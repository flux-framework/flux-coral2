/************************************************************\
 * Copyright 2021 Lawrence Livermore National Security, LLC
 * (c.f. AUTHORS, NOTICE.LLNS, COPYING)
 *
 * This file is part of the Flux resource manager framework.
 * For details, see https://github.com/flux-framework.
 *
 * SPDX-License-Identifier: LGPL-3.0
\************************************************************/
#define FLUX_SHELL_PLUGIN_NAME "pmi-cray-pals"

#if HAVE_CONFIG_H
#include "config.h"
#endif
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdlib.h>
#include <unistd.h>
#include <argz.h>
#include <libgen.h>

#include <jansson.h>

#include <flux/hostlist.h>
#include <flux/shell.h>
#include <flux/taskmap.h>

#include "eventlog_helpers.h"

/* PALS --- interface with HPE/Cray's PMI.
 *
 * Cray uses an interface that is different from PMI, PMI2, or PMIX.
 * The interface consists of setting environment variables and writing
 * out a file for Cray software to read in; Cray software then sets
 * up PMI itself, with no further communication from the resource manager.
 *
 * To support Cray PMI, the launcher must perform these tasks:
 * 1. Assign an apid to the application
 * (arbitrary string, unique per-application)
 * 2. On each compute node, create a spool directory
 * (in this case, FLUX_JOB_TMPDIR) owned by the application's user
 * 3. On each compute node, write an apinfo file in
 * the spool directory. The file should consist of a pals_header_t
 * followed by the other pals_*_t structs in the order defined by the
 * header. The structs will be written directly to disk with no kind of
 * encoding or padding whatsoever (!).
 * 4. Set environment variables for each spawned process (listed below)
 * 5. Remove the spool directory on each compute node when
 * the application is complete
 *
 * These environment variables should be set for each process:
 * PALS_APID - Application ID (arbitrary string, mostly used for logging)
 * PALS_APINFO - Full path to the apinfo file
 * PALS_RANKID - Global rank ID for this process
 * PALS_NODEID - Node index for this process
 * (e.g. head compute node is 0, next compute node is 1, etc)
 * PALS_SPOOL_DIR - Application-specific directory for keeping runtime files
 * PMI_CONTROL_PORT - Port numbers for libpals to bind on each compute node as
 * a comma-separated list.
 * The list of ports must be the same for all nodes in the job.
 * The list must be nonoverlapping for each concurrent application running
 * on the same node(s). No service is expected to be behind the port---
 * instead, the port is used by libpals internally. A port does not need
 * to be set if the job takes only one node.
 * The number of ports that must be specified is (# of MPMD commands) + 1.
 * PMI_CONTROL_FD - (optional) a comma-separated list of open socket FDs
 * corresponding to the PMI_CONTROL_PORT variable. If not provided,
 * libpals will open the sockets itself.
 *
 * See also `src/job-manager/plugins/cray_pals_port_distributor.c` for
 * the PMI_CONTROL_PORT distribution mechanism.
 */

/* Application file format version */
#define PALS_APINFO_VERSION 5

typedef struct {
    int version;                 // Set to PALS_APINFO_VERSION
    size_t total_size;           // Size of the whole file in bytes
    size_t comm_profile_size;    // sizeof(pals_comm_profile_t)
    size_t comm_profile_offset;  // offset from beginning of file to the first comm_profile_t
    int ncomm_profiles;          // number of comm_profile_t (not used yet, set to 0)
    size_t cmd_size;             // sizeof(pals_cmd_t)
    size_t cmd_offset;           // offset to first pals_cmd_t
    int ncmds;                   // number of commands (MPMD programs)
    size_t pe_size;              // sizeof(pals_pe_t)
    size_t pe_offset;            // offset to first pals_pe_t
    int npes;                    // number of PEs (processes/ranks)
    size_t node_size;            // sizeof(pals_node_t)
    size_t node_offset;          // offset to first pals_node_t
    int nnodes;                  // number of nodes
    size_t nic_size;             // sizeof(pals_hsn_nic_t)
    size_t nic_offset;           // offset to first pals_hsn_nic_t
    int nnics;                   // number of NICs (not used yet, set to 0)
    size_t status_offset;        // offset to an array of ints all initialized to 0
                                 // array size is the number of ranks on the node
    size_t dist_size;            // sizeof(pals_distance_t) + max_nics_per_node * sizeof(uint8_t)
    size_t dist_offset;          // offset to first pals_distance_t
} pals_header_t;

