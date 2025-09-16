/************************************************************\
 * Copyright 2025 Lawrence Livermore National Security, LLC
 * (c.f. AUTHORS, NOTICE.LLNS, COPYING)
 *
 * This file is part of the Flux resource manager framework.
 * For details, see https://github.com/flux-framework.
 *
 * SPDX-License-Identifier: LGPL-3.0
\************************************************************/

#ifndef _VNIPOOL_H
#define _VNIPOOL_H

#include <sys/types.h>
#include <stdint.h>
#include <jansson.h>
#include <flux/core.h>

#define VNIPOOL_DEFAULT "1024-65535"

struct vnipool *vnipool_create (void);
void vnipool_destroy (struct vnipool *vp);

/* Configure the VNI pool.
 * This function may be called repeatedly as the pool config changes.
 */
int vnipool_configure (struct vnipool *vp, const char *vni_pool, flux_error_t *error);

/* Allocate VNIs and return them in a json array.
 * The reservation should be released by job id.
 */
json_t *vnipool_reserve (struct vnipool *vp, flux_jobid_t id, int vni_count, flux_error_t *error);

/* Remove a job reservation and free its VNIs
 */
int vnipool_release (struct vnipool *vp, flux_jobid_t id, flux_error_t *error);

/* Find a job reservation.
 */
json_t *vnipool_lookup (struct vnipool *vp, flux_jobid_t id, flux_error_t *error);

/* Hook for debugging.
 * The caller must free the returned JSON object.
 */
json_t *vnipool_query (struct vnipool *vp);

#endif /* !_VNIPOOL_H */

// vi:ts=4 sw=4 expandtab
