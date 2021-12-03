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
#include <stdint.h>
#include <inttypes.h>
#include <jansson.h>

#include <flux/core.h>
#include <flux/jobtap.h>

#define CREATE_DEP_NAME "dws-create"
#define SETUP_PROLOG_NAME "dws-setup"

struct create_arg_t {
    flux_plugin_t *p;
    flux_jobid_t id;
};


static int raise_job_exception(flux_t *h, flux_jobid_t id, const char *exception, const char *errstr)
{
    char *reason;
    flux_future_t *exception_f;

    if (!errstr){
        errstr = "<no error string provided>";
    }
    flux_log_error (h, "Raising exception for job %" PRIu64 ": %s", id, errstr);
    if (asprintf (&reason, "DWS workflow interactions failed: %s", errstr) < 0)
        return -1;
    exception_f = flux_job_raise (h, id, exception, 0, reason);
    // N.B.: we don't block to check the status of this exception raising as
    // that would cause a deadlock in the job-manager
    flux_future_destroy (exception_f);
    free(reason);
    return 0;
}

static int dws_prolog_finish (flux_t *h, flux_plugin_t *p, flux_jobid_t id, int success, const char *errstr){
    if (flux_jobtap_prolog_finish (p, id, SETUP_PROLOG_NAME, !success) < 0) {
            flux_log_error (h,
                            "Failed to finish prolog %s for job %" PRIu64,
                            SETUP_PROLOG_NAME,
                            id);
            return -1;
        }
    if (!success) {
        flux_log_error (h, "Failed to setup DWS workflow object for job %" PRIu64, id);
        return raise_job_exception (h, id, SETUP_PROLOG_NAME, errstr);
    }
    return 0;
}

static void create_cb (flux_future_t *f, void *arg)
{
    int success = false;
    char *errstr = NULL;
    flux_t *h = flux_future_get_flux(f);
    struct create_arg_t *args = flux_future_aux_get (f, "flux::create_args");
    json_t *resources = NULL;

    if (args == NULL) {
        flux_log_error (h, "create args missing in future aux");
        goto done;
    }

    if (flux_rpc_get_unpack (f,
                             "{s:b, s?s, s?o}",
                             "success", &success,
                             "errstr", &errstr,
                             "resources", &resources) < 0)
    {
        raise_job_exception (h, args->id, CREATE_DEP_NAME, "Failed to unpack dws.create RPC");
        goto done;
    }

    if (success && resources) {
        if (flux_jobtap_dependency_remove (args->p, args->id, CREATE_DEP_NAME) < 0) {
            raise_job_exception (h, args->id, CREATE_DEP_NAME, "Failed to remove dependency for job");
        }
    } else {
        raise_job_exception (h, args->id, CREATE_DEP_NAME, "dws.create RPC returned failure");
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
            return -1;
        }

        flux_future_t *create_fut = flux_rpc_pack (
            h, "dws.create", FLUX_NODEID_ANY, 0, "{s:s, s:i, s:O}", "dw_string", dw, "jobid", id, "resources", resources
        );
        if (create_fut == NULL) {
            flux_log_error (h, "Failed to send dws.create RPC");
            return -1;
        }

        struct create_arg_t *create_args = calloc (sizeof (struct create_arg_t), 1);
        if (create_args == NULL) {
            return -1;
        }
        create_args->p = p;
        create_args->id = id;
        if (flux_future_aux_set (create_fut, "flux::create_args", create_args, free) < 0
            || flux_future_then (create_fut, -1, create_cb, NULL) < 0) {
            flux_future_destroy (create_fut);
            return -1;
        }
    }
    return 0;
}


static void setup_rpc_cb (flux_future_t *f, void *arg)
{
    int success = false;
    json_t *env = NULL;
    //char *errstr = NULL;
    flux_t *h = flux_future_get_flux(f);
    struct create_arg_t *args = flux_future_aux_get (f, "flux::setup_args");

    if (args == NULL) {
        flux_log_error (h, "create args missing in future aux");
        goto done;
    }

    if (flux_rpc_get_unpack (f,
                             "{s:b, s?o}",
                             "success", &success, "variables", &env) < 0)
    {
        dws_prolog_finish (h, args->p, args->id, 0, "Failed to unpack dws.setup RPC");
        goto done;
    }
    // error string below will only be printed if ``!(success && env)``
    if (success && env){
        if (flux_jobtap_event_post_pack (args->p,
                                    args->id,
                                    "dws_environment",
                                    "{s:O}",
                                    "variables",
                                    env) < 0){
            dws_prolog_finish (h, args->p, args->id, 0, "failed to send dws_environment event");
        }
        else {
            flux_log_error (h, "sent dws_environment event");
            dws_prolog_finish (h, args->p, args->id, 1, "success!");
        }
    }
    else {
        dws_prolog_finish (h, args->p, args->id, success, "dws.setup RPC returned failure");
    }

done:
    flux_future_destroy (f);

}


static void fetch_R_callback (flux_future_t *f, void *arg)
{
    json_t *R;
    flux_t *h = flux_future_get_flux(f);
    struct create_arg_t *args = flux_future_aux_get (f, "flux::fetch_R");
    struct create_arg_t *create_args;
    flux_future_t *setup_rpc_fut;

    if (args == NULL){
        flux_log_error (h, "fetch_R aux missing");
        goto done;
    }

    if (flux_kvs_lookup_get_unpack (f, "o", &R) < 0){
        dws_prolog_finish (h, args->p, args->id, 0, "Failed to unpack R");
        goto done;
    }

    create_args = calloc (sizeof (struct create_arg_t), 1);
    if (create_args == NULL) {
        dws_prolog_finish (h, args->p, args->id, 0, "Failed to create aux struct");
        goto done;
    }
    create_args->p = args->p;
    create_args->id = args->id;
    if (!(setup_rpc_fut = flux_rpc_pack (
        h, "dws.setup", FLUX_NODEID_ANY, 0, "{s:i, s:O}", "jobid", args->id, "R", R))
        || flux_future_aux_set (setup_rpc_fut, "flux::setup_args", create_args, free) < 0
        || flux_future_then (setup_rpc_fut, -1, setup_rpc_cb, NULL) < 0) {
        flux_future_destroy (setup_rpc_fut);
        dws_prolog_finish (h, args->p, args->id, 0, "Failed to send dws.setup RPC");
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
    char buf[1024];
    flux_t *h = flux_jobtap_get_flux (p);
    flux_future_t *fetch_R_future = NULL;

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
        struct create_arg_t *create_args = calloc (sizeof (struct create_arg_t), 1);
        if (create_args == NULL) {
            return -1;
        }
        create_args->p = p;
        create_args->id = id;
        if (flux_job_kvs_key (buf, sizeof (buf), id, "R") < 0
            || !(fetch_R_future = flux_kvs_lookup (h, NULL, 0, buf))
            || flux_future_aux_set (fetch_R_future, "flux::fetch_R", create_args, free) < 0
            || flux_future_then (fetch_R_future, -1., fetch_R_callback, NULL) < 0) {
            flux_future_destroy (fetch_R_future);
            flux_log_error (h,
                            "dws-jobtap: "
                            "Error creating future to send R to dws.py");
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