/* Network communication profile structure */
typedef struct {
    uint32_t svc_id;          /**< CXI service ID */
    uint32_t traffic_classes; /**< Bitmap of allowed traffic classes */
    uint16_t vnis[4];         /**< VNIs for this service */
    uint8_t nvnis;            /**< Number of VNIs */
    char device_name[16];     /**< NIC device for this profile */
} pals_comm_profile_t;

/* MPMD command information structure */
typedef struct {
    int npes;         /* Number of tasks in this command */
    int pes_per_node; /* Number of tasks per node */
    int cpus_per_pe;  /* Number of CPUs per task */
} pals_cmd_t;

/* PE (i.e. task) information structure */
typedef struct {
    int localidx; /* Node-local PE index */
    int cmdidx;   /* Command index for this PE */
    int nodeidx;  /* Node index this PE is running on */
} pals_pe_t;

/* Node information structure */
typedef struct {
    int nid;           /* Node ID */
    char hostname[64]; /* Node hostname */
} pals_node_t;

/* NIC address type */
typedef enum { PALS_ADDR_IPV4, PALS_ADDR_IPV6, PALS_ADDR_MAC } pals_address_type_t;

/* NIC information structure */
typedef struct {
    int nodeidx;                      /**< Node index this NIC belongs to */
    pals_address_type_t address_type; /**< Address type for this NIC */
    char address[64];                 /**< Address of this NIC */
    short numa_node;                  /**< NUMA node it is in */
    char device_name[16];             /**< Device name */
    long _unused[2];
} pals_hsn_nic_t;

/* Distance to NIC information structure */
typedef struct {
    uint8_t num_nic_distances;     /**< Number of CPU->NIC distances on current node */
    uint8_t accelerator_distances; /**< Accel distances too? (bool). Set to 0, not used. */
    uint8_t distances[0];          /* < One for each NIC, two if using accelerators */
} pals_distance_t;

struct task_placement {
    int *task_counts;
    int **task_ids;
};

/* If true, don't edit LD_LIBRARY_PATH
 */
static int no_edit_env;

/*
 * Return a 'struct hostlist' containing the hostnames of every shell rank.
 */
static struct hostlist *hostlist_from_array (json_t *nodelist_array)
{
    size_t index;
    json_t *value;
    struct hostlist *hlist;
    const char *entry;

    if (!json_is_array (nodelist_array) || !(hlist = hostlist_create ())) {
        return NULL;
    }
    json_array_foreach (nodelist_array, index, value) {
        if (!(entry = json_string_value (value)) || hostlist_append (hlist, entry) < 0) {
            hostlist_destroy (hlist);
            return NULL;
        }
    }
    return hlist;
}

/* Wrap calls to write for checks to EINTR/EAGAIN */
static int safe_write (int fd, const void *buf, size_t size)
{
    ssize_t rc;
    while (size > 0) {
        rc = write (fd, buf, size);
        if (rc < 0) {
            if ((errno == EAGAIN) || (errno == EINTR))
                continue;
            return -1;
        } else {
            buf += rc;
            size -= rc;
        }
    }
    return 0;
}

/*
 * Return an array of initialized pals_pe_t structures.
 * 'task_counts' should be an array of length 'nnodes' specifying
 * how many tasks are on each node in the job.
 * 'tids' should be a 2D ragged array giving the job ranks for each
 * node in the job.
 */
