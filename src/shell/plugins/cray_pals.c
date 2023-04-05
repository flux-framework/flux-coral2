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

#include <jansson.h>

#include <flux/hostlist.h>
#include <flux/shell.h>

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
#define PALS_APINFO_VERSION 1

/* File header structure */
typedef struct {
    int version;               // Set to PALS_APINFO_VERSION
    size_t total_size;         // Size of the whole file in bytes
    size_t comm_profile_size;  // sizeof(pals_comm_profile_t)
    // offset from beginning of file to the first comm_profile_t
    size_t comm_profile_offset;
    // number of comm_profile_t (not used yet, set to 0)
    int ncomm_profiles;
    size_t cmd_size;  // sizeof(pals_cmd_t)
    // offset from beginning of file to the first pals_cmd_t
    size_t cmd_offset;
    int ncmds;       // number of commands (MPMD programs)
    size_t pe_size;  // sizeof(pals_pe_t)
    // offset from beginning of file to the first pals_pe_t
    size_t pe_offset;
    int npes;          // number of PEs (processes/ranks)
    size_t node_size;  // sizeof(pals_node_t)
    // offset from beginning of file to the first pals_node_t
    size_t node_offset;
    int nnodes;       // number of nodes
    size_t nic_size;  // sizeof(pals_nic_t)
    // offset from beginning of file to the first pals_nic_t
    size_t nic_offset;
    int nnics;  // number of NICs (not used yet, set to 0)
} pals_header_t;

/* Network communication profile structure */
typedef struct {
    char tokenid[40];    /* Token UUID */
    int vni;             /* VNI associated with this token */
    int vlan;            /* VLAN associated with this token */
    int traffic_classes; /* Bitmap of allowed traffic classes */
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
    int nodeidx;                      /* Node index this NIC belongs to */
    pals_address_type_t address_type; /* Address type for this NIC */
    char address[40];                 /* Address of this NIC */
} pals_nic_t;

struct task_placement {
    int *task_counts;
    int **task_ids;
};

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
    json_array_foreach (nodelist_array, index, value)
    {
        if (!(entry = json_string_value (value))
            || hostlist_append (hlist, entry) < 0) {
            hostlist_destroy (hlist);
            return NULL;
        }
    }
    return hlist;
}

