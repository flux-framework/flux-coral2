/************************************************************\
 * Copyright 2025 Lawrence Livermore National Security, LLC
 * (c.f. AUTHORS, NOTICE.LLNS, COPYING)
 *
 * This file is part of the Flux resource manager framework.
 * For details, see https://github.com/flux-framework.
 *
 * SPDX-License-Identifier: LGPL-3.0
\************************************************************/

/* vnipool.c - VNI reservation system
 */

#if HAVE_CONFIG_H
#include "config.h"
#endif
#include <flux/idset.h>
#include <flux/core.h>
#ifdef HAVE_LIBCXI_LIBCXI_H
#include <libcxi/libcxi.h>
#endif
#ifndef CXI_SVC_MAX_VNIS
#define CXI_SVC_MAX_VNIS 4
#endif

#include "src/common/libutil/errprintf.h"
#include "src/common/libutil/idf58.h"

#include "vnipool.h"

// 16-bit unsigned value, with 1,10 reserved for the default CXI service
#define VNI_VALID_SET "0,2-9,11-65535"

struct vnipool {
    struct idset *universe;  // the configured valid VNIs
    struct idset *pool;      // the unallocated VNIs
    json_t *jobs;            // jobid.f58 => reservation object
};

json_t *vnipool_query (struct vnipool *vp)
{
    json_t *o = json_null ();
    if (vp) {
        char *universe = idset_encode (vp->universe, IDSET_FLAG_RANGE);
        char *pool = idset_encode (vp->pool, IDSET_FLAG_RANGE);
        o = json_pack ("{s:s s:s s:O}",
                       "universe",
                       universe ? universe : "",
                       "free",
                       pool ? pool : "",
                       "jobs",
                       vp->jobs);
        free (pool);
        free (universe);
    }
    return o;
}

/* Return true if 'a' is a subset of 'b'.
 */
static bool is_subset_of (const struct idset *a, const struct idset *b)
{
    struct idset *u;

    if (!(u = idset_intersect (a, b)) || !idset_equal (u, a)) {
        idset_destroy (u);
        return false;
    }
    idset_destroy (u);
    return true;
}

/* Release VNIs back to the pool and free the JSON array containing them.
 * Careful not to put VNIs in the pool that are no longer in the config!
 */
static void vnipool_free_array (struct vnipool *vp, json_t *vnis)
{
    if (vnis) {
        size_t index;
        json_t *entry;

        json_array_foreach (vnis, index, entry) {
            int id = json_integer_value (entry);
            if (idset_test (vp->universe, id))
                idset_free (vp->pool, id);
        }
        json_decref (vnis);
    }
}

/* Allocate 'count' VNIs from the pool and return them in a JSON array.
 */
static json_t *vnipool_alloc_array (struct vnipool *vp, int count)
{
    json_t *vnis;

    if (!(vnis = json_array ()))
        return NULL;
    for (int i = 0; i < count; i++) {
        unsigned int vni;
        json_t *o;
        if (idset_alloc (vp->pool, &vni) < 0)
            goto error;
        if (!(o = json_integer (vni)) || json_array_append_new (vnis, o) < 0) {
            json_decref (o);
            idset_free (vp->pool, vni);
        }
    }
    return vnis;
error:
    vnipool_free_array (vp, vnis);
    json_decref (vnis);
    return NULL;
}

/* Allocated VNIs and create a reservation object for the specified job.
 */
json_t *vnipool_reserve (struct vnipool *vp, flux_jobid_t id, int vnicount, flux_error_t *error)
{
    const char *key = idf58 (id);
    json_t *vnis = NULL;

    if (vnicount < 0 || vnicount > CXI_SVC_MAX_VNIS) {
        errprintf (error, "VNI count must be within 1-%d", CXI_SVC_MAX_VNIS);
        errno = EINVAL;
        return NULL;
    }
    if (!(vnis = vnipool_alloc_array (vp, vnicount))) {
        errprintf (error,
                   "failed to reserve %d VNI%s (%zu available)",
                   vnicount,
                   vnicount > 1 ? "s" : "",
                   idset_count (vp->pool));
        errno = ENOSPC;
        return NULL;
    }
    if (json_object_set_new (vp->jobs, key, vnis) < 0) {
        errprintf (error, "out of memory saving VNI reservation");
        vnipool_free_array (vp, vnis);
        errno = ENOMEM;
        return NULL;
    }
    return vnis;
}

/* Release VNIs and remove the reservation object for the specified job.
 */