static pals_pe_t *setup_pals_pes (int ntasks, int nnodes, int *task_counts, int **tids)
{
    pals_pe_t *pes = NULL;
    int nodeidx, localidx, taskid;

    if (!(pes = calloc (ntasks, sizeof (pals_pe_t)))) {
        return NULL;
    }
    for (nodeidx = 0; nodeidx < nnodes; nodeidx++) {  // for each node identifier nodeidx ...
        for (localidx = 0; localidx < task_counts[nodeidx];
             localidx++) {  // for each task within that node
            // get the global task ID of that task
            taskid = tids[nodeidx][localidx];
            if (taskid >= ntasks) {
                shell_log_error ("taskid %d (on node %d) >= ntasks %d", taskid, nodeidx, ntasks);
                free (pes);
                return NULL;
            }
            pes[taskid].nodeidx = nodeidx;
            pes[taskid].localidx = localidx;
            pes[taskid].cmdidx = 0;
        }
    }
    return pes;
}

/*
 * Initialize a pals_cmd_t.
 */
static void setup_pals_cmd (pals_cmd_t *cmd,
                            int ntasks,
                            int nnodes,
                            int cores_per_task,
                            int *task_counts)
{
    int max_tasks_per_node = 1;

    cmd->npes = ntasks;
    cmd->cpus_per_pe = cores_per_task;
    for (int i = 0; i < nnodes; ++i) {
        max_tasks_per_node =
            max_tasks_per_node > task_counts[i] ? max_tasks_per_node : task_counts[i];
    }
    cmd->pes_per_node = max_tasks_per_node;
}

/*
 * Fill in the apinfo header.
 */
static void build_header (pals_header_t *hdr, int ncmds, int npes, int nnodes)
{
    size_t offset = sizeof (pals_header_t);

    memset (hdr, 0, sizeof (pals_header_t));
    hdr->version = PALS_APINFO_VERSION;

    hdr->comm_profile_size = sizeof (pals_comm_profile_t);
    hdr->comm_profile_offset = offset;
    hdr->ncomm_profiles = 0;
    offset += hdr->comm_profile_size * hdr->ncomm_profiles;

    hdr->cmd_size = sizeof (pals_cmd_t);
    hdr->cmd_offset = offset;
    hdr->ncmds = ncmds;
    offset += hdr->cmd_size * hdr->ncmds;

    hdr->pe_size = sizeof (pals_pe_t);
    hdr->pe_offset = offset;
    hdr->npes = npes;
    offset += hdr->pe_size * hdr->npes;

    hdr->node_size = sizeof (pals_node_t);
    hdr->node_offset = offset;
    hdr->nnodes = nnodes;
    offset += hdr->node_size * hdr->nnodes;

    hdr->nic_size = sizeof (pals_hsn_nic_t);
    hdr->nic_offset = offset;
    hdr->nnics = 0;
    offset += hdr->nic_size * hdr->nnics;

    hdr->status_offset = 0;
    hdr->dist_size = 0;
    hdr->dist_offset = 0;

    hdr->total_size = offset;
}

/*
 * Write the job's hostlist to the file.
 */
static int write_pals_nodes (int fd, struct hostlist *hlist)
{
    const char *entry;
    pals_node_t node;
    int node_index = 0;

    if (!(entry = hostlist_first (hlist))) {
        return -1;
    }
    while (entry) {
        node.nid = node_index++;
        if (snprintf (node.hostname, sizeof (node.hostname), "%s", entry) >= sizeof (node.hostname)
            || safe_write (fd, &node, sizeof (pals_node_t)) < 0) {
            return -1;
        }
        entry = hostlist_next (hlist);
    }
    return 0;
}

/*
 * Allocate and return a `struct task_placement`, returning
 * NULL on error. Destroy with `task_placement_destroy`.
 */
static struct task_placement *task_placement_create (int nnodes)
{
    struct task_placement *ret = NULL;

    if (!(ret = malloc (sizeof (struct task_placement)))) {
        return NULL;
    }
    if (!(ret->task_counts = malloc (sizeof (*(ret->task_counts)) * nnodes))) {
        free (ret);
        return NULL;
    }
    // use calloc so we can call `free` indiscriminately on pointers
    // in the `task_ids` array
    if (!(ret->task_ids = calloc (nnodes, sizeof (*(ret->task_ids))))) {
        free (ret->task_counts);
        free (ret);
        return NULL;
    }
    return ret;
}

