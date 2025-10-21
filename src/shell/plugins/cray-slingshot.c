/************************************************************\
 * Copyright 2025 Lawrence Livermore National Security, LLC
 * (c.f. AUTHORS, NOTICE.LLNS, COPYING)
 *
 * This file is part of the Flux resource manager framework.
 * For details, see https://github.com/flux-framework.
 *
 * SPDX-License-Identifier: LGPL-3.0
\************************************************************/

/* cray-slingshot.c - shell plugin for Cassini NIC support
 *
 * There are three modes of operation:
 *
 * Inherit
 *   The SLINGSHOT_* environment is inherited from the broker
 *   environment.  This should work for any instance level, and
 *   when Flux is launched by a foreign resource manager.
 *
 * Reservation
 *   In a system instance, a VNI reservation is obtained from
 *   the cray-slingshot job event.  This mode assumes
 *   - the jobtap plugin creates a VNI reservation
 *   - a prolog script creates CXI services for the reservation
 *   - an epilog (and/or housekeeping) script destroys CXI services
 *   The shell plugin finds its CXI service numbers by querying the
 *   Cassini NICs for ones that match the reservation.
 *
 * Default
 *   The do-nothing option.  If neither reservation nor broker
 *   environment are available, then let applications figure out what
 *   to do.  Fully clear the SLINGSHOT_* environment just in case.
 *   If the default CXI service is enabled, applications can use that
 *   (at everyone's peril).
 *
 * If this plugin is getting in the way for some reason, it can
 * be completely disabled with -o cray-slingshot=off.
 */

#define FLUX_SHELL_PLUGIN_NAME "cray-slingshot"

#if HAVE_CONFIG_H
#include "config.h"
#endif
#include <string.h>
#include <math.h>
#include <jansson.h>
#include <argz.h>
#include <flux/shell.h>
#include <flux/idset.h>
#ifdef HAVE_LIBCXI_LIBCXI_H
#include <libcxi/libcxi.h>
#endif

#include "src/common/libutil/eventlog.h"
#include "ccan/str/str.h"

struct cray_slingshot_options {
    bool off;
    int vnicount;
};

struct cray_slingshot {
    flux_jobid_t jobid;
    flux_shell_t *shell;
    flux_future_t *f_event;
    flux_future_t *f_getenv;
    struct cray_slingshot_options opt;
};

/* See tcmask_from_desc().
 */
static const int tcmask_default = 0xf;

/* Convert json string array to a single string, e.g.
 * ["cxi0","cxi1"] => "cxi0,cxi1"
 */
static char *stringify_json_string_array (json_t *list)
{
    size_t index;
    json_t *entry;
    size_t argz_len = 0;
    char *argz = NULL;

    json_array_foreach (list, index, entry) {
        if (argz_add (&argz, &argz_len, json_string_value (entry)) != 0) {
            free (argz);
            return NULL;
        }
    }
    argz_stringify (argz, argz_len, ',');
    return argz;
}

/* Set an environment variable to a list of integers derived from a json string array
 */
static int setenv_json_int_array (flux_shell_t *shell, const char *name, json_t *list)
{
    if (json_array_size (list) == 0)
        return 0;  // not an error
    char *s;
    if (!(s = json_dumps (list, JSON_EMBED | JSON_COMPACT))  // EMBED strips enclosing braces
        || flux_shell_setenvf (shell, 1, name, "%s", s) < 0) {
        shell_log_error ("setenv %s failed", name);
        free (s);
        return -1;
    }
    free (s);
    return 0;
}

/* Set an environment variable to a list of names derived from a json string array.
 */
static int setenv_json_string_array (flux_shell_t *shell, const char *name, json_t *list)
{
    if (json_array_size (list) == 0)
        return 0;  // not an error
    char *s;
    if (!(s = stringify_json_string_array (list))
        || flux_shell_setenvf (shell, 1, name, "%s", s) < 0) {
        shell_log_error ("setenv %s failed", name);
        free (s);
        return -1;
    }
    free (s);
    return 0;
}

#ifdef HAVE_CXI
/* Convert traffic class flag array to bitmask.  This specific mapping is
 * required by Cray MPICH.
 */