int vnipool_release (struct vnipool *vp, flux_jobid_t id, flux_error_t *error)
{
    const char *key = idf58 (id);
    json_t *vnis;

    if (!(vnis = vnipool_lookup (vp, id, error)))
        return -1;
    vnipool_free_array (vp, json_incref (vnis));
    (void)json_object_del (vp->jobs, key);
    return 0;
}

/* Find a reservation for the specified job.
 */
json_t *vnipool_lookup (struct vnipool *vp, flux_jobid_t id, flux_error_t *error)
{
    const char *key = idf58 (id);
    json_t *job;

    if (!(job = json_object_get (vp->jobs, key))) {
        errprintf (error, "unknown job %s", key);
        errno = ENOENT;
        return NULL;
    }
    return job;
}

/* Decode a vni-pool configuration value to an idset.
 * All the VNIs must be in the 'valid' set.
 */
static struct idset *decode_vnipool (const char *s, const char *valid, flux_error_t *error)
{
    struct idset *ids;
    struct idset *valid_ids = NULL;
    idset_error_t err;

    if (!(ids = idset_decode_ex (s, -1, -1, 0, &err))) {
        errprintf (error, "decode error: %s", err.text);
        goto inval;
    }
    if (!(valid_ids = idset_decode_ex (valid, -1, -1, 0, &err))) {
        errprintf (error, "internal error decoding %s: %s", valid, err.text);
        goto inval;
    }
    if (!is_subset_of (ids, valid_ids)) {
        errprintf (error, "%s contains invalid VNIs, must be a subset of %s", s, valid);
        goto inval;
    }
    idset_destroy (valid_ids);
    return ids;
inval:
    errno = EINVAL;
    idset_destroy (valid_ids);
    idset_destroy (ids);
    return NULL;
}

/* Create a new vni pool idset suitable for idset_alloc(3).
 * Populate the pool with the IDs in 'new_universe', minus those
 * that are already allocated.
 */
static struct idset *create_vnipool (const struct idset *new_universe,
                                     const struct idset *old_universe,
                                     const struct idset *old_pool)
{
    size_t pool_size = idset_universe_size (new_universe);
    struct idset *pool;

    // N.B. IDSET_FLAG_ALLOC_RR was added in flux-core 0.76
    if (!(pool = idset_create (pool_size, IDSET_FLAG_INITFULL | IDSET_FLAG_ALLOC_RR)))
        goto error;
    for (unsigned int id = 0; id < pool_size; id++) {
        if (!idset_test (new_universe, id)
            || (idset_test (old_universe, id) && !idset_test (old_pool, id)))
            if (idset_clear (pool, id) < 0)
                goto error;
    }
    return pool;
error:
    idset_destroy (pool);
    return NULL;
}

/* (Re-)configure the VNI pool.
 * Existing VNI reservations that are inside the new range are preserved.
 * Those that are now out of range are not preserved (though their vni->jobs
 * entries may persist).
 */
int vnipool_configure (struct vnipool *vp, const char *vni_pool, flux_error_t *error)
{
    struct idset *new_universe = NULL;
    struct idset *new_pool = NULL;

    if (!(new_universe = decode_vnipool (vni_pool, VNI_VALID_SET, error)))
        return -1;
    /* Same as the old universe?  Do nothing.
     */
    if (idset_equal (new_universe, vp->universe)) {
        idset_destroy (new_universe);
        return 0;
    }
    if (!(new_pool = create_vnipool (new_universe, vp->universe, vp->pool))) {
        errprintf (error, "error creating new vni pool: %s", strerror (errno));
        idset_destroy (new_universe);
        return -1;
    }
    idset_destroy (vp->universe);
    idset_destroy (vp->pool);
    vp->universe = new_universe;
    vp->pool = new_pool;
    return 0;
}

void vnipool_destroy (struct vnipool *vp)
{
    if (vp) {
        int saved_errno = errno;
        idset_destroy (vp->universe);
        idset_destroy (vp->pool);
        json_decref (vp->jobs);
        free (vp);
        errno = saved_errno;
    }
}

struct vnipool *vnipool_create (void)
{
    struct vnipool *vp;

    if (!(vp = calloc (1, sizeof (*vp))))
        return NULL;
    if (!(vp->jobs = json_object ())) {
        errno = ENOMEM;
        goto error;
    }
    return vp;
error:
    vnipool_destroy (vp);
    return NULL;
}

// vi:ts=4 sw=4 expandtab