/*
 * Destroy a `struct task_placement`. The elements of the `task_ids` array
 * must either be pointers to valid memory or NULL.
 */
static void task_placement_destroy (struct task_placement *t, int nnodes)
{
    if (!t) {
        return;
    }
    free (t->task_counts);
    for (int i = 0; i < nnodes; ++i) {
        free (t->task_ids[i]);
    }
    free (t->task_ids);
    free (t);
}

/*
 * Return a mapping from nodes to the task IDs they are associated with.
 */
static struct task_placement *get_task_placement (flux_shell_t *shell)
{
    struct task_placement *ret = NULL;
    const struct taskmap *map;
    const struct idset *idset;
    int nnodes;
    unsigned int curr_task_id = 0;

    if (!(map = flux_shell_get_taskmap (shell)) || (nnodes = taskmap_nnodes (map)) < 1
        || !(ret = task_placement_create (nnodes))) {
        return NULL;
    }

    for (int nodeid = 0; nodeid < nnodes; ++nodeid) {
        if ((ret->task_counts[nodeid] = taskmap_ntasks (map, nodeid)) < 0
            || !(ret->task_ids[nodeid] =
                     malloc (sizeof (*(ret->task_ids[nodeid])) * ret->task_counts[nodeid]))
            || !(idset = taskmap_taskids (map, nodeid))) {
            shell_log_error ("Error fetching task idset for nodeid %i", nodeid);
            task_placement_destroy (ret, nnodes);
            return NULL;
        }
        curr_task_id = idset_first (idset);
        for (int localtasknum = 0; localtasknum < ret->task_counts[nodeid]; ++localtasknum) {
            if (curr_task_id == IDSET_INVALID_ID) {
                shell_log_error ("Fetched an invalid ID for nodeid %i", nodeid);
                task_placement_destroy (ret, nnodes);
                return NULL;
            }
            ret->task_ids[nodeid][localtasknum] = (int)curr_task_id;
            curr_task_id = idset_next (idset, curr_task_id);
        }
    }

    return ret;
}

static int get_cores_per_task (flux_shell_t *shell, int ntasks)
{
    int version, task_slots, cores_per_slot;

    if (flux_shell_jobspec_info_unpack (shell,
                                        "{s:i, s:i, s:i}",
                                        "version",
                                        &version,
                                        "nslots",
                                        &task_slots,
                                        "cores_per_slot",
                                        &cores_per_slot)
            < 0
        || version != 1) {
        shell_log_error ("Error calculating 'cores_per_task' from jobspec");
        return -1;
    }
    return (int)((task_slots * cores_per_slot) / ntasks);
}

/*
 * Write the application information file and return the number
 * of shells in the job.
 */
static int create_apinfo (const char *apinfo_path, flux_shell_t *shell)
{
    int fd = -1;
    pals_header_t hdr;
    pals_cmd_t cmd;
    pals_pe_t *pes = NULL;
    int shell_size, ntasks, cores_per_task, nnodes = 0;
    json_t *nodelist_array;
    struct hostlist *hlist = NULL;
    struct task_placement *placement = NULL;

    // Get shell size and hostlist
    if (flux_shell_info_unpack (shell,
                                "{s:i, s:i, s:{s:{s:o}}}",
                                "size",
                                &shell_size,
                                "ntasks",
                                &ntasks,
                                "R",
                                "execution",
                                "nodelist",
                                &nodelist_array)
            < 0
        || !(hlist = hostlist_from_array (nodelist_array))) {
        shell_log_error ("Error creating hostlists");
        goto error;
    }
    nnodes = hostlist_count (hlist);
    if (nnodes < 1 || !(placement = get_task_placement (shell))
        || (cores_per_task = get_cores_per_task (shell, ntasks)) < 0) {
        shell_log_error ("Error calculating task placement");
        goto error;
    }
    // Gather the header, pes, and cmds structs
    build_header (&hdr, 1, ntasks, nnodes);
    setup_pals_cmd (&cmd, ntasks, nnodes, cores_per_task, placement->task_counts);
    if (!(pes = setup_pals_pes (ntasks, nnodes, placement->task_counts, placement->task_ids))) {
        shell_log_error ("Error initializing pals_pe_t structs");
        goto error;
    }
    // Write the header, cmds, pes, and nodes structs
    if ((fd = creat (apinfo_path, S_IRUSR | S_IWUSR)) == -1
        || safe_write (fd, &hdr, sizeof (pals_header_t)) < 0
        || safe_write (fd, &cmd, (hdr.ncmds * sizeof (pals_cmd_t))) < 0
        || safe_write (fd, pes, (hdr.npes * sizeof (pals_pe_t))) < 0
        || write_pals_nodes (fd, hlist) < 0 || fsync (fd) == -1) {
        shell_log_errno ("Couldn't write apinfo to disk");
        goto error;
    }
    shell_trace ("created pals apinfo file %s", apinfo_path);

cleanup:

    hostlist_destroy (hlist);
    task_placement_destroy (placement, nnodes);
    free (pes);
    close (fd);
    return shell_size;

error:

    shell_size = -1;
    goto cleanup;
}

