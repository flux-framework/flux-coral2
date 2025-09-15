/************************************************************\
 * Copyright 2025 Lawrence Livermore National Security, LLC
 * (c.f. AUTHORS, NOTICE.LLNS, COPYING)
 *
 * This file is part of the Flux resource manager framework.
 * For details, see https://github.com/flux-framework.
 *
 * SPDX-License-Identifier: LGPL-3.0
\************************************************************/

/* flux-slingshot.c - prolog/epilog/housekeeping helper */

#if HAVE_CONFIG_H
#include "config.h"
#endif
#include <unistd.h>
#include <stdio.h>
#include <stdarg.h>
#include <jansson.h>
#include <flux/core.h>
#include <flux/optparse.h>
#include <flux/idset.h>
#ifdef HAVE_LIBCXI_LIBCXI_H
#include <libcxi/libcxi.h>
#endif
#ifndef CXI_SVC_MAX_VNIS
#define CXI_SVC_MAX_VNIS 4
#endif
#ifndef CXI_DEFAULT_SVC_ID
#define CXI_DEFAULT_SVC_ID 1
#endif
#include "src/common/libutil/eventlog.h"
#include "src/common/libutil/idf58.h"
#include "src/common/libutil/fsd.h"
#include "src/common/libutil/monotime.h"
#include "ccan/str/str.h"

#ifndef MIN
#define MIN(a, b) ((a) < (b) ? (a) : (b))
#endif

static int cmd_prolog (optparse_t *p, int argc, char **argv);
static int cmd_epilog (optparse_t *p, int argc, char **argv);
static int cmd_list (optparse_t *p, int argc, char **argv);
static int cmd_jobinfo (optparse_t *p, int argc, char **argv);
static int cmd_clean (optparse_t *p, int argc, char **argv);

static struct optparse_option prolog_opts[] = {
    {
        .name = "dry-run",
        .has_arg = 0,
        .usage = "List actions instead of performing them",
    },
    {
        .name = "userid",
        .key = 'u',
        .has_arg = 1,
        .usage = "Override FLUX_JOB_USER",
    },
    {
        .name = "jobid",
        .key = 'j',
        .has_arg = 1,
        .usage = "Override FLUX_JOB_ID",
    },
    OPTPARSE_TABLE_END,
};

static struct optparse_option epilog_opts[] = {
    {
        .name = "dry-run",
        .has_arg = 0,
        .usage = "List actions instead of performing them",
    },
    {
        .name = "userid",
        .key = 'u',
        .has_arg = 1,
        .arginfo = "UID",
        .usage = "Override FLUX_JOB_USER",
    },
    {
        .name = "jobid",
        .key = 'j',
        .has_arg = 1,
        .arginfo = "ID",
        .usage = "Override FLUX_JOB_ID",
    },
    {
        .name = "retry-busy",
        .has_arg = 1,
        .arginfo = "FSD",
        .usage = "Retry EBUSY failures for specified duration",
    },
    OPTPARSE_TABLE_END,
};

static struct optparse_option list_opts[] = {
    {
        .name = "no-header",
        .key = 'n',
        .has_arg = 0,
        .usage = "Suppress printing of header line",
    },
    OPTPARSE_TABLE_END,
};

static struct optparse_option jobinfo_opts[] = {
    {
        .name = "jobid",
        .key = 'j',
        .has_arg = 1,
        .usage = "Override FLUX_JOB_ID",
    },
    OPTPARSE_TABLE_END,
};

static struct optparse_option clean_opts[] = {
    {
        .name = "dry-run",
        .has_arg = 0,
        .usage = "List actions instead of performing them",
    },
    {
        .name = "retry-busy",
        .has_arg = 1,
        .arginfo = "FSD",
        .usage = "Retry EBUSY failures for specified duration",
    },
    OPTPARSE_TABLE_END,
};