static void freemany (int **ptr, int size)
{
    for (int i = 0; i < size; ++i) {
        free (ptr[i]);
    }
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
    for (nodeidx = 0; nodeidx < nnodes;
         nodeidx++) {  // for each node identifier nodeidx ...
        for (localidx = 0; localidx < task_counts[nodeidx];
             localidx++) {  // for each task within that node
            // get the global task ID of that task
            taskid = tids[nodeidx][localidx];
            if (taskid >= ntasks) {
                shell_log_error ("taskid %d (on node %d) >= ntasks %d",
                                 taskid,
                                 nodeidx,
                                 ntasks);
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

    hdr->nic_size = sizeof (pals_nic_t);
    hdr->nic_offset = offset;
    hdr->nnics = 0;
    offset += hdr->nic_size * hdr->nnics;

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
        if (snprintf (node.hostname, sizeof (node.hostname), "%s", entry)
                >= sizeof (node.hostname)
            || safe_write (fd, &node, sizeof (pals_node_t)) < 0) {
            return -1;
        }
        entry = hostlist_next (hlist);
    }
    return 0;
}

/*
 * Return the number of job tasks assigned to each shell rank.
 */
static int *get_task_counts_pershell (flux_shell_t *shell, int shell_size)
{
    int *task_counts;
    int i;

    if (!(task_counts = malloc (shell_size * sizeof (shell_size)))) {
        return NULL;
    }
    for (i = 0; i < shell_size; ++i) {
        if (flux_shell_rank_info_unpack (shell,
                                         i,
                                         "{s:i}",
                                         "ntasks",
                                         &task_counts[i]) < 0) {
            free (task_counts);
            return NULL;
        }
    }
    return task_counts;
}

/*
 * Return the job ranks assigned to each shell rank.
 * 'task_counts' should be an array of length 'shell_size' specifying
 * how many tasks are assigned to each shell in the job.
 */
static int **get_task_ids_pershell (int *task_counts_pershell, int shell_size)
{
    int **task_ids;
    int shell_rank, j, curr_task_id = 0;

    if (!(task_ids = malloc (shell_size * sizeof (task_counts_pershell)))) {
        return NULL;
    }
    for (shell_rank = 0; shell_rank < shell_size; ++shell_rank) {
        if (!(task_ids[shell_rank] = malloc (task_counts_pershell[shell_rank]
                                             * sizeof (task_counts_pershell)))) {
            for (j = 0; j < shell_rank; ++j) {
                free (task_ids[shell_rank]);
            }
            free (task_ids);
            return NULL;
        }
        for (j = 0; j < task_counts_pershell[shell_rank]; ++j) {
            task_ids[shell_rank][j] = curr_task_id++;
        }
    }
    return task_ids;
}

/*
 * Return the placement of job ranks on nodes.
 */
static struct task_placement *get_task_placement_pernode (int nnodes,
                                                          int shell_size,
                                                          int *shells_to_nodes,
                                                          int *task_counts_pershell,
                                                          int **task_ids_pershell)
{
    int *task_counts_pernode = NULL, **task_ids_pernode = NULL;
    // keep track of how much each entry in 'task_ids_pernode' is filled
    int *task_ids_pernode_fill = NULL;
    int shell_rank, node_index, i;
    struct task_placement *ret = NULL;

    if (!(task_counts_pernode = calloc (nnodes, sizeof (nnodes)))
        || !(task_ids_pernode_fill = calloc (nnodes, sizeof (nnodes)))
        || !(task_ids_pernode = malloc (nnodes * sizeof (task_counts_pernode)))
        || !(ret = malloc (sizeof (struct task_placement)))) {
        goto error;
    }
    for (shell_rank = 0; shell_rank < shell_size; ++shell_rank) {
        // count the number of tasks per node
        node_index = shells_to_nodes[shell_rank];
        task_counts_pernode[node_index] += task_counts_pershell[shell_rank];
    }
    // make space for task IDs for each node
    for (node_index = 0; node_index < nnodes; ++node_index) {
        if (!(task_ids_pernode[node_index] =
                  malloc (task_counts_pernode[node_index] * sizeof (nnodes)))) {
            freemany (task_ids_pernode, node_index);
            goto error;
        }
    }
    for (shell_rank = 0; shell_rank < shell_size; ++shell_rank) {
        node_index = shells_to_nodes[shell_rank];
        for (i = 0; i < task_counts_pershell[shell_rank]; ++i) {
            task_ids_pernode[node_index][task_ids_pernode_fill[node_index]] =
                task_ids_pershell[shell_rank][i];
            task_ids_pernode_fill[node_index]++;
        }
    }

    free (task_ids_pernode_fill);
    ret->task_ids = task_ids_pernode;
    ret->task_counts = task_counts_pernode;
    return ret;

error:
    free (task_ids_pernode_fill);
    free (task_counts_pernode);
    free (task_ids_pernode);
    free (ret);
    return NULL;
}

static struct task_placement *get_task_placement (flux_shell_t *shell,
                                                  int nnodes,
                                                  int shell_size,
                                                  struct hostlist *hlist,
                                                  struct hostlist *hlist_uniq)
{
    int shell_rank, *shells_to_nodes = NULL, *task_counts_pershell = NULL;
    int **task_ids_pershell = NULL, node_index;
    struct task_placement *ret = NULL;
    const char *entry;

    // get task placement per shell
    if (!(shells_to_nodes = malloc (shell_size * sizeof (shell_size)))
        || !(task_counts_pershell = get_task_counts_pershell (shell, shell_size))
        || !(task_ids_pershell =
                 get_task_ids_pershell (task_counts_pershell, shell_size))) {
        shell_log_errno ("Error getting per-shell task IDs");
        goto cleanup;
    }

    // find the node index of each shell rank
    for (shell_rank = 0; shell_rank < shell_size; ++shell_rank) {
        if (!(entry = hostlist_nth (hlist, shell_rank))
            || (node_index = hostlist_find (hlist_uniq, entry)) < 0) {
            shell_log_error ("Error mapping shells to nodes");
            goto cleanup;
        }
        shells_to_nodes[shell_rank] = node_index;  // save the node index
    }
    if (!(ret = get_task_placement_pernode (nnodes,
                                            shell_size,
                                            shells_to_nodes,
                                            task_counts_pershell,
                                            task_ids_pershell))) {
        shell_log_errno ("Error getting per-node task placement");
    }

cleanup:
    free (shells_to_nodes);
    free (task_counts_pershell);
    if (task_ids_pershell) {
        freemany (task_ids_pershell, shell_size);
        free (task_ids_pershell);
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
                                        &cores_per_slot) < 0
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
    struct hostlist *hlist = NULL, *hlist_uniq = NULL;
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
                                &nodelist_array) < 0
        || !(hlist = hostlist_from_array (nodelist_array))
        || !(hlist_uniq = hostlist_copy (hlist))) {
        shell_log_error ("Error creating hostlists");
        goto error;
    }
    hostlist_uniq (hlist_uniq);
    nnodes = hostlist_count (hlist_uniq);
    if (nnodes < 1
        || !(placement =
                 get_task_placement (shell, nnodes, shell_size, hlist, hlist_uniq))
        || (cores_per_task = get_cores_per_task (shell, ntasks)) < 0) {
        shell_log_error ("Error calculating task placement");
        goto error;
    }
    // Gather the header, pes, and cmds structs
    build_header (&hdr, 1, ntasks, nnodes);
    setup_pals_cmd (&cmd, ntasks, nnodes, cores_per_task, placement->task_counts);
    if (!(pes = setup_pals_pes (ntasks,
                                nnodes,
                                placement->task_counts,
                                placement->task_ids))) {
        shell_log_error ("Error initializing pals_pe_t structs");
        goto error;
    }
    // Write the header, cmds, pes, and nodes structs
    if ((fd = creat (apinfo_path, S_IRUSR | S_IWUSR)) == -1
        || safe_write (fd, &hdr, sizeof (pals_header_t)) < 0
        || safe_write (fd, &cmd, (hdr.ncmds * sizeof (pals_cmd_t))) < 0
        || safe_write (fd, pes, (hdr.npes * sizeof (pals_pe_t))) < 0
        || write_pals_nodes (fd, hlist_uniq) < 0 || fsync (fd) == -1) {
        shell_log_errno ("Couldn't write apinfo to disk");
        goto error;
    }

cleanup:

    hostlist_destroy (hlist);
    hostlist_destroy (hlist_uniq);
    if (placement) {
        free (placement->task_counts);
        freemany (placement->task_ids, nnodes);
        free (placement->task_ids);
        free (placement);
    }
    free (pes);
    close (fd);
    return shell_size;

error:

    shell_size = -1;
    goto cleanup;
}