static int read_future (flux_future_t *fut,
                        char *buf,
                        size_t bufsize,
                        json_int_t *random,
                        double timeout)
{
    json_t *o = NULL;
    json_t *context = NULL;
    json_t *array;
    const char *name = "<no events received>", *event = NULL;
    size_t index = 0;
    json_t *value;
    json_int_t portnum;
    int bytes_written;

    while (flux_future_wait_for (fut, timeout) == 0
           && flux_job_event_watch_get (fut, &event) == 0) {
        if (!(o = eventlog_entry_decode (event))) {
            shell_log_errno ("Error decoding eventlog entry");
            return -1;
        }
        if (eventlog_entry_parse (o, NULL, &name, &context) < 0) {
            shell_log_errno ("Error parsing eventlog entry");
            json_decref (o);
            return -1;
        }
        if (!strcmp (name, "start")) {
            /*  'start' event with no cray_port_distribution event.
             *  assume cray-pals jobtap plugin is not loaded.
             */
            shell_debug (
                "cray_pals_port_distributor jobtap plugin is not "
                "loaded: proceeding without PMI_CONTROL_PORT set");
            return 0;
        }
        if (!strcmp (name, "cray_port_distribution")) {
            if (json_unpack (context, "{s:o, s:I}", "ports", &array, "random_integer", random)
                < 0) {
                shell_log_error ("Error unpacking 'cray_port_distribution' event");
                json_decref (o);
                return -1;
            }
            json_array_foreach (array, index, value) {
                if ((portnum = json_integer_value (value)) == 0) {
                    shell_log_error ("Received non-integer port");
                    json_decref (o);
                    return -1;
                }
                if (index == 0) {
                    bytes_written = snprintf (buf, bufsize, "%" JSON_INTEGER_FORMAT, portnum);
                } else {
                    bytes_written = snprintf (buf, bufsize, ",%" JSON_INTEGER_FORMAT, portnum);
                }
                buf += bytes_written;
                bufsize -= bytes_written;
                if (bufsize < 10) {
                    shell_log_error ("Port buffer exhausted");
                    json_decref (o);
                    return -1;
                }
            }
            json_decref (o);
            /*  Return 1 on success
             */
            return 1;
        } else {
            flux_future_reset (fut);
            json_decref (o);
        }
    }
    shell_log_error ("Timed out waiting for start event, last event received was %s", name);
    return -1;
}

static int get_pals_ports (flux_shell_t *shell, json_int_t jobid)
{
    flux_t *h;
    char buf[256];
    flux_future_t *fut = NULL;
    int rc;
    json_int_t random;
    double timeout = 10.0;

    if (!(h = flux_shell_get_flux (shell))
        || !(fut = flux_job_event_watch (h, (flux_jobid_t)jobid, "eventlog", 0))) {
        shell_log_error ("Error creating event_watch future");
        return -1;
    }
    if (flux_shell_getopt_unpack (shell, "cray-pals", "{s?F}", "timeout", &timeout) < 0
        || (rc = read_future (fut, buf, sizeof (buf), &random, timeout)) < 0)
        shell_log_error ("Error reading ports from eventlog");
    flux_future_destroy (fut);

    /* read_future() returns 1 if port distribution event was found:
     */
    if (rc == 1) {
        if (flux_shell_setenvf (shell, 1, "PMI_CONTROL_PORT", "%s", buf) < 0
            || flux_shell_setenvf (shell, 1, "PMI_SHARED_SECRET", "%ju", (uintmax_t)random) < 0) {
            return -1;
        }
        shell_trace ("set PMI_CONTROL_PORT to %s", buf);
        shell_trace ("set PMI_SHARED_SECRET to %ju", (uintmax_t)random);
    }
    return rc;
}

