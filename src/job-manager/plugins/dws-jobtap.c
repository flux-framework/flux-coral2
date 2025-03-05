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

#include <errno.h>
#include <stdio.h>
#include <syslog.h>
#include <stdint.h>
#include <inttypes.h>
#include <jansson.h>

#include <flux/core.h>
#include <flux/jobtap.h>

#define PLUGIN_NAME "dws"
#define CREATE_DEP_NAME "dws-create"
#define SETUP_PROLOG_NAME "dws-setup"
#define DWS_EPILOG_NAME "dws-epilog"

struct create_arg_t {
    flux_plugin_t *p;
    flux_jobid_t id;
};

/*  Convenience function to convert a flux_jobid_t to F58 encoding
 *  If the encode fails (unlikely), then the decimal encoding is returned.
 */
static inline const char *idf58 (flux_jobid_t id)
{
    static __thread char buf[21];
    if (flux_job_id_encode (id, "f58", buf, sizeof (buf)) < 0) {
        /* 64bit integer is guaranteed to fit in 21 bytes
         * floor(log(2^64-1)/log(1)) + 1 = 20
         */
        (void)sprintf (buf, "%ju", (uintmax_t)id);
    }
    return buf;
}

static inline int current_job_exception (flux_plugin_t *p, const char *reason)
{
    return flux_jobtap_raise_exception (p, FLUX_JOBTAP_CURRENT_JOB, PLUGIN_NAME, 0, reason);
}

static inline int raise_job_exception (flux_plugin_t *p,
                                       flux_jobid_t id,
                                       const char *exception,
                                       const char *errstr)
{
    if (!errstr) {
        errstr = "<no error string provided>";
    }
    return flux_jobtap_raise_exception (p,
                                        id,
                                        exception,
                                        0,
                                        "DWS workflow interactions failed: %s",
                                        errstr);
}

static int dws_prolog_finish (flux_t *h,
                              flux_plugin_t *p,
                              flux_jobid_t id,
                              int success,
                              const char *errstr,
                              int *prolog_active)
{
    if (*prolog_active) {
        if (!success) {
            flux_log (h, LOG_ERR, "Failed to setup DWS workflow object for job %s", idf58 (id));
            // we don't finish the prolog here, we let the exception handler do it
            return raise_job_exception (p, id, SETUP_PROLOG_NAME, errstr);
        }
        if (flux_jobtap_prolog_finish (p, id, SETUP_PROLOG_NAME, !success) < 0) {
            flux_log_error (h,
                            "Failed to finish prolog %s for job %s with errstr '%s'",
                            SETUP_PROLOG_NAME,
                            idf58 (id),
                            errstr);
            return -1;
        }
        *prolog_active = 0;
    }
    return 0;
}

static int dws_epilog_finish (flux_t *h,
                              flux_plugin_t *p,
                              flux_jobid_t id,
                              int success,
                              const char *errstr)
{
    int ret = 0;
    if (!success) {
        flux_log (h, LOG_ERR, "Failed to clean up DWS workflow object for job %s", idf58 (id));
        ret = raise_job_exception (p, id, DWS_EPILOG_NAME, errstr);
    }
    if (flux_jobtap_epilog_finish (p, id, DWS_EPILOG_NAME, !success) < 0) {
        flux_log_error (h,
                        "Failed to finish epilog %s for job %s with errstr '%s'",
                        DWS_EPILOG_NAME,
                        idf58 (id),
                        errstr);
        return -1;
    }
    return ret;
}

static void create_cb (flux_future_t *f, void *arg)
{
    int success = false;
    const char *errstr = NULL;
    flux_t *h = flux_future_get_flux (f);
    struct create_arg_t *args = flux_future_aux_get (f, "flux::create_args");

    if (args == NULL) {
        flux_log_error (h, "create args missing in future aux");
        return;
    }

    if (flux_rpc_get_unpack (f, "{s:b, s?s}", "success", &success, "errstr", &errstr) < 0) {
        errstr = "Failed to unpack dws.create RPC";
        if (errno == ENOSYS) {
            errstr =
                "dws.create RPC could not be sent. "
                "Admins: is the flux-coral2-dws service loaded?";
        }
        raise_job_exception (args->p, args->id, CREATE_DEP_NAME, errstr);
        return;
    }

    if (!success) {
        if (errstr) {
            raise_job_exception (args->p, args->id, CREATE_DEP_NAME, errstr);
        } else {
            raise_job_exception (args->p,
                                 args->id,
                                 CREATE_DEP_NAME,
                                 "dws.create RPC returned failure");
        }
    }
}