static int read_future (flux_future_t *fut, char *buf, size_t bufsize)
{
    json_t *o = NULL;
    json_t *context = NULL;
    json_t *array;
    const char *name, *event = NULL;
    size_t index = 0;
    json_t *value;
    json_int_t portnum;
    int bytes_written;

    while (flux_future_wait_for (fut, 10.0) == 0
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
            shell_debug ("cray_pals_port_distributor jobtap plugin is not "
                         "loaded: proceeding without PMI_CONTROL_PORT set");
            return 0;
        }
        if (!strcmp (name, "cray_port_distribution")) {
            if (!(array = json_object_get (context, "ports"))) {
                shell_log_error ("No port context in cray_port_distribution");
                json_decref (o);
                return -1;
            }
            json_array_foreach (array, index, value)
            {
                if ((portnum = json_integer_value (value)) == 0) {
                    shell_log_error ("Received non-integer port");
                    json_decref (o);
                    return -1;
                }
                if (index == 0) {
                    bytes_written =
                        snprintf (buf, bufsize, "%" JSON_INTEGER_FORMAT, portnum);
                } else {
                    bytes_written =
                        snprintf (buf, bufsize, ",%" JSON_INTEGER_FORMAT, portnum);
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
    shell_log_error ("Timed out waiting for start event");
    return -1;
}

static int get_pals_ports (flux_shell_t *shell, json_int_t jobid)
{
    flux_t *h;
    char buf[256];
    flux_future_t *fut = NULL;
    int rc;

    if (!(h = flux_shell_get_flux (shell))
        || !(fut = flux_job_event_watch (h, (flux_jobid_t)jobid, "eventlog", 0))) {
        shell_log_error ("Error creating event_watch future");
        return -1;
    }
    if ((rc = read_future (fut, buf, sizeof (buf))) < 0)
        shell_log_error ("Error reading ports from eventlog");
    flux_future_destroy (fut);

    /* read_future() returns 1 if port distribution event was found:
     */
    if (rc == 1
        && flux_shell_setenvf (shell, 1, "PMI_CONTROL_PORT", "%s", buf) < 0) {
        return -1;
    }
    return rc;
}

/*
 * Set job-wide environment variables for LibPALS
 */
static int set_environment (flux_shell_t *shell,
                            const char *apinfo_path,
                            int shell_size)
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
    return 0;
}

/*
 * Create the LibPALS apinfo file in the job's tempdir and set
 * the LibPALS environment.
 */
static int libpals_init (flux_plugin_t *p,
                         const char *topic,
                         flux_plugin_arg_t *args,
                         void *data)
{
    const char *tmpdir;
    char apinfo_path[1024];
    flux_shell_t *shell = flux_plugin_get_shell (p);
    int shell_size;

    if (!(tmpdir = flux_shell_getenv (shell, "FLUX_JOB_TMPDIR"))
        || snprintf (apinfo_path,
                     sizeof (apinfo_path),
                     "%s/%s",
                     tmpdir,
                     "libpals_apinfo")
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

    if (!shell || !(task = flux_shell_current_task (shell))
        || !(cmd = flux_shell_task_cmd (task))
        || flux_shell_task_info_unpack (task, "{s:i}", "rank", &task_rank) < 0
        || flux_cmd_setenvf (cmd, 1, "PALS_RANKID", "%d", task_rank) < 0) {
        return -1;
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
        return 0; // plugin disabled

    shell_debug ("enabled");

    if (flux_plugin_add_handler (p, "shell.init", libpals_init, NULL) < 0
        || flux_plugin_add_handler (p,
                                    "task.init",
                                    libpals_task_init,
                                     NULL) < 0)
        return -1;

    return 0;
}