/*
 * Remove the first occurrence of 'path' from the environment variable
 * 'name', which is assumed to be a colon-separated list.
 * Return -1 on error, 0 if found and removed.
 */
static int remove_path_from_cmd_env (flux_cmd_t *cmd, const char *name, const char *path)
{
    const char *searchpath;
    char *argz;
    size_t argz_len;
    int rc = -1;

    if (!(searchpath = flux_cmd_getenv (cmd, name))
        || argz_create_sep (searchpath, ':', &argz, &argz_len) != 0)
        return -1;

    char *entry = NULL;
    while ((entry = argz_next (argz, argz_len, entry))) {
        if (!strcmp (entry, path)) {  // match!
            argz_delete (&argz, &argz_len, entry);
            if (argz && strlen (argz) > 0) {
                argz_stringify (argz, argz_len, ':');
                if (flux_cmd_setenvf (cmd, 1, name, "%s", argz) < 0)
                    goto out;
            } else
                flux_cmd_unsetenv (cmd, name);
            rc = 0;
            break;
        }
    }
out:
    free (argz);
    return rc;
}

/*
 * Set job-wide environment variables for LibPALS
 */
static int set_environment (flux_shell_t *shell, const char *apinfo_path, int shell_size)
{
    int rank = -1;
    json_int_t jobid;
    const char *tmpdir;

    // must unset PMI_CONTROL_PORT if it was set by Slurm
    flux_shell_unsetenv (shell, "PMI_CONTROL_PORT");
    if (flux_shell_info_unpack (shell, "{s:i, s:I}", "rank", &rank, "jobid", &jobid) < 0
        || flux_shell_setenvf (shell, 1, "PALS_NODEID", "%i", rank) < 0
        || flux_shell_setenvf (shell, 1, "PALS_APID", "%" JSON_INTEGER_FORMAT, jobid) < 0
        || !(tmpdir = flux_shell_getenv (shell, "FLUX_JOB_TMPDIR"))
        || flux_shell_setenvf (shell, 1, "PALS_SPOOL_DIR", "%s", tmpdir) < 0
        || flux_shell_setenvf (shell, 1, "PALS_APINFO", "%s", apinfo_path) < 0
        // no need to set ports if shell_size == 1
        || (shell_size > 1 && get_pals_ports (shell, jobid) < 0)) {
        shell_log_error ("Error setting libpals environment");
        return -1;
    }
    shell_trace ("set PALS_NODEID to %i", rank);
    shell_trace ("set PALS_APID to %" JSON_INTEGER_FORMAT, jobid);
    shell_trace ("set PALS_SPOOL_DIR to %s", tmpdir);
    shell_trace ("set PALS_APINFO to %s", apinfo_path);
    return 0;
}

/*
 * Create the LibPALS apinfo file in the job's tempdir and set
 * the LibPALS environment.
 */
static int libpals_init (flux_plugin_t *p, const char *topic, flux_plugin_arg_t *args, void *data)
{
    const char *tmpdir;
    char apinfo_path[1024];
    flux_shell_t *shell = flux_plugin_get_shell (p);
    int shell_size;

    if (!(tmpdir = flux_shell_getenv (shell, "FLUX_JOB_TMPDIR"))
        || snprintf (apinfo_path, sizeof (apinfo_path), "%s/%s", tmpdir, "libpals_apinfo")
               >= sizeof (apinfo_path)
        || (shell_size = create_apinfo (apinfo_path, shell)) < 1
        || set_environment (shell, apinfo_path, shell_size) < 0) {
        return -1;
    }
    return 0;
}

