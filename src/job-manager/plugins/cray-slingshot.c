/************************************************************\
 * Copyright 2025 Lawrence Livermore National Security, LLC
 * (c.f. AUTHORS, NOTICE.LLNS, COPYING)
 *
 * This file is part of the Flux resource manager framework.
 * For details, see https://github.com/flux-framework.
 *
 * SPDX-License-Identifier: LGPL-3.0
\************************************************************/

/* cray-slingshot.c - post reserved VNIs to job eventlog
 *
 * This should be loaded in the system instance only.  In sub-instances,
 * VNIs (and CXI services) are inherited from a system instance allocation.
 *
 * Optional TOML config (defaults are shown commented out):
 *   [cray-slingshot]
 *   #vni-pool = "1024-65535"
 *   #vnis-per-job = 1
 *   #vni-reserve-fatal = true
 *
 * The following job shell options are parsed by the jobtap plugin:
 *  -o cray-slingshot=off
 *     Disable VNI reservation for this job.
 *  -o cray-slingshot.vnicount=N
 *     Request that N VNIs be reserved for this job (0-4).
 * Other cray-slingshot options are ignored.
 *
 * A cray-slingshot job event is posted to define the reservation when
 * the job enters the run state:
 *   {"name":"cray-slingshot","context":{"vnis":[1030,1032]}}
 *
 * The reservation can be empty, e.g.
 *   {"name":"cray-slingshot","context":{"vnis":[],"empty-reason":s}}
 * That happens when:
 * 1) job is submitted with -o cray-slingshot=off
 * 2) job is submitted with -o cray-slingshot.vnicount=0
 * 3) vnis-per-job=0 and job is submitted without -o cray-slingshot.vnicount
 * 4) vni-reserve-fatal=false and the reservation cannot be fulfilled
 *
 * For more info on the Slingshot Flux integration refer to
 *   https://flux-framework.readthedocs.io/projects/flux-coral2/en/latest/guide/slingshot.html
 */

#if HAVE_CONFIG_H
#include "config.h"
#endif
#include <jansson.h>
#include <flux/core.h>
#include <flux/jobtap.h>

#include "src/common/libutil/errprintf.h"
#include "src/common/libutil/idf58.h"
#include "ccan/str/str.h"

#include "vnipool.h"

#define PLUGIN_NAME "cray-slingshot"

struct cray_slingshot {
    struct vnipool *vnipool;
    int vnis_per_job;
    bool vni_reserve_fatal;
};

static const char *vni_pool_default = VNIPOOL_DEFAULT;
static const int vnis_per_job_default = 1;
static const bool vni_reserve_fatal_default = true;

static void cray_slingshot_destroy (struct cray_slingshot *ctx)
{
    if (ctx) {
        int saved_errno = errno;
        vnipool_destroy (ctx->vnipool);
        free (ctx);
        errno = saved_errno;
    }
}

static struct cray_slingshot *cray_slingshot_create (void)
{
    struct cray_slingshot *ctx;
    if (!(ctx = calloc (1, sizeof (*ctx))))
        return NULL;
    if (!(ctx->vnipool = vnipool_create ()))
        goto error;
    // config callback completes initialization
    return ctx;
error:
    cray_slingshot_destroy (ctx);
    return NULL;
}

/* plugin.query
 */
static int plugin_query_cb (flux_plugin_t *p, const char *topic, flux_plugin_arg_t *args, void *arg)
{
    struct cray_slingshot *ctx = arg;
    flux_t *h = flux_jobtap_get_flux (p);
    json_t *vnipool;

    if (!(vnipool = vnipool_query (ctx->vnipool))) {
        flux_log_error (h, "%s: error creating query response", PLUGIN_NAME);
        return -1;
    }
    if (flux_plugin_arg_pack (args,
                              FLUX_PLUGIN_ARG_OUT,
                              "{s:i s:b s:O}",
                              "vnis-per-job",
                              ctx->vnis_per_job,
                              "vni-reserve-fatal",
                              ctx->vni_reserve_fatal ? 1 : 0,
                              "vnipool",
                              vnipool)
        < 0) {
        flux_log_error (h, "%s: error packing query args", PLUGIN_NAME);
        json_decref (vnipool);
        return -1;
    }
    json_decref (vnipool);
    return 0;
}

/* conf.update
 * This is called initially and each time the config object changes.
 */
static int conf_update_cb (flux_plugin_t *p, const char *topic, flux_plugin_arg_t *args, void *arg)
{
    struct cray_slingshot *ctx = arg;
    const char *vni_pool = vni_pool_default;
    int vnis_per_job = vnis_per_job_default;
    int vni_reserve_fatal = vni_reserve_fatal_default;
    flux_error_t error;

    if (flux_plugin_arg_unpack (args,
                                FLUX_PLUGIN_ARG_IN,
                                "{s:{s?{s?s s?i s?b}}}",
                                "conf",
                                "cray-slingshot",
                                "vni-pool",
                                &vni_pool,
                                "vnis-per-job",
                                &vnis_per_job,
                                "vni-reserve-fatal",
                                &vni_reserve_fatal)
        < 0) {
        errprintf (&error,
                   "%s: error unpacking conf.update arguments: %s",
                   PLUGIN_NAME,
                   flux_plugin_arg_strerror (args));
        goto error;
    }
    if (vnis_per_job < 0 || vnis_per_job > 4) {
        errprintf (&error, "%s: cray-slingshot.vnis-per-job value out of range (0-4)", PLUGIN_NAME);
        errno = EINVAL;
        goto error;
    }
    ctx->vnis_per_job = vnis_per_job;
    ctx->vni_reserve_fatal = vni_reserve_fatal ? true : false;
    if (vnipool_configure (ctx->vnipool, vni_pool, &error) < 0)
        goto error;
    return 0;
error:
    return flux_jobtap_error (p, args, "%s", error.text);
}

