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
#include "src/common/libapinfo/apinfo.h"

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

static const int default_apinfo_version = 5;

static int apinfo_version = default_apinfo_version;

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
    int shell_size, ntasks, cores_per_task;
    json_t *nodelist_array;
    const struct taskmap *map;
    struct hostlist *hlist = NULL;
    struct apinfo *ap = NULL;
    flux_error_t error;

    if (flux_shell_info_unpack (shell,
                                "{s:i s:i s:{s:{s:o}}}",
                                "size",
                                &shell_size,
                                "ntasks",
                                &ntasks,
                                "R",
                                "execution",
                                "nodelist",
                                &nodelist_array)
        < 0) {
        shell_log_error ("Error unpacking shell info");
        goto error;
    }
    if (!(map = flux_shell_get_taskmap (shell))) {
        shell_log_error ("Error getting shell taskmap");
        goto error;
    }
    if ((cores_per_task = get_cores_per_task (shell, ntasks)) < 0)
        goto error;
    if (!(hlist = hostlist_from_array (nodelist_array))) {
        shell_log_error ("Error creating hostlist from nodelist array");
        goto error;
    }
    if (!(ap = apinfo_create (apinfo_version)) || apinfo_set_hostlist (ap, hlist) < 0
        || apinfo_set_taskmap (ap, map, cores_per_task)) {
        shell_log_error ("Error creating apinfo v%d object", apinfo_version);
        goto error;
    }
    if (apinfo_check (ap, &error) < 0) {
        shell_log_error ("apinfo check failed: %s", error.text);
        goto error;
    }
    if (apinfo_put (ap, apinfo_path)) {
        shell_log_error ("Error writing apinfo object");
        goto error;
    }
    shell_trace ("created pals apinfo v%d file %s", apinfo_version, apinfo_path);
    apinfo_destroy (ap);
    hostlist_destroy (hlist);
    return shell_size;
error:
    apinfo_destroy (ap);
    hostlist_destroy (hlist);
    return -1;
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

    shell_debug ("enabled (version %s)", PACKAGE_VERSION);

    // If -o cray-pals.no-edit-env is was specified set a flag for later
    no_edit_env = 0;
    (void)flux_shell_getopt_unpack (shell, "cray-pals", "{s?i}", "no-edit-env", &no_edit_env);

    // If -o cray-pals.apinfo-version=N, use that version
    apinfo_version = default_apinfo_version;
    (void)flux_shell_getopt_unpack (shell, "cray-pals", "{s?i}", "apinfo-version", &apinfo_version);

    if (flux_plugin_add_handler (p, "shell.init", libpals_init, NULL) < 0
        || flux_plugin_add_handler (p, "task.init", libpals_task_init, NULL) < 0)
        return -1;

    return 0;
}

// vi:ts=4 sw=4 expandtab