/*
 * Set the 'PALS_RANKID' environment variable to the value of 'FLUX_TASK_RANK'
 */
static int libpals_task_init (flux_plugin_t *p,
                              const char *topic,
                              flux_plugin_arg_t *args,
                              void *data)
{
    flux_shell_t *shell = flux_plugin_get_shell (p);
    flux_shell_task_t *task;
    flux_cmd_t *cmd;
    int task_rank;

    if (!shell || !(task = flux_shell_current_task (shell)) || !(cmd = flux_shell_task_cmd (task))
        || flux_shell_task_info_unpack (task, "{s:i}", "rank", &task_rank) < 0
        || flux_cmd_setenvf (cmd, 1, "PALS_RANKID", "%d", task_rank) < 0) {
        return -1;
    }
    shell_trace ("set PALS_RANKID to %d", task_rank);

    if (!no_edit_env) {
        const char *pmipath = flux_conf_builtin_get ("pmi_library_path", FLUX_CONF_AUTO);
        char *cpy = NULL;
        char *dir;
        if (pmipath && (cpy = strdup (pmipath)) && (dir = dirname (cpy))) {
            while (remove_path_from_cmd_env (cmd, "LD_LIBRARY_PATH", dir) == 0)
                shell_trace ("edit LD_LIBRARY_PATH remove %s", dir);
        }
        free (cpy);
    }
    return 0;
}

static bool member_of_csv (const char *list, const char *name)
{
    char *argz = NULL;
    size_t argz_len;

    if (argz_create_sep (list, ',', &argz, &argz_len) == 0) {
        const char *entry = NULL;

        while ((entry = argz_next (argz, argz_len, entry))) {
            if (!strcmp (entry, name)) {
                free (argz);
                return true;
            }
        }
        free (argz);
    }
    return false;
}

/*
 * Unset all PALS_* variables.
 */
static int unset_pals_env (flux_shell_t *shell)
{
    char *pals_env[] = {"PALS_NODEID",
                        "PALS_RANKID",
                        "PALS_APINFO",
                        "PALS_APID",
                        "PALS_SPOOL_DIR",
                        "PALS_FD",
                        "PALS_DEPTH",
                        "PALS_LOCAL_RANKID",
                        "PALS_LOCAL_SIZE",
                        "PMI_JOBID",
                        "PMI_CONTROL_PORT",
                        "PMI_SHARED_SECRET",
                        "PMI_JOBID",
                        "PMI_LOCAL_RANK",
                        "PMI_LOCAL_SIZE"};
    for (int i = 0; i < sizeof (pals_env) / sizeof (pals_env[0]); i++) {
        flux_shell_unsetenv (shell, pals_env[i]);
    }
    return 0;
}

int flux_plugin_init (flux_plugin_t *p)
{
    const char *pmi_opt = NULL;
    flux_shell_t *shell;

    if (!(shell = flux_plugin_get_shell (p))
        || flux_plugin_set_name (p, FLUX_SHELL_PLUGIN_NAME) < 0)
        return -1;

    if (flux_shell_getopt_unpack (shell, "pmi", "s", &pmi_opt) < 0) {
        shell_log_error ("pmi shell option must be a string");
        return -1;
    }
    if (!pmi_opt || !member_of_csv (pmi_opt, "cray-pals"))
        // plugin disabled, unset all inherited PALS_ variables
        // otherwise libPALS might pick up and try to use them
        return unset_pals_env (shell);

    shell_debug ("enabled");

    // If -o cray-pals.no-edit-env is was specified set a flag for later
    no_edit_env = 0;
    (void)flux_shell_getopt_unpack (shell, "cray-pals", "{s?i}", "no-edit-env", &no_edit_env);

    if (flux_plugin_add_handler (p, "shell.init", libpals_init, NULL) < 0
        || flux_plugin_add_handler (p, "task.init", libpals_task_init, NULL) < 0)
        return -1;

    return 0;
}

// vi:ts=4 sw=4 expandtab