static int tcmask_from_desc (struct cxi_svc_desc *desc)
{
    int map[CXI_TC_MAX] = {0};
    map[CXI_TC_DEDICATED_ACCESS] = 0x1;
    map[CXI_TC_LOW_LATENCY] = 0x2;
    map[CXI_TC_BULK_DATA] = 0x4;
    map[CXI_TC_BEST_EFFORT] = 0x8;

    int mask = 0;
    for (int i = 0; i < CXI_TC_MAX; i++)
        if (desc->tcs[i])
            mask |= map[i];
    return mask;
}

static int array_append_int (json_t *array, int val)
{
    json_t *o;
    if (!(o = json_integer (val)) || json_array_append_new (array, o) < 0) {
        json_decref (o);
        shell_log_error ("out of memory building int array");
        return -1;
    }
    return 0;
}

static int array_append_str (json_t *array, const char *val)
{
    json_t *o;
    if (!(o = json_string (val)) || json_array_append_new (array, o) < 0) {
        json_decref (o);
        shell_log_error ("out of memory building string array");
        return -1;
    }
    return 0;
}

/* If a CXI service is enabled, not a system service, and lists
 * the same VNIs as the provided JSON array, return true.
 * Assumption: VNIs are in the same order in both arrays,
 * and we needn't bother checking uid/gid restrictions.
 */
static bool match_cxi_service (struct cxi_svc_desc *desc, json_t *vnis)
{
    if (!desc->enable || desc->is_system_svc)
        return false;
    if (desc->num_vld_vnis != json_array_size (vnis))
        return false;
    for (int i = 0; i < desc->num_vld_vnis; i++) {
        json_t *entry = json_array_get (vnis, i);
        if (desc->vnis[i] != json_integer_value (entry))
            return false;
    }
    return true;
}

/* Find the first CXI service on the specified interface that has
 * VNIs matching the vnis array.  When found, append the service
 * ID to the svcs array.  If not found, append -1.
 * Any traffic classes not permitted by a CXI service are removed from tcmask.
 */
static int append_cxi_service_match (json_t *svcs, uint32_t dev_id, json_t *vnis, int *tcmask)
{
    int e;
    struct cxil_dev *dev;
    struct cxil_svc_list *svc_list = NULL;
    int match = -1;
    int match_tcmask = tcmask_default;
    int rc = -1;

    if ((e = cxil_open_device (dev_id, &dev)) < 0) {
        shell_log_errn (-e, "cxil_open_device cxi%u", dev_id);
        return -1;
    }
    if ((e = cxil_get_svc_list (dev, &svc_list)) < 0) {
        shell_log_errn (-e, "cxil_get_svc_list cxi%u", dev_id);
        goto done;
    }
    for (int i = 0; i < svc_list->count; i++) {
        if (match_cxi_service (&svc_list->descs[i], vnis)) {
            match = svc_list->descs[i].svc_id;
            match_tcmask = tcmask_from_desc (&svc_list->descs[i]);
            break;
        }
    }
    if (match == -1) {
        shell_warn ("cxi%u: CXI service for reserved VNIs not found", dev_id);
        match = -1;
    }
    if (array_append_int (svcs, match) < 0)
        goto done;
    *tcmask &= match_tcmask;
    rc = 0;
done:
    cxil_free_svc_list (svc_list);
    cxil_close_device (dev);
    return rc;
}

/* Find Cassini devices and add their names (e.g. "cxi0")
 * to the devs array and matching CXI service IDs to the svcs array.
 * Any traffic classes not permitted by a CXI service are removed from tcmask.
 */
static int add_devices (json_t *devs, json_t *svcs, json_t *vnis, int *tcmask)
{
    struct cxil_device_list *dev_list;
    int e;
    if ((e = cxil_get_device_list (&dev_list)) < 0) {
        shell_log_errn (-e, "cxil_get_device_list");
        return -1;
    }
    for (int i = 0; i < dev_list->count; i++) {
        if (array_append_str (devs, dev_list->info[i].device_name) < 0) {
            cxil_free_device_list (dev_list);
            return -1;
        }
        if (append_cxi_service_match (svcs, dev_list->info[i].dev_id, vnis, tcmask) < 0) {
            cxil_free_device_list (dev_list);
            return -1;
        }
    }
    cxil_free_device_list (dev_list);
    return 0;
}
#endif

/* Read the cray-slingshot event from eventlog to find reserved VNIs,
 * then look for corresponding CXI services placed there by the prolog.
 * The eventlog watch request was set in motion by the shell.init callback.
 * Return 0 for success, -1 for fatal error, or 1 on non-fatal error.
 */