static struct optparse_subcommand subcommands[] = {
    {
        .name = "prolog",
        .usage = "[OPTIONS]",
        .doc = "Create CXI services for job's VNI reservation",
        .fn = cmd_prolog,
        .flags = 0,
        .opts = prolog_opts,
    },
    {
        .name = "epilog",
        .usage = "[OPTIONS]",
        .doc = "Remove CXI services for job's VNI reservation",
        .fn = cmd_epilog,
        .flags = 0,
        .opts = epilog_opts,
    },
    {
        .name = "list",
        .usage = "[OPTIONS]",
        .doc = "List devices and their CXI service counts",
        .fn = cmd_list,
        .flags = 0,
        .opts = list_opts,
    },
    {
        .name = "jobinfo",
        .usage = "[OPTIONS]",
        .doc = "Show job's slingshot reservation in JSON form",
        .fn = cmd_jobinfo,
        .flags = 0,
        .opts = jobinfo_opts,
    },
    {
        .name = "clean",
        .usage = "[OPTIONS]",
        .doc = "Clean orphan CXI services",
        .fn = cmd_clean,
        .flags = 0,
        .opts = clean_opts,
    },
    OPTPARSE_SUBCMD_END,
};

static const char *prog = "flux-slingshot";

static double eventlog_timeout = 30.;

static void vwarn (const char *fmt, va_list ap)
{
    char buf[160];
    (void)vsnprintf (buf, sizeof (buf), fmt, ap);
    fprintf (stderr, "%s: %s\n", prog, buf);
}

static void warn (const char *fmt, ...)
{
    va_list ap;
    va_start (ap, fmt);
    vwarn (fmt, ap);
    va_end (ap);
}

static void fatal (const char *fmt, ...)
{
    va_list ap;
    va_start (ap, fmt);
    vwarn (fmt, ap);
    va_end (ap);
    exit (1);
}

#if HAVE_CXI
typedef bool (*svc_match_f) (struct cxi_svc_desc *desc, void *match_info);

struct res_match_info {
    uid_t uid;
    json_t *vnis;
};

/* Match a CXI service to reservation if the service
 * - is not a system service
 * - has a one access restriction that matches job owner
 * - has VNI restrictions that exactly match the reservation (in order)
 */
static bool match_reservation (struct cxi_svc_desc *desc, void *match_info)
{
    struct res_match_info *match = match_info;

    if (desc->is_system_svc)
        return false;
    if (!desc->restricted_members || desc->members[0].type != CXI_SVC_MEMBER_UID
        || desc->members[0].svc_member.uid != match->uid)
        return false;
    if (!desc->restricted_vnis || desc->num_vld_vnis != json_array_size (match->vnis))
        return false;
    for (int i = 0; i < desc->num_vld_vnis; i++) {
        json_t *entry = json_array_get (match->vnis, i);
        if (desc->vnis[i] != json_integer_value (entry))
            return false;
    }
    return true;
}

/* Match a CXI service to the configured VNI pool.
 */
static bool match_vnipool (struct cxi_svc_desc *desc, struct idset *vnipool)
{
    if (!desc->is_system_svc) {
        for (int i = 0; i < desc->num_vld_vnis; i++) {
            if (idset_test (vnipool, desc->vnis[i]))
                return true;
        }
    }
    return false;
}

/* Destroy one or more matching CXI services on device 'dev'.
 * If all is true, remove all matches, otherwise just the first.
 * The match function and its argument are used to select targets.
 * Returns the number of EBUSY failures.
 * to EBUSY.  Respects "dry-run" option.
 */
static int destroy_cxi_service_device (struct cxil_dev *dev,
                                       optparse_t *p,
                                       bool all,
                                       svc_match_f matchfun,
                                       void *match_info)
{
    int dev_id = dev->info.dev_id;
    int e;
    struct cxil_svc_list *svc_list;
    int busycount = 0;
    int matchcount = 0;

    if ((e = cxil_get_svc_list (dev, &svc_list)) < 0) {
        warn ("cxi%u: cxil_get_svc_list", dev_id, strerror (-e));
        return 0;
    }
    for (int i = 0; i < svc_list->count && (all || matchcount == 0); i++) {
        struct cxi_svc_desc *desc = &svc_list->descs[i];
        if (matchfun (desc, match_info)) {
            matchcount++;
            if (!optparse_hasopt (p, "dry-run")) {
                if ((e = cxil_destroy_svc (dev, desc->svc_id)) < 0) {
                    warn ("cxi%u: cxil_destroy_svc: %s", dev_id, desc->svc_id, strerror (-e));
                    if (e == -EBUSY)
                        busycount++;
                    continue;
                }
            }
            warn ("cxi%u: destroy svc_id=%u", dev_id, desc->svc_id);
        }
    }
    cxil_free_svc_list (svc_list);
    return busycount;
}