/* Post the cray-slingshot event with context like this:
 *    {"vnis":[i,i,i,...], "empty-reason"?s}
 */
static int post_event (flux_plugin_t *p,
                       flux_jobid_t id,
                       json_t *vnis,
                       const char *empty_reason,
                       flux_error_t *error)
{
    json_t *context;

    if (vnis)
        context = json_pack ("{s:O}", "vnis", vnis);
    else
        context = json_pack ("{s:[]}", "vnis");
    if (!context)
        goto error;
    if (empty_reason) {
        json_t *o;
        if (!(o = json_string (empty_reason))
            || json_object_set_new (context, "empty-reason", o) < 0) {
            json_decref (o);
            goto error;
        }
    }
    if (flux_jobtap_event_post_pack (p, id, "cray-slingshot", "O", context) < 0) {
        errprintf (error, "error posting cray-slingshot event");
        json_decref (context);
        return -1;
    }
    return 0;
error:
    errprintf (error, "error constructing cray-slingshot event context");
    json_decref (context);
    return -1;
}

/* job.state.run
 */
static int job_state_run_cb (flux_plugin_t *p,
                             const char *topic,
                             flux_plugin_arg_t *args,
                             void *arg)
{
    struct cray_slingshot *ctx = arg;
    flux_error_t error;
    flux_jobid_t id;
    json_t *options = NULL;
    json_t *R;
    int vnicount = -1;
    json_t *vnis;
    const char *empty_reason = NULL;

    if (flux_plugin_arg_unpack (args,
                                FLUX_PLUGIN_ARG_IN,
                                "{s:I s:{s:{s:{s?{s?{s?o}}}}} s:o}",
                                "id",
                                &id,
                                "jobspec",
                                "attributes",
                                "system",
                                "shell",
                                "options",
                                "cray-slingshot",
                                &options,
                                "R",
                                &R)
        < 0) {
        errprintf (&error, "error unpacking job info: %s", strerror (errno));
        goto error;
    }
    if (options) {
        // -o cray-slingshot=off
        if (json_is_string (options) && streq (json_string_value (options), "off")) {
            empty_reason = "disabled by user request";
            goto empty;
        }
        // -o cray-slingshot.vnicount=N
        json_error_t jerror;
        if (json_unpack_ex (options, &jerror, 0, "{s?i}", "vnicount", &vnicount) < 0) {
            errprintf (&error, "error parsing cray-slingshot shell options: %s", jerror.text);
            errno = EINVAL;
            goto error;
        }
    }
    if (vnicount == -1)
        vnicount = ctx->vnis_per_job;
    if (vnicount == 0) {
        empty_reason = "none requested";
        goto empty;
    }
    if (!(vnis = vnipool_reserve (ctx->vnipool, id, vnicount, &error))) {
        if (!ctx->vni_reserve_fatal) {
            empty_reason = error.text;
            goto empty;
        }
        goto error;
    }
    if (post_event (p, id, vnis, empty_reason, &error) < 0) {
        (void)vnipool_release (ctx->vnipool, id, NULL);
        goto error;
    }
    return 0;
empty:
    if (post_event (p, id, NULL, empty_reason, &error) < 0)
        goto error;
    return 0;
error:
    flux_jobtap_raise_exception (p, id, "cray-slingshot", 0, "%s", error.text);
    return 0;
}

/* job.state.cleanup
 */
static int job_state_cleanup_cb (flux_plugin_t *p,
                                 const char *topic,
                                 flux_plugin_arg_t *args,
                                 void *arg)
{
    struct cray_slingshot *ctx = arg;
    flux_t *h = flux_jobtap_get_flux (p);
    flux_jobid_t id;
    flux_error_t error;

    if (flux_plugin_arg_unpack (args, FLUX_PLUGIN_ARG_IN, "{s:I}", "id", &id) < 0) {
        flux_log_error (h, "flux_plugin_arg_unpack");
        return -1;
    }
    if (vnipool_release (ctx->vnipool, id, &error) < 0 && errno != ENOENT) {
        flux_log (h,
                  LOG_ERR,
                  "%s: VNI release error for %s: %s",
                  PLUGIN_NAME,
                  idf58 (id),
                  error.text);
        return -1;
    }
    return 0;
}

/* jobtap plugin main entry point
 */
int flux_plugin_init (flux_plugin_t *p)
{
    struct cray_slingshot *ctx;

    if (!(ctx = cray_slingshot_create ()) || flux_plugin_set_name (p, PLUGIN_NAME) < 0
        || flux_plugin_add_handler (p, "job.state.run", job_state_run_cb, ctx) < 0
        || flux_plugin_add_handler (p, "job.state.cleanup", job_state_cleanup_cb, ctx) < 0
        || flux_plugin_add_handler (p, "conf.update", conf_update_cb, ctx) < 0
        || flux_plugin_add_handler (p, "plugin.query", plugin_query_cb, ctx) < 0
        || flux_plugin_aux_set (p, NULL, ctx, (flux_free_f)cray_slingshot_destroy)) {
        cray_slingshot_destroy (ctx);
        return -1;
    }
    return 0;
}

// vi:ts=4 sw=4 expandtab