static int depend_cb (flux_plugin_t *p, const char *topic, flux_plugin_arg_t *args, void *arg)
{
    flux_jobid_t id;
    json_t *dw = NULL;
    flux_t *h = flux_jobtap_get_flux (p);
    json_t *resources;
    json_t *jobspec;
    int userid;
    struct create_arg_t *create_args;

    if (flux_plugin_arg_unpack (args,
                                FLUX_PLUGIN_ARG_IN,
                                "{s:I s:{s:{s:{s?o}}} s:{s:o} s:i s:o}",
                                "id",
                                &id,
                                "jobspec",
                                "attributes",
                                "system",
                                "dw",
                                &dw,
                                "jobspec",
                                "resources",
                                &resources,
                                "userid",
                                &userid,
                                "jobspec",
                                &jobspec)
        < 0) {
        current_job_exception (p, "jobtap plugin failed to unpack args");
        return -1;
    }
    if (dw) {
        if (flux_jobtap_dependency_add (p, id, CREATE_DEP_NAME) < 0) {
            flux_log_error (h, "Failed to add dws jobtap dependency for %s", idf58 (id));
            current_job_exception (p, "Failed to add dws jobtap dependency");
            return -1;
        }
        // subscribe to exception events
        if (flux_jobtap_job_subscribe (p, FLUX_JOBTAP_CURRENT_JOB) < 0) {
            current_job_exception (p, "dws-jobtap: error initializing exception-monitoring");
            flux_log_error (h,
                            "dws-jobtap: error initializing exception-monitoring for %s",
                            idf58 (id));
            return -1;
        }
        flux_future_t *create_fut = flux_rpc_pack (h,
                                                   "dws.create",
                                                   FLUX_NODEID_ANY,
                                                   0,
                                                   "{s:O, s:I, s:O, s:i}",
                                                   "dw_directives",
                                                   dw,
                                                   "jobid",
                                                   id,
                                                   "resources",
                                                   resources,
                                                   "userid",
                                                   userid);
        if (create_fut == NULL) {
            flux_log_error (h, "Failed to send dws.create RPC for %s", idf58 (id));
            current_job_exception (p, "Failed to send dws.create RPC");
            return -1;
        }
        if (!(create_args = calloc (1, sizeof (struct create_arg_t)))) {
            current_job_exception (p, "Failed to allocate memory");
            return -1;
        }
        create_args->p = p;
        create_args->id = id;
        if (flux_future_aux_set (create_fut, "flux::create_args", create_args, free) < 0
            || flux_future_then (create_fut, -1, create_cb, NULL) < 0
            || flux_jobtap_job_aux_set (p,
                                        FLUX_JOBTAP_CURRENT_JOB,
                                        NULL,
                                        create_fut,
                                        (flux_free_f)flux_future_destroy)
                   < 0) {
            flux_future_destroy (create_fut);
            current_job_exception (p, "Failed to set aux on future");
            return -1;
        }
    }
    return 0;
}

static void setup_rpc_cb (flux_future_t *f, void *arg)
{
    int success = false;
    const char *errstr = NULL;
    flux_t *h = flux_future_get_flux (f);
    struct create_arg_t *args = flux_future_aux_get (f, "flux::setup_args");
    int *prolog_active = flux_future_aux_get (f, "flux::prolog_active");

    if (args == NULL || prolog_active == NULL) {
        flux_log_error (h, "create args missing in future aux");
        return;
    }

    if (flux_rpc_get_unpack (f, "{s:b, s?s}", "success", &success, "errstr", &errstr) < 0) {
        dws_prolog_finish (h,
                           args->p,
                           args->id,
                           0,
                           "Failed to unpack dws.setup RPC",
                           prolog_active);
        return;
    }
    if (!success) {
        if (errstr) {
            dws_prolog_finish (h, args->p, args->id, 0, errstr, prolog_active);
        } else {
            dws_prolog_finish (h,
                               args->p,
                               args->id,
                               0,
                               "dws.setup RPC returned failure",
                               prolog_active);
        }
    }
}