/* Destroy one or more matching CXI services on all devices.
 * If all is true, remove all matches, o/w just the first on each device.
 * The match function and its argument are used to select targets.
 * Returns the number of EBUSY failures.
 * Respects "dry-run" option.
 */
static int destroy_cxi_service (optparse_t *p, bool all, svc_match_f match_fun, void *match_info)
{
    struct cxil_device_list *dev_list;
    int e;
    int busycount = 0;

    if ((e = cxil_get_device_list (&dev_list)) < 0)
        fatal ("cxil_get_device_list: %s", strerror (-e));
    for (int i = 0; i < dev_list->count; i++) {
        uint32_t dev_id = dev_list->info[i].dev_id;
        struct cxil_dev *dev;

        if ((e = cxil_open_device (dev_id, &dev)) < 0) {
            warn ("cxi%u: cxil_open_device: %s", dev_id, strerror (-e));
            continue;
        }
        busycount += destroy_cxi_service_device (dev, p, all, match_fun, match_info);
        cxil_close_device (dev);
    }
    cxil_free_device_list (dev_list);
    return busycount;
}

/* Allocate a CXI service on 'dev'.
 */
static void allocate_cxi_service_device (struct cxil_dev *dev,
                                         optparse_t *p,
                                         uid_t uid,
                                         json_t *vnis,
                                         int ncores)
{
    int e;
    struct cxi_svc_desc desc = {0};
    struct cxi_svc_fail_info fail_info = {0};

    desc.restricted_vnis = 1;
    desc.num_vld_vnis = json_array_size (vnis);
    for (int i = 0; i < desc.num_vld_vnis; i++) {
        json_t *entry = json_array_get (vnis, i);
        desc.vnis[i] = json_integer_value (entry);
    }

    desc.restricted_members = 1;
    desc.members[0].type = CXI_SVC_MEMBER_UID;
    desc.members[0].svc_member.uid = uid;
    desc.members[1].type = CXI_SVC_MEMBER_IGNORE;

    desc.resource_limits = 1;
    desc.limits.txqs.max = MIN (2048, dev->info.num_txqs);
    desc.limits.tgqs.max = MIN (1024, dev->info.num_tgqs);
    desc.limits.eqs.max = MIN (2047, dev->info.num_eqs);
    desc.limits.cts.max = MIN (2047, dev->info.num_cts);
    desc.limits.tles.max = MIN (1 * ncores, dev->info.num_tles);
    desc.limits.ptes.max = MIN (2048, dev->info.num_ptes);
    desc.limits.les.max = MIN (16384, dev->info.num_les);
    desc.limits.acs.max = MIN (1022, dev->info.num_acs);

    desc.limits.txqs.res = MIN (2 * ncores, desc.limits.txqs.max);
    desc.limits.tgqs.res = MIN (1 * ncores, desc.limits.tgqs.max);
    desc.limits.eqs.res = MIN (2 * ncores, desc.limits.eqs.max);
    desc.limits.cts.res = MIN (1 * ncores, desc.limits.cts.max);
    desc.limits.tles.res = MIN (1 * ncores, desc.limits.tles.max);
    desc.limits.ptes.res = MIN (6 * ncores, desc.limits.ptes.max);
    desc.limits.les.res = MIN (16 * ncores, desc.limits.les.max);
    desc.limits.acs.res = MIN (2 * ncores, desc.limits.acs.max);

    desc.restricted_tcs = 1;
    desc.tcs[CXI_TC_BEST_EFFORT] = true;
    desc.tcs[CXI_TC_LOW_LATENCY] = true;

    if (!optparse_hasopt (p, "dry-run")) {
        if ((e = cxil_alloc_svc (dev, &desc, &fail_info)) < 0) {
            for (int i = 0; i < CXI_RSRC_TYPE_MAX; i++) {
                if (fail_info.rsrc_avail[i] < desc.limits.type[i].res) {
                    warn ("%s: cannot reserve %hu %s: only %hu available",
                          dev->info.device_name,
                          desc.limits.type[i].res,
                          cxi_rsrc_type_strs[i],
                          fail_info.rsrc_avail[i]);
                }
            }
            if (fail_info.no_le_pools)
                warn ("%s: no LE pools available", dev->info.device_name);
            if (fail_info.no_tle_pools)
                warn ("%s: no TLE pools available", dev->info.device_name);
            if (fail_info.no_cntr_pools)
                warn ("%s: no CNTR pools available", dev->info.device_name);
            fatal ("cxi%u: cxil_alloc_svc: %s", dev->info.dev_id, strerror (-e));
        }
    } else
        e = -1;
    char *s = json_dumps (vnis, JSON_COMPACT);
    warn ("cxi%u: alloc cxi_svc=%d uid=%u ncores=%d vnis=%s",
          dev->info.dev_id,
          e,
          uid,
          ncores,
          s ? s : "");
    free (s);
}

