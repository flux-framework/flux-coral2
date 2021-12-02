/************************************************************\
 * Copyright 2021 Lawrence Livermore National Security, LLC
 * (c.f. AUTHORS, NOTICE.LLNS, COPYING)
 *
 * This file is part of the Flux resource manager framework.
 * For details, see https://github.com/flux-framework.
 *
 * SPDX-License-Identifier: LGPL-3.0
\************************************************************/

/* dws-jobtap.c - keep jobs in depend state if they contain a dws attribute,
 *  send an RPC for creation/validation, and wait for a response to release
 */

#if HAVE_CONFIG_H
#include "config.h"
#endif

#include <stdio.h>
#include <jansson.h>

#include <flux/core.h>
#include <flux/jobtap.h>

#define CREATE_DEP_NAME "dws-create"
#define SETUP_PROLOG_NAME "dws-setup"

struct create_arg_t {
    flux_plugin_t *p;
    flux_jobid_t id;
};

static void create_cb (flux_future_t *f, void *arg)
{
    int success = false;
    char *errstr = NULL;
    flux_t *h = flux_future_get_flux(f);
    char jobid_buf[64];
    struct create_arg_t *args = flux_future_aux_get (f, "flux::create_args");
    json_t *resources = NULL;

    if (args == NULL) {
        flux_log_error (h, "create args missing in future aux");
        goto done;
    }

    if (flux_job_id_encode (args->id, "f58", jobid_buf, 64) < 0) {
        flux_log_error (h, "Failed to encode id in f58");
        goto done;
    }

    if (flux_rpc_get_unpack (f,
                             "{s:b, s?s, s?o}",
                             "success", &success,
                             "errstr", &errstr,
                             "resources", &resources) < 0)
    {
        flux_log_error (h, "Failed to unpack dws.create RPC for job %s", jobid_buf);
        goto done;
    }

    if (success && resources) {
        if (flux_jobtap_dependency_remove (args->p, args->id, CREATE_DEP_NAME) < 0) {
            flux_log_error (h,
                            "Failed to remove dependency %s for job %s",
                            CREATE_DEP_NAME,
                            jobid_buf);
        }
    } else {
        flux_log_error (h, "Failed to create DWS workflow object for job %s", jobid_buf);

        char *reason;
        flux_future_t *exception_f;
        if (asprintf (&reason, "DWS workflow object creation failed: %s", errstr) < 0)
            goto done;
        exception_f = flux_job_raise (h, args->id, "dw-create", 0, reason);
        // N.B.: we don't block to check the status of this exception raising as
        // that would cause a deadlock in the job-manager
        flux_future_destroy (exception_f);
        free (reason);
    }

done:
    flux_future_destroy (f);
}

static int depend_cb (flux_plugin_t *p,
                      const char *topic,
                      flux_plugin_arg_t *args,
                      void *arg)
{
    flux_jobid_t id;
    char *dw = NULL;
    flux_t *h = flux_jobtap_get_flux (p);
    int rc = 0;
    json_t *resources;

    if (flux_plugin_arg_unpack (args,
                                FLUX_PLUGIN_ARG_IN,
                                "{s:I s:{s:{s:{s?s}}} s:{s:o}}",
                                "id", &id,
                                "jobspec",
                                "attributes",
                                "system",
                                "dw", &dw,
                                "jobspec", "resources", &resources) < 0)
        return -1;
    if (dw) {
        if (flux_jobtap_dependency_add (p, id, CREATE_DEP_NAME) < 0) {
            flux_log_error (h, "Failed to add jobtap dependency for dws");
            rc = -1;
            goto ret;
        }

        flux_future_t *create_fut = flux_rpc_pack (
            h, "dws.create", FLUX_NODEID_ANY, 0, "{s:s, s:i, s:O}", "dw_string", dw, "jobid", id, "resources", resources
        );
        if (create_fut == NULL) {
            flux_log_error (h, "Failed to send dws.create RPC");
            rc = -1;
            goto ret;
        }

        struct create_arg_t *create_args = calloc (sizeof (struct create_arg_t), 1);
        if (create_args == NULL) {
            rc = -1;
            goto ret;
        }
        create_args->p = p;
        create_args->id = id;
        if (flux_future_aux_set (create_fut, "flux::create_args", create_args, free) < 0) {
            flux_future_destroy (create_fut);
            rc = -1;
            goto ret;
        }

        if (flux_future_then (create_fut, -1, create_cb, NULL) < 0) {
            flux_future_destroy (create_fut);
            rc = -1;
            goto ret;
        }
    }

ret:
    return rc;

}