static void fetch_R_callback (flux_future_t *f, void *arg)
{
    json_t *R;
    flux_t *h = flux_future_get_flux (f);
    struct create_arg_t *args = flux_future_aux_get (f, "flux::fetch_R");
    struct create_arg_t *create_args;
    int *prolog_active = flux_future_aux_get (f, "flux::prolog_active");
    flux_future_t *setup_rpc_fut;

    if (args == NULL || prolog_active == NULL) {
        flux_log_error (h, "fetch_R_callback: auxes missing");
        goto done;
    }

    if (flux_kvs_lookup_get_unpack (f, "o", &R) < 0) {
        dws_prolog_finish (h, args->p, args->id, 0, "Failed to unpack R", prolog_active);
        goto done;
    }

    create_args = calloc (1, sizeof (struct create_arg_t));
    if (create_args == NULL) {
        dws_prolog_finish (h, args->p, args->id, 0, "Failed to create aux struct", prolog_active);
        goto done;
    }
    create_args->p = args->p;
    create_args->id = args->id;
    if (!(setup_rpc_fut = flux_rpc_pack (h,
                                         "dws.setup",
                                         FLUX_NODEID_ANY,
                                         0,
                                         "{s:I, s:O}",
                                         "jobid",
                                         args->id,
                                         "R",
                                         R))
        || flux_future_aux_set (setup_rpc_fut, "flux::setup_args", create_args, free) < 0
        || flux_future_aux_set (setup_rpc_fut, "flux::prolog_active", prolog_active, NULL) < 0
        || flux_future_then (setup_rpc_fut, -1, setup_rpc_cb, NULL) < 0
        || flux_jobtap_job_aux_set (args->p,
                                    args->id,
                                    NULL,
                                    setup_rpc_fut,
                                    (flux_free_f)flux_future_destroy)
               < 0) {
        flux_future_destroy (setup_rpc_fut);
        dws_prolog_finish (h, args->p, args->id, 0, "Failed to send dws.setup RPC", prolog_active);
        goto done;
    }

done:
    flux_future_destroy (f);
}

static int run_cb (flux_plugin_t *p, const char *topic, flux_plugin_arg_t *args, void *arg)
{
    flux_jobid_t id;
    json_t *dw = NULL;
    char buf[1024];
    flux_t *h = flux_jobtap_get_flux (p);
    flux_future_t *fetch_R_future = NULL;
    int *prolog_active;

    if (flux_plugin_arg_unpack (args,
                                FLUX_PLUGIN_ARG_IN,
                                "{s:I s:{s:{s:{s?o}}}}",
                                "id",
                                &id,
                                "jobspec",
                                "attributes",
                                "system",
                                "dw",
                                &dw)
        < 0) {
        current_job_exception (p, "jobtap plugin failed to unpack args");
        return -1;
    }
    if (dw) {
        // set a boolean aux indicating whether jobtap prolog is active, so it can
        // be finished if an exception occurs
        if (!(prolog_active = malloc (sizeof (int)))
            || flux_jobtap_job_aux_set (p,
                                        FLUX_JOBTAP_CURRENT_JOB,
                                        "dws_prolog_active",
                                        prolog_active,
                                        free)
                   < 0) {
            free (prolog_active);
            flux_log_error (h, "dws-jobtap: error creating prolog_active aux for %s", idf58 (id));
            current_job_exception (p, "error creating prolog_active aux");
            return -1;
        }
        *prolog_active = 1;
        if (flux_jobtap_prolog_start (p, SETUP_PROLOG_NAME) < 0) {
            flux_log_error (h, "Failed to start dws jobtap prolog for %s", idf58 (id));
            current_job_exception (p, "Failed to start dws jobtap prolog");
            return -1;
        }
        struct create_arg_t *create_args = calloc (1, sizeof (struct create_arg_t));
        if (create_args == NULL) {
            dws_prolog_finish (h, p, id, 0, "OOM", prolog_active);
            return -1;
        }
        create_args->p = p;
        create_args->id = id;
        if (flux_job_kvs_key (buf, sizeof (buf), id, "R") < 0
            || !(fetch_R_future = flux_kvs_lookup (h, NULL, 0, buf))
            || flux_future_aux_set (fetch_R_future, "flux::fetch_R", create_args, free) < 0
            || flux_future_aux_set (fetch_R_future, "flux::prolog_active", prolog_active, NULL) < 0
            || flux_future_then (fetch_R_future, -1., fetch_R_callback, NULL) < 0) {
            flux_future_destroy (fetch_R_future);
            flux_log_error (h,
                            "dws-jobtap: "
                            "Error creating future to send R to coral2_dws.py for %s",
                            idf58 (id));
            dws_prolog_finish (h, p, id, 0, "", prolog_active);
            return -1;
        }
    }
    return 0;
}