/* Allocate a CXI service on all Cassini devices.
 */
static int allocate_cxi_service (optparse_t *p, uid_t uid, json_t *vnis, int ncores)
{
    int count = 0;
    struct cxil_device_list *dev_list;
    int e;

    if ((e = cxil_get_device_list (&dev_list)) < 0)
        fatal ("cxil_get_device_list: %s", strerror (-e));
    for (int i = 0; i < dev_list->count; i++) {
        uint32_t dev_id = dev_list->info[i].dev_id;
        struct cxil_dev *dev;

        if ((e = cxil_open_device (dev_id, &dev)) < 0) {
            warn ("cxi%u: cxil_open_device: %s", dev_id, strerror (-e));
            continue;
        }
        allocate_cxi_service_device (dev, p, uid, vnis, ncores);
        cxil_close_device (dev);
        count++;
    }
    cxil_free_device_list (dev_list);
    return count;
}
#endif  // HAVE_CXI

/* Get jobid and userid from the perilog environment, with override
 * from command line.
 */
static void parse_job_info (optparse_t *p, flux_jobid_t *idp, uid_t *uidp)
{
    const char *s;

    if (idp) {
        flux_jobid_t id;

        if (!(s = optparse_get_str (p, "jobid", getenv ("FLUX_JOB_ID"))))
            fatal ("FLUX_JOB_ID is not set.  Try --jobid=ID.");
        if (flux_job_id_parse (s, &id) < 0)
            fatal ("error parsing jobid");
        *idp = id;
    }
    if (uidp) {
        uid_t uid;
        char *endptr;

        if (!(s = optparse_get_str (p, "userid", getenv ("FLUX_JOB_USERID"))))
            fatal ("FLUX_JOB_USERID is not set.  Try --userid=UID.");
        errno = 0;
        uid = strtoul (s, &endptr, 10);
        if (errno != 0 || *endptr != '\0')
            fatal ("error parsing userid");
        *uidp = uid;
    }
}

static json_t *lookup_reservation (flux_t *h, flux_jobid_t id)
{
    flux_future_t *f;
    json_t *res;
    flux_error_t error;

    if (!(f = flux_job_event_watch (h, id, "eventlog", 0)))
        fatal ("error sending eventlog watch request");
    if (eventlog_wait_for (f, "cray-slingshot", eventlog_timeout, &res, &error) < 0)
        fatal ("%s", error.text);
    flux_future_destroy (f);
    return res;
}

/* Parse and validate the vnis array from the cray-slingshot
 * reservation object.  The returned object is borrowed from 'res'.
 */
