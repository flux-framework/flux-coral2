/************************************************************\
 * Copyright 2021 Lawrence Livermore National Security, LLC
 * (c.f. AUTHORS, NOTICE.LLNS, COPYING)
 *
 * This file is part of the Flux resource manager framework.
 * For details, see https://github.com/flux-framework.
 *
 * SPDX-License-Identifier: LGPL-3.0
\************************************************************/
#define FLUX_SHELL_PLUGIN_NAME "dws_environment"

#include <stdint.h>
#include <stdlib.h>
#include <unistd.h>

#include <jansson.h>

#include <flux/hostlist.h>
#include <flux/shell.h>

#include "eventlog_helpers.h"

/* DWS Environment --- set environment variables provided by DWS
 *
 * If a job requests Rabbit resources with a #DW string in its jobspec,
 * Flux will assign it some resources and DWS will prepare those resources
 * for use by the job. Before the job can execute DWS, will provide
 * Flux with some environment variables that need to be inserted into the
 * job. This shell plugin performs that insertion.
 *
 */

/*
 * Apply a JSON object defining environment variables to the job's environment
 */
static int set_environment (flux_shell_t *shell, json_t *env_object)
{
    const char *key, *value_string;
    json_t *value;

    json_object_foreach (env_object, key, value) {
        if (!(value_string = json_string_value (value))) {
            shell_log_error ("variables in dws_environment event must have string values");
            return -1;
        }
        if (flux_shell_setenvf (shell, 1, key, "%s", value_string) < 0) {
            shell_log_error ("Failed setting DWS environment variable");
            return -1;
        }
    }
    return 0;
}

/*
 * Read an eventlog future, looking for the 'dws_environment' event
 */
static int read_future (flux_shell_t *shell, flux_future_t *fut)
{
    json_t *o = NULL;
    json_t *context = NULL;
    json_t *env;
    const char *name, *event = NULL;

    while (flux_future_wait_for (fut, 30.0) == 0 && flux_job_event_watch_get (fut, &event) == 0) {
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
            //  'start' event with no dws_environment event.
            shell_log_error ("'start' event found before 'dws_environment'");
            json_decref (o);
            return -1;
        } else if (!strcmp (name, "dws_environment")) {
            if (json_unpack (context, "{s:o}", "variables", &env) < 0) {
                shell_log_error ("No 'variables' context in dws_environment event");
                json_decref (o);
                return -1;
            }
            if (set_environment (shell, env) < 0) {
                json_decref (o);
                return -1;
            }
            json_decref (o);
            return 0;
        } else {
            flux_future_reset (fut);
            json_decref (o);
        }
    }
    shell_log_error ("No 'dws_environment' event posted within timeout");
    return -1;
}

static int dws_environment_init (flux_plugin_t *p,
                                 const char *topic,
                                 flux_plugin_arg_t *args,
                                 void *data)
{
    flux_shell_t *shell = flux_plugin_get_shell (p);
    json_t *dw = NULL;
    json_int_t jobid;
    flux_t *h;
    flux_future_t *fut;

    if (!shell) {
        return -1;
    }
    if (flux_shell_info_unpack (shell,
                                "{s:I s:{s:{s:{s?o}}}}",
                                "jobid",
                                &jobid,
                                "jobspec",
                                "attributes",
                                "system",
                                "dw",
                                &dw)
        < 0)
        return -1;
    if (!dw) {
        // This plugin doesn't need to do anything, no #DW directives
        // and therefore no environment variables
        return 0;
    }
    if (!(h = flux_shell_get_flux (shell))
        || !(fut = flux_job_event_watch (h, (flux_jobid_t)jobid, "eventlog", 0))) {
        shell_log_error ("Error creating event_watch future");
        return -1;
    }
    if (read_future (shell, fut) < 0) {
        shell_log_error ("Error reading DW environment from eventlog");
        flux_job_event_watch_cancel (fut);
        flux_future_destroy (fut);
        return -1;
    }
    if ((flux_job_event_watch_cancel (fut)) < 0)
        shell_log_error ("flux_job_event_watch_cancel");
    flux_future_destroy (fut);
    return 0;
}

int flux_plugin_init (flux_plugin_t *p)
{
    if (flux_plugin_set_name (p, FLUX_SHELL_PLUGIN_NAME) < 0
        || flux_plugin_add_handler (p, "shell.init", dws_environment_init, NULL) < 0) {
        return -1;
    }
    return 0;
}