static void post_run_rpc_callback (flux_future_t *f, void *arg)
{
    flux_t *h = flux_future_get_flux (f);
    struct create_arg_t *args;
    int success = false;
    const char *errstr = NULL;

    if (!(args = flux_future_aux_get (f, "flux::create_args"))) {
        flux_log_error (h, "create args missing in future aux");
        return;
    }

    if (flux_rpc_get_unpack (f, "{s:b, s?s}", "success", &success, "errstr", &errstr) < 0) {
        dws_epilog_finish (h, args->p, args->id, 0, "Failed to send dws.post_run RPC");
        return;
    }
    if (!success) {
        dws_epilog_finish (h, args->p, args->id, 0, errstr);
    }
}

static int cleanup_cb (flux_plugin_t *p, const char *topic, flux_plugin_arg_t *args, void *arg)
{
    flux_jobid_t id;
    json_t *dw = NULL;
    flux_future_t *post_run_fut;
    flux_t *h = flux_jobtap_get_flux (p);
    int dws_run_started = 0;
    struct create_arg_t *create_args;

    if (flux_plugin_arg_unpack (args,
                                FLUX_PLUGIN_ARG_IN,
                                "{s:I s:{s:{s:{s?o}}}}",
                                "id",
                                &id,
                                "jobspec",
                                "attributes",
                                "system",
                                "dw",
                                &dw)
        < 0) {
        current_job_exception (p, "Failed to unpack args");
        return -1;
    }
    // check that the job has a DW attr section
    if (dw) {
        if (!(create_args = calloc (1, sizeof (struct create_arg_t)))) {
            flux_log_error (h, "error allocating arg struct for %s", idf58 (id));
            current_job_exception (p, "error allocating arg struct");
            return -1;
        }
        create_args->p = p;
        create_args->id = id;

        if (flux_jobtap_job_aux_get (p, FLUX_JOBTAP_CURRENT_JOB, "flux::dws_run_started")) {
            dws_run_started = 1;
        }
        if (flux_jobtap_job_aux_set (p, id, "dws_epilog_active", (void *)1, NULL) < 0
            || flux_jobtap_epilog_start (p, DWS_EPILOG_NAME) < 0) {
            flux_log_error (h, "Failed to start jobtap epilog for %s", idf58 (id));
            current_job_exception (p, "Failed to start jobtap epilog");
            return -1;
        }
        if (!(post_run_fut = flux_rpc_pack (h,
                                            "dws.post_run",
                                            FLUX_NODEID_ANY,
                                            0,
                                            "{s:I, s:b}",
                                            "jobid",
                                            id,
                                            "run_started",
                                            dws_run_started))
            || flux_future_aux_set (post_run_fut, "flux::create_args", create_args, free) < 0
            || flux_future_then (post_run_fut, -1., post_run_rpc_callback, NULL) < 0
            || flux_jobtap_job_aux_set (p,
                                        FLUX_JOBTAP_CURRENT_JOB,
                                        NULL,
                                        post_run_fut,
                                        (flux_free_f)flux_future_destroy)
                   < 0) {
            flux_future_destroy (post_run_fut);
            dws_epilog_finish (h, p, id, 0, "Failed to send dws.post_run RPC");
            flux_log_error (h, "Failed to send dws.post_run RPC for %s", idf58 (id));
            return -1;
        }
    }
    return 0;
}

/*
 * In the event of a severity-0 exception, check if the prolog is running,
 * and remove it if so.
 */
static int exception_cb (flux_plugin_t *p, const char *topic, flux_plugin_arg_t *args, void *arg)
{
    flux_jobid_t id;
    flux_t *h = flux_jobtap_get_flux (p);
    int *prolog_active, severity;
    flux_future_t *teardown_fut;

    if (flux_plugin_arg_unpack (args,
                                FLUX_PLUGIN_ARG_IN,
                                "{s:I s:{s:{s:i}}}",
                                "id",
                                &id,
                                "entry",
                                "context",
                                "severity",
                                &severity)
        < 0) {
        flux_log_error (h, "Failed to unpack args");
        return -1;
    }
    if (severity != 0) {
        return 0;  // Do nothing for severity > 0 exceptions
    }
    if ((prolog_active = flux_jobtap_job_aux_get (p, FLUX_JOBTAP_CURRENT_JOB, "dws_prolog_active"))
        && (*prolog_active)) {
        if (flux_jobtap_prolog_finish (p, id, SETUP_PROLOG_NAME, 1) < 0) {
            flux_log_error (h,
                            "Failed to finish prolog %s for job %s after exception",
                            SETUP_PROLOG_NAME,
                            idf58 (id));
            return -1;
        }
        *prolog_active = 0;
    } else if (flux_jobtap_job_aux_get (p, FLUX_JOBTAP_CURRENT_JOB, "dws_epilog_active") > 0) {
        if (!(teardown_fut =
                  flux_rpc_pack (h, "dws.teardown", FLUX_NODEID_ANY, 0, "{s:I}", "jobid", id))) {
            flux_log_error (h, "Failed to send dws.teardown RPC for job %s", idf58 (id));
            return -1;
        }
        flux_future_destroy (teardown_fut);
    }
    return 0;
}