static json_t *parse_reservation_vnis (json_t *res)
{
    json_t *vnis;
    size_t index;
    json_t *entry;

    if (json_unpack (res, "{s:o}", "vnis", &vnis) < 0 || json_array_size (vnis) > CXI_SVC_MAX_VNIS)
        return NULL;
    json_array_foreach (vnis, index, entry) {
        if (!json_is_integer (entry) || json_integer_value (entry) < 0
            || json_integer_value (entry) == 1 || json_integer_value (entry) == 10
            || json_integer_value (entry) > 65535)
            return NULL;
    }
    return vnis;
}

static int ncores_from_R (flux_future_t *f)
{
    flux_t *h = flux_future_get_flux (f);
    uint32_t rank;
    const char *R;
    json_error_t jerror;
    json_t *o;
    json_t *R_lite;
    size_t index;
    json_t *entry;
    int ncores = 0;

    if (flux_get_rank (h, &rank) < 0)
        fatal ("could not determine rank");
    if (flux_rpc_get_unpack (f, "{s:s}", "R", &R) < 0)
        fatal ("could not lookup R: %s", future_strerror (f, errno));
    if (!(o = json_loads (R, 0, &jerror))
        || json_unpack_ex (o, &jerror, 0, "{s:{s:o}}", "execution", "R_lite", &R_lite) < 0)
        fatal ("error decoding R_lite: %s", jerror.text);
    json_array_foreach (R_lite, index, entry) {
        const char *r;
        const char *c;
        struct idset *ranks;
        struct idset *cores;

        if (json_unpack_ex (entry, &jerror, 0, "{s:s s:{s:s}}", "rank", &r, "children", "core", &c)
            < 0)
            fatal ("error decoding R_lite[%zu]: %s", index, jerror.text);
        if (!(ranks = idset_decode (r)) || !(cores = idset_decode (c)))
            fatal ("error decoding R_lite[%zu] ranks/cores", index);
        if (idset_test (ranks, rank))
            ncores = idset_count (cores);
        idset_destroy (ranks);
        idset_destroy (cores);
        if (ncores > 0)
            break;
    }
    json_decref (o);
    return ncores;
}

static flux_future_t *lookup_R (flux_t *h, flux_jobid_t id)
{
    return flux_rpc_pack (h,
                          "job-info.lookup",
                          FLUX_NODEID_ANY,
                          0,
                          "{s:I s:[s] s:i}",
                          "id",
                          id,
                          "keys",
                          "R",
                          "flags",
                          0);
}

static int cmd_prolog (optparse_t *p, int argc, char **argv)
{
    int optindex = optparse_option_index (p);
    flux_jobid_t id;
    uid_t uid;
    flux_t *h;
    flux_future_t *f_R;
    flux_future_t *f_eventlog;
    flux_error_t error;
    json_t *res;
    json_t *vnis;
    int ncores;

    if (optindex < argc)
        fatal ("free arguments are not supported");
    parse_job_info (p, &id, &uid);
    if (!(h = flux_open (NULL, 0)))
        fatal ("could not contact Flux broker");
    if (!(f_R = lookup_R (h, id)))
        fatal ("error sending job-info.lookup request");
    if (!(f_eventlog = flux_job_event_watch (h, id, "eventlog", 0)))
        fatal ("error sending eventlog watch request");
    if (eventlog_wait_for (f_eventlog, "cray-slingshot", eventlog_timeout, &res, &error) < 0)
        fatal ("waiting for cray-slingshot event: %s", error.text);
    if (!res) {
        if (optparse_hasopt (p, "dry-run"))
            warn ("no cray-slingshot reservation was found");
        goto done;
    }
    if (!(vnis = parse_reservation_vnis (res)))
        fatal ("error parsing cray-slingshot reservation");
    if (json_array_size (vnis) == 0)
        goto done;
    ncores = ncores_from_R (f_R);
#if HAVE_CXI
    allocate_cxi_service (p, uid, vnis, ncores);
#else
    char *s = json_dumps (vnis, JSON_COMPACT);
    warn ("no CXI support uid=%u ncores=%d vnis=%s", uid, ncores, s ? s : "");
    free (s);
#endif
    json_decref (res);
done:
    flux_future_destroy (f_eventlog);
    flux_future_destroy (f_R);
    flux_close (h);
    return 0;
}