static int cray_slingshot_reserved (struct cray_slingshot *ctx)
{
    flux_error_t error;
    json_t *res;
    json_t *vnis;
    json_error_t jerror;
    json_t *devices = NULL;
    json_t *cxi_svc = NULL;
    int tcmask = tcmask_default;
    int rc = -1;

    if (eventlog_wait_for (ctx->f_event, "cray-slingshot", -1., &res, &error) < 0) {
        shell_log_error ("waiting for eventlog: %s", error.text);
        return -1;
    }
    if (!res)
        return 1;  // optional event was not posted
    if (json_unpack_ex (res, &jerror, 0, "{s:o}", "vnis", &vnis) < 0) {
        shell_log_error ("parsing cray-slingshot event context: %s", jerror.text);
        return -1;
    }
    if (!(devices = json_array ()) || !(cxi_svc = json_array ())) {
        shell_log_error ("out of memory building device/service lists");
        goto done;
    }
#ifdef HAVE_CXI
    if (add_devices (devices, cxi_svc, vnis, &tcmask) < 0)
        goto done;
#endif
    if (json_array_size (devices) == 0)
        shell_warn ("no slingshot devices were found");
    if (setenv_json_int_array (ctx->shell, "SLINGSHOT_VNIS", vnis) < 0
        || setenv_json_string_array (ctx->shell, "SLINGSHOT_DEVICES", devices) < 0
        || setenv_json_int_array (ctx->shell, "SLINGSHOT_SVC_IDS", cxi_svc) < 0
        || flux_shell_setenvf (ctx->shell, 1, "SLINGSHOT_TCS", "0x%x", tcmask) < 0)
        goto done;
    shell_debug ("setting environment for VNI reservation");
    rc = 0;
done:
    json_decref (cxi_svc);
    json_decref (devices);
    json_decref (res);
    return rc;
}

/* Pass local broker's SLINGSHOT environment variables through.
 * The getenv request was set in motion by the shell.init callback.
 * Return 0 for success, -1 for fatal error, or 1 on non-fatal error.
 */
static int cray_slingshot_inherit (struct cray_slingshot *ctx)
{
    const char *vnis = NULL;
    const char *devices = NULL;
    const char *svc_ids = NULL;
    const char *tcs = NULL;

    if (flux_rpc_get_unpack (ctx->f_getenv,
                             "{s:{s?s s?s s?s s?s}}",
                             "env",
                             "SLINGSHOT_VNIS",
                             &vnis,
                             "SLINGSHOT_DEVICES",
                             &devices,
                             "SLINGSHOT_SVC_IDS",
                             &svc_ids,
                             "SLINGSHOT_TCS",
                             &tcs)
        < 0) {
        if (errno != EPERM && errno != ENOSYS) {
            shell_log_error ("broker.getenv: %s", future_strerror (ctx->f_getenv, errno));
            return -1;
        }
    }
    if (!vnis)
        return 1;
    if (flux_shell_setenvf (ctx->shell, 1, "SLINGSHOT_VNIS", "%s", vnis) < 0
        || (devices && flux_shell_setenvf (ctx->shell, 1, "SLINGSHOT_DEVICES", "%s", devices) < 0)
        || (svc_ids && flux_shell_setenvf (ctx->shell, 1, "SLINGSHOT_SVC_IDS", "%s", svc_ids) < 0)
        || (tcs && flux_shell_setenvf (ctx->shell, 1, "SLINGSHOT_TCS", "%s", tcs) < 0)) {
        shell_log_error ("setenv SLINGSHOT_* failed");
        return -1;
    }
    shell_debug ("using inherited job environment");
    return 0;
}

/* shell.post-init (after init barrier, before task launch)
 *
 * Try each method to get SLINGSHOT environment set up until one works
 * Methods return 0 if successful, -1 on fatal error, or 1 on non-fatal error.
 */
static int shell_post_init_cb (flux_plugin_t *p,
                               const char *topic,
                               flux_plugin_arg_t *args,
                               void *data)
{
    struct cray_slingshot *ctx = data;
    int rc;

    if ((rc = cray_slingshot_inherit (ctx)) <= 0)
        return rc;
    if ((rc = cray_slingshot_reserved (ctx)) <= 0)
        return rc;
    shell_debug ("no job environment is set");
    return 0;
}