/*
 * Generate a new jobspec constraints object for a job so that it can avoid
 * attempting to run on nodes attached to down rabbits.
 */
static json_t *generate_constraints (flux_t *h,
                                     flux_plugin_t *p,
                                     flux_jobid_t jobid,
                                     const char *exclude_str)
{
    flux_plugin_arg_t *args = flux_jobtap_job_lookup (p, jobid);
    json_t *constraints = NULL;
    json_t * not ;
    if (!args
        || flux_plugin_arg_unpack (args,
                                   FLUX_PLUGIN_ARG_IN,
                                   "{s:{s:{s:{s?o}}}}",
                                   "jobspec",
                                   "attributes",
                                   "system",
                                   "constraints",
                                   &constraints)
               < 0) {
        flux_log_error (h, "Failed to unpack args");
        flux_plugin_arg_destroy (args);
        return NULL;
    }
    if (!constraints) {
        if (!(constraints = json_pack ("{s:[{s:[s]}]}", "not", "properties", exclude_str))) {
            flux_log_error (h, "Failed to create new constraints object for %s", idf58 (jobid));
            flux_plugin_arg_destroy (args);
            return NULL;
        }
        flux_plugin_arg_destroy (args);
        return constraints;
    } else {  // deep copy the constraints because we don't want to modify it in-place
        if (!(constraints = json_deep_copy (constraints))) {
            flux_log_error (h, "Failed to deep copy constraints object for %s", idf58 (jobid));
            flux_plugin_arg_destroy (args);
            return NULL;
        }
    }
    flux_plugin_arg_destroy (args);
    if (!(not = json_object_get (constraints, "not"))) {
        if (json_object_set_new (constraints,
                                 "not",
                                 json_pack ("[{s:[s]}]", "properties", exclude_str))
            < 0) {
            flux_log_error (h, "Failed to create new NOT constraints object for %s", idf58 (jobid));
            json_decref (constraints);
            return NULL;
        }
        return constraints;
    }
    if (json_array_append_new (not, json_pack ("{s:[s]}", "properties", exclude_str)) < 0) {
        flux_log_error (h, "Failed to create new NOT constraints object for %s", idf58 (jobid));
        json_decref (constraints);
        return NULL;
    }
    return constraints;
}

static void resource_update_msg_cb (flux_t *h,
                                    flux_msg_handler_t *mh,
                                    const flux_msg_t *msg,
                                    void *arg)
{
    flux_plugin_t *p = (flux_plugin_t *)arg;
    json_int_t jobid;
    json_t *resources = NULL, *errmsg, *constraints = NULL;
    int copy_offload;
    const char *errmsg_str, *exclude_str;

    if (flux_msg_unpack (msg,
                         "{s:I, s:o, s:b, s:o, s:s}",
                         "id",
                         &jobid,
                         "resources",
                         &resources,
                         "copy-offload",
                         &copy_offload,
                         "errmsg",
                         &errmsg,
                         "exclude",
                         &exclude_str)
        < 0) {
        flux_log_error (h, "received malformed dws.resource-update RPC");
        return;
    }
    if (strlen (exclude_str) > 0) {
        if (!(constraints = generate_constraints (h, p, jobid, exclude_str))) {
            flux_log_error (h, "Could not generate exclusion constraint for %s", idf58 (jobid));
            raise_job_exception (p, jobid, PLUGIN_NAME, "Could not generate exclusion constraint");
            return;
        }
    }
    if (!json_is_null (errmsg)) {
        if (!(errmsg_str = json_string_value (errmsg))) {
            flux_log_error (h,
                            "received malformed dws.resource-update RPC, errmsg must be string or "
                            "JSON null: %s",
                            idf58 (jobid));
            errmsg_str = "<could not fetch error message>";
        }
        raise_job_exception (p, jobid, PLUGIN_NAME, errmsg_str);
        json_decref (constraints);
        return;
    } else if (flux_jobtap_job_aux_set (p,
                                        jobid,
                                        "flux::dws-copy-offload",
                                        copy_offload ? (void *)1 : (void *)0,
                                        NULL)
                   < 0
               || flux_jobtap_jobspec_update_id_pack (p,
                                                      (flux_jobid_t)jobid,
                                                      "{s:O, s:o*}",
                                                      "resources",
                                                      resources,
                                                      "attributes.system.constraints",
                                                      constraints)
                      < 0) {
        flux_log_error (h,
                        "could not update jobspec for %s with new constraints and resources",
                        idf58 (jobid));
        raise_job_exception (p, jobid, PLUGIN_NAME, "Internal error: failed to update jobspec");
        json_decref (constraints);
        return;
    }
    if (flux_jobtap_dependency_remove (p, jobid, CREATE_DEP_NAME) < 0) {
        raise_job_exception (p, jobid, CREATE_DEP_NAME, "Failed to remove dependency for job");
        return;
    }
}