static int cmd_epilog (optparse_t *p, int argc, char **argv)
{
    int optindex = optparse_option_index (p);
    flux_jobid_t id;
    uid_t uid;
    flux_t *h;
    json_t *res;
    json_t *vnis;
    double timeout = -1;
    struct timespec t0;
    int busycount = 0;

    if (optindex < argc)
        fatal ("free arguments are not supported");
    parse_job_info (p, &id, &uid);
    if (optparse_hasopt (p, "retry-busy")) {
        const char *arg = optparse_get_str (p, "retry-busy", NULL);
        if (fsd_parse_duration (arg, &timeout) < 0)
            fatal ("invalid --retry-busy FSD");
    }
    if (!(h = flux_open (NULL, 0)))
        fatal ("could not contact Flux broker");
    if (!(res = lookup_reservation (h, id))) {
        if (optparse_hasopt (p, "dry-run"))
            warn ("no cray-slingshot reservation was found");
        goto done;
    }
    if (!(vnis = parse_reservation_vnis (res)))
        fatal ("error parsing cray-slingshot reservation");
    if (json_array_size (vnis) == 0) {
        json_decref (res);
        goto done;
    }
    monotime (&t0);
    do {
        if (busycount > 0)
            sleep (1);
#if HAVE_CXI
        struct res_match_info match = {.uid = uid, .vnis = vnis};
        busycount = destroy_cxi_service (p, false, match_reservation, &match);
#endif
    } while (busycount > 0 && timeout > 0 && monotime_since (t0) < timeout * 1E3);
    json_decref (res);
done:
    flux_close (h);
    if (busycount > 0 && timeout > 0)
        return 1;
    return 0;
}

static struct idset *lookup_vnipool (flux_t *h)
{
    flux_future_t *f;
    json_t *config;
    const char *vnipool;
    struct idset *ids = NULL;

    if (!(f = flux_rpc (h, "config.get", NULL, FLUX_NODEID_ANY, 0))
        || flux_rpc_get_unpack (f, "o", &config) < 0)
        fatal ("Error fetching config object: %s", future_strerror (f, errno));
    if (json_unpack (config, "{s:{s:s}}", "cray-slingshot", "vni-pool", &vnipool) == 0) {
        if (!(ids = idset_decode (vnipool)))
            fatal ("error decoding cray-slingshot.vni-pool config");
    }
    flux_future_destroy (f);
    return ids;
}

static int cmd_clean (optparse_t *p, int argc, char **argv)
{
    int optindex = optparse_option_index (p);
    double timeout = -1;
    struct timespec t0;
    flux_t *h;
    int busycount = 0;
    struct idset *vnipool;

    if (optindex < argc)
        fatal ("free arguments are not supported");
    if (optparse_hasopt (p, "retry-busy")) {
        const char *arg = optparse_get_str (p, "retry-busy", NULL);
        if (fsd_parse_duration (arg, &timeout) < 0)
            fatal ("invalid --timeout FSD");
    }
    if (!(h = flux_open (NULL, 0)))
        fatal ("could not contact Flux broker");
    if (!(vnipool = lookup_vnipool (h)))
        return 0;
    monotime (&t0);
    do {
        if (busycount > 0)
            sleep (1);
#if HAVE_CXI
        busycount = destroy_cxi_service (p, true, (svc_match_f)match_vnipool, vnipool);
#endif
    } while (busycount > 0 && timeout > 0 && monotime_since (t0) < timeout * 1E3);
    idset_destroy (vnipool);
    flux_close (h);
    if (busycount > 0 && timeout > 0)
        return 1;
    return 0;
}

