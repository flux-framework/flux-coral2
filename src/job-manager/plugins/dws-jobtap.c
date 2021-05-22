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
 *  send an RPC for validation, and wait for a response to release
 */

#if HAVE_CONFIG_H
#include "config.h"
#endif

#include <stdio.h>
#include <jansson.h>

#include <flux/core.h>
#include <flux/jobtap.h>

#define VALIDATE_DEP_NAME "dws-validate"

struct validate_arg_t {
    flux_plugin_t *p;
    flux_jobid_t id;
};

static void validate_cb (flux_future_t *f, void *arg)
{
    int success = false;
    char *errstr = NULL;
    flux_t *h = flux_future_get_flux(f);
    char jobid_buf[64];
    struct validate_arg_t *args = flux_future_aux_get (f, "flux::validate_args");

    if (args == NULL) {
        flux_log_error (h, "validate args missing in future aux");
        goto done;
    }

    if (flux_job_id_encode (args->id, "f58", jobid_buf, 64) < 0) {
        flux_log_error (h, "Failed to encode id in f58");
        goto done;
    }

    if (flux_rpc_get_unpack (f,
                             "{s:b, s?s}",
                             "success", &success,
                             "errstr", &errstr) < 0)
    {
        flux_log_error (h, "Failed to unpack dws.validate RPC for job %s", jobid_buf);
        goto done;
    }

    if (success) {
        if (flux_jobtap_dependency_remove (args->p, args->id, VALIDATE_DEP_NAME) < 0) {
            flux_log_error (h,
                            "Failed to remove dependency %s for job %s",
                            VALIDATE_DEP_NAME,
                            jobid_buf);
        }
    } else {
        flux_log_error (h, "Failed to validate DW string for job %s", jobid_buf);
        
        char *reason;
        flux_future_t *exception_f;
        if (asprintf (&reason, "DW string validation failed: %s", errstr) < 0)
            goto done;
        exception_f = flux_job_raise (h, args->id, "dw-validation", 0, reason);
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
        if (flux_jobtap_dependency_add (p, id, VALIDATE_DEP_NAME) < 0) {
            flux_log_error (h, "Failed to add jobtap dependency for dws");
            rc = -1;
            goto ret;
        }

        flux_future_t *validate_fut = flux_rpc_pack (
            h, "dws.validate", FLUX_NODEID_ANY, 0, "{s:s}", "dw_string", dw
        );
        if (validate_fut == NULL) {
            flux_log_error (h, "Failed to send dws.validate RPC");
            rc = -1;
            goto ret;
        }
        
        struct validate_arg_t *validate_args = calloc (sizeof (struct validate_arg_t), 1);
        if (validate_args == NULL) {
            rc = -1;
            goto ret;
        }
        validate_args->p = p;
        validate_args->id = id;
        if (flux_future_aux_set (validate_fut, "flux::validate_args", validate_args, free) < 0) {
            flux_future_destroy (validate_fut);
            rc = -1;
            goto ret;
        }

        if (flux_future_then (validate_fut, -1, validate_cb, NULL) < 0) {
            flux_future_destroy (validate_fut);
            rc = -1;
            goto ret;
        }
    }

ret:
    return rc;
    
}

static const struct flux_plugin_handler tab[] = {
    { "job.state.depend", depend_cb, NULL },
    { 0 },
};

int flux_plugin_init (flux_plugin_t *p)
{
    if (flux_plugin_register (p, "dws-test", tab) < 0)
        return -1;
    return 0;
}