/*
 * Upon receipt of dws.prolog-remove RPC, remove the
 * dws prolog for a job.
 */
static void prolog_remove_msg_cb (flux_t *h,
                                  flux_msg_handler_t *mh,
                                  const flux_msg_t *msg,
                                  void *arg)
{
    flux_plugin_t *p = (flux_plugin_t *)arg;
    json_int_t jobid;
    json_t *env = NULL;
    int *prolog_active, junk_prolog_active = 1;
    int copy_offload = 0;

    if (flux_msg_unpack (msg, "{s:I, s:o}", "id", &jobid, "variables", &env) < 0) {
        flux_log_error (h, "received malformed dws.prolog-remove RPC");
        return;
    }
    if (flux_jobtap_job_aux_get (p, (flux_jobid_t)jobid, "flux::dws-copy-offload")) {
        copy_offload = 1;
    }
    if (!(prolog_active = flux_jobtap_job_aux_get (p, (flux_jobid_t)jobid, "dws_prolog_active"))) {
        // if we can't fetch the aux, proceed as normal.
        // the aux is only in place to ensure the prolog is removed when
        // an exception occurs
        prolog_active = &junk_prolog_active;  // at least it's a valid address
        flux_log_error (h, "failed to fetch 'dws_prolog_active' aux for %s", idf58 (jobid));
    }
    if (flux_jobtap_event_post_pack (p,
                                     jobid,
                                     "dws_environment",
                                     "{s:O, s:b}",
                                     "variables",
                                     env,
                                     "copy_offload",
                                     copy_offload)
            < 0
        || flux_jobtap_job_aux_set (p, jobid, "flux::dws_run_started", (void *)1, NULL) < 0) {
        dws_prolog_finish (h, p, jobid, 0, "failed to post dws_environment event", prolog_active);
    } else {
        dws_prolog_finish (h, p, jobid, 1, "success!", prolog_active);
    }
}

/*
 * Upon receipt of dws.epilog-remove RPC, remove the
 * dws epilog for a job.
 */
static void epilog_remove_msg_cb (flux_t *h,
                                  flux_msg_handler_t *mh,
                                  const flux_msg_t *msg,
                                  void *arg)
{
    flux_plugin_t *p = (flux_plugin_t *)arg;
    json_int_t jobid;

    if (flux_msg_unpack (msg, "{s:I}", "id", &jobid) < 0) {
        flux_log_error (h, "received malformed dws.epilog-remove RPC");
        return;
    }
    dws_epilog_finish (h, p, jobid, 1, "success!");
}

static const struct flux_plugin_handler tab[] = {
    {"job.state.depend", depend_cb, NULL},
    {"job.state.run", run_cb, NULL},
    {"job.state.cleanup", cleanup_cb, NULL},
    {"job.event.exception", exception_cb, NULL},
    {0},
};

int flux_plugin_init (flux_plugin_t *p)
{
    if (flux_plugin_register (p, PLUGIN_NAME, tab) < 0
        || flux_jobtap_service_register (p, "resource-update", resource_update_msg_cb, p) < 0
        || flux_jobtap_service_register (p, "prolog-remove", prolog_remove_msg_cb, p) < 0
        || flux_jobtap_service_register (p, "epilog-remove", epilog_remove_msg_cb, p) < 0) {
        return -1;
    }

    return 0;
}