#if HAVE_CXI
static void count_services (int dev_id, int *def, int *sys, int *usr)
{
    int e;
    struct cxil_dev *dev;
    struct cxil_svc_list *svc_list;

    if ((e = cxil_open_device (dev_id, &dev)) < 0) {
        warn ("cxi%u: cxil_open_device: %s", dev_id, strerror (-e));
        return;
    }
    if ((e = cxil_get_svc_list (dev, &svc_list)) < 0) {
        warn ("cxi%u: cxil_get_svc_list", dev_id, strerror (-e));
        goto done;
    }
    for (int i = 0; i < svc_list->count; i++) {
        struct cxi_svc_desc *desc = &svc_list->descs[i];

        if (desc->enable) {
            if (desc->svc_id == CXI_DEFAULT_SVC_ID)
                (*def)++;
            else if (desc->is_system_svc)
                (*sys)++;
            else
                (*usr)++;
        }
    }
    cxil_free_svc_list (svc_list);
done:
    cxil_close_device (dev);
}
#endif

static int cmd_list (optparse_t *p, int argc, char **argv)
{
    int optindex = optparse_option_index (p);
    if (optindex < argc)
        fatal ("free arguments are not supported");
    if (!optparse_hasopt (p, "no-header")) {
        printf ("%-5s %-8s %-8s %-8s %-8s\n", "Name", "Status", "Default", "System", "User");
    }
#if HAVE_CXI
    struct cxil_device_list *dev_list;
    int e;

    if ((e = cxil_get_device_list (&dev_list)) < 0)
        fatal ("cxil_get_device_list: %s", strerror (-e));
    for (int i = 0; i < dev_list->count; i++) {
        int def = 0;
        int sys = 0;
        int usr = 0;

        count_services (dev_list->info[i].dev_id, &def, &sys, &usr);

        printf ("%-5s %-8s %-8d %-8d %-8d\n",
                dev_list->info[i].device_name,
                cxil_rh_running (&dev_list->info[i]) ? "up" : "down",
                def,
                sys,
                usr);
    }
    cxil_free_device_list (dev_list);
#endif
    return 0;
}

static int cmd_jobinfo (optparse_t *p, int argc, char **argv)
{
    int optindex = optparse_option_index (p);
    flux_jobid_t id;
    flux_t *h;
    json_t *res;

    if (optindex < argc)
        fatal ("free arguments are not supported");
    parse_job_info (p, &id, NULL);
    if (!(h = flux_open (NULL, 0)))
        fatal ("could not contact Flux broker");
    res = lookup_reservation (h, id);
    if (!res)
        fatal ("no reservation found for %s", idf58 (id));

    char *s = json_dumps (res, JSON_COMPACT);
    if (!s)
        fatal ("error printing reservation");
    printf ("%s\n", s);
    free (s);

    json_decref (res);
    flux_close (h);
    return 0;
}

static int usage (optparse_t *p, struct optparse_option *o, const char *optarg)
{
    struct optparse_subcommand *s;
    optparse_print_usage (p);
    fprintf (stderr, "\n");
    fprintf (stderr, "Common commands for flux-slingshot:\n");
    s = subcommands;
    while (s->name) {
        if (!(s->flags & OPTPARSE_OPT_HIDDEN))
            fprintf (stderr, "   %-15s %s\n", s->name, s->doc);
        s++;
    }
    exit (1);
}

int main (int argc, char *argv[])
{
    optparse_t *p;
    int optindex;
    int exitval;

    if (!(p = optparse_create ("flux-slingshot"))
        || optparse_reg_subcommands (p, subcommands) != OPTPARSE_SUCCESS
        || optparse_set (p, OPTPARSE_OPTION_CB, "help", usage) != OPTPARSE_SUCCESS)
        fatal ("error setting up option parsing");
    if ((optindex = optparse_parse_args (p, argc, argv)) < 0)
        exit (1);
    if ((argc - optindex == 0) || !optparse_get_subcommand (p, argv[optindex])
        || (exitval = optparse_run_subcommand (p, argc, argv)) < 0) {
        usage (p, NULL, NULL);
        exit (1);
    }
    optparse_destroy (p);

    return exitval;
}

// vi:ts=4 sw=4 expandtab