/* shell.init (after broker connect, before init barrier)
 *
 * Set in motion two possible options that can run in parallel
 * with the shell barrier:
 * - obtain allocated VNIs from the eventlog
 * - inherit VNIs/CXI services from the local broker
 */
static int shell_init_cb (flux_plugin_t *p, const char *topic, flux_plugin_arg_t *args, void *data)
{
    struct cray_slingshot *ctx = data;
    flux_t *h = flux_shell_get_flux (ctx->shell);

    if (!(ctx->f_event = flux_job_event_watch (h, ctx->jobid, "eventlog", 0)))
        shell_die (1, "error sending eventlog watch request");

    if (!(ctx->f_getenv = flux_rpc_pack (h,
                                         "broker.getenv",
                                         FLUX_NODEID_ANY,
                                         0,
                                         "{s:[ssss]}",
                                         "names",
                                         "SLINGSHOT_VNIS",
                                         "SLINGSHOT_DEVICES",
                                         "SLINGSHOT_SVC_IDS",
                                         "SLINGSHOT_TCS")))
        shell_die (1, "error sending broker.getenv request");
    return 0;
}

static void cray_slingshot_destroy (struct cray_slingshot *ctx)
{
    if (ctx) {
        int saved_errno = errno;
        flux_future_destroy (ctx->f_event);
        flux_future_destroy (ctx->f_getenv);
        free (ctx);
        errno = saved_errno;
    }
}

static struct cray_slingshot *cray_slingshot_create (flux_shell_t *shell)
{
    struct cray_slingshot *ctx;

    if (!(ctx = calloc (1, sizeof (*ctx))))
        return NULL;
    if (flux_shell_info_unpack (shell, "{s:I}", "jobid", &ctx->jobid) < 0) {
        shell_log_error ("Error unpacking jobid from shell info");
        goto error;
    }
    ctx->shell = shell;
    return ctx;
error:
    cray_slingshot_destroy (ctx);
    return NULL;
}

/* Parse plugin options
 *   -o cray-slingshot=off
 *   -o cray-slingshot.vnicount=N
 */
static int cray_slingshot_parse_args (struct cray_slingshot *ctx,
                                      struct cray_slingshot_options *optp)
{
    json_t *options = NULL;
    struct cray_slingshot_options opt = {0};

    if (flux_shell_getopt_unpack (ctx->shell, "cray-slingshot", "o", &options) < 0) {
        shell_log_error ("-o cray-slingshot: error unpacking options");
        goto error;
    }
    if (options) {
        if (json_is_string (options)) {
            const char *val = json_string_value (options);
            if (streq (val, "off"))
                opt.off = true;
            else {
                shell_log_error ("-o cray-slingshot: invalid option: %s", val);
                goto error;
            }
        } else {
            json_error_t jerror;
            if (json_unpack_ex (options, &jerror, 0, "{s?i !}", "vnicount", &opt.vnicount) < 0) {
                shell_log_error ("-o cray-slingshot: %s", jerror.text);
                goto error;
            }
        }
    }
    *optp = opt;
    return 0;
error:
    errno = EINVAL;
    return -1;
}

int flux_plugin_init (flux_plugin_t *p)
{
    flux_shell_t *shell;
    struct cray_slingshot *ctx;

    if (!(shell = flux_plugin_get_shell (p))
        || flux_plugin_set_name (p, FLUX_SHELL_PLUGIN_NAME) < 0)
        return -1;

    if (!(ctx = cray_slingshot_create (shell))
        || flux_plugin_aux_set (p, NULL, ctx, (flux_free_f)cray_slingshot_destroy) < 0) {
        cray_slingshot_destroy (ctx);
        return -1;
    }

    if (cray_slingshot_parse_args (ctx, &ctx->opt) < 0)
        return -1;
    if (ctx->opt.off)
        return 0;

    // start with a clean slingshot environment
    flux_shell_unsetenv (ctx->shell, "SLINGSHOT_VNIS");
    flux_shell_unsetenv (ctx->shell, "SLINGSHOT_DEVICES");
    flux_shell_unsetenv (ctx->shell, "SLINGSHOT_SVC_IDS");
    flux_shell_unsetenv (ctx->shell, "SLINGSHOT_TCS");

    if (flux_plugin_add_handler (p, "shell.init", shell_init_cb, ctx) < 0
        || flux_plugin_add_handler (p, "shell.post-init", shell_post_init_cb, ctx) < 0)
        return -1;

    return 0;
}

// vi:ts=4 sw=4 expandtab