static void setup_cb (flux_future_t *f, void *arg)
{
    int success = false;
    //char *errstr = NULL;
    flux_t *h = flux_future_get_flux(f);
    char jobid_buf[64];
    struct create_arg_t *args = flux_future_aux_get (f, "flux::setup_args");

    if (args == NULL) {
        flux_log_error (h, "create args missing in future aux");
        goto done;
    }

    if (flux_job_id_encode (args->id, "f58", jobid_buf, 64) < 0) {
        flux_log_error (h, "Failed to encode id in f58");
        goto done;
    }

    if (flux_rpc_get_unpack (f,
                             "{s:b}",
                             "success", &success) < 0)
    {
        flux_log_error (h, "Failed to unpack dws.setup RPC for job %s", jobid_buf);
        goto done;
    }

    if (flux_jobtap_prolog_finish (args->p, args->id, SETUP_PROLOG_NAME, !success) < 0) {
            flux_log_error (h,
                            "Failed to finish prolog %s for job %s",
                            SETUP_PROLOG_NAME,
                            jobid_buf);
        }

    if (success) {

    } else {
        flux_log_error (h, "Failed to setup DWS workflow object for job %s", jobid_buf);

        char *reason;
        flux_future_t *exception_f;
        if (asprintf (&reason, "DWS workflow setup failed: %s", "unknown error") < 0)
            goto done;
        exception_f = flux_job_raise (h, args->id, SETUP_PROLOG_NAME, 0, reason);
        // N.B.: we don't block to check the status of this exception raising as
        // that would cause a deadlock in the job-manager
        flux_future_destroy (exception_f);
        free (reason);
    }

done:
    flux_future_destroy (f);

}


static int run_cb (flux_plugin_t *p,
                      const char *topic,
                      flux_plugin_arg_t *args,
                      void *arg)
{
    flux_jobid_t id;
    char *dw = NULL;
    flux_t *h = flux_jobtap_get_flux (p);
    flux_future_t *setup_fut;

    if (flux_plugin_arg_unpack (args,
                                FLUX_PLUGIN_ARG_IN,
                                "{s:I s:{s:{s:{s?s}}}}",
                                "id", &id,
                                "jobspec",
                                "attributes",
                                "system",
                                "dw", &dw) < 0)
        return -1;
    if (dw) {
        if (flux_jobtap_prolog_start (p, SETUP_PROLOG_NAME) < 0) {
            flux_log_error (h, "Failed to start jobtap prolog for dws");
            return -1;
        }

        setup_fut = flux_rpc_pack (
            h, "dws.setup", FLUX_NODEID_ANY, 0, "{s:i}", "jobid", id
        );
        if (setup_fut == NULL) {
            flux_log_error (h, "Failed to send dws.create RPC");
            return -1;
        }
        struct create_arg_t *create_args = calloc (sizeof (struct create_arg_t), 1);
        if (create_args == NULL) {
            return -1;
        }
        create_args->p = p;
        create_args->id = id;
        if (flux_future_aux_set (setup_fut, "flux::setup_args", create_args, free) < 0) {
            flux_future_destroy (setup_fut);
            return -1;
        }
        if (flux_future_then (setup_fut, -1, setup_cb, NULL) < 0) {
            flux_future_destroy (setup_fut);
            return -1;
        }
    }
    return 0;
}

static const struct flux_plugin_handler tab[] = {
    { "job.state.depend", depend_cb, NULL },
    { "job.state.run", run_cb, NULL },
    { 0 },
};

int flux_plugin_init (flux_plugin_t *p)
{
    if (flux_plugin_register (p, "dws-test", tab) < 0)
        return -1;
    return 0;
}
