/************************************************************\
 * Copyright 2025 Lawrence Livermore National Security, LLC
 * (c.f. AUTHORS, NOTICE.LLNS, COPYING)
 *
 * This file is part of the Flux resource manager framework.
 * For details, see https://github.com/flux-framework.
 *
 * SPDX-License-Identifier: LGPL-3.0
\************************************************************/

#ifndef _LIBAPINFO_APINFO_H
#define _LIBAPINFO_APINFO_H

#include <flux/core.h>
#include <flux/hostlist.h>
#include <flux/taskmap.h>
#include <stdio.h>

/* Create/destroy an apinfo object of the specified version.
 * All its sections are initially empty.
 */
struct apinfo *apinfo_create (int version);
void apinfo_destroy (struct apinfo *ap);

/* Write the apinfo object to a file/stream.
 */
int apinfo_write (struct apinfo *ap, FILE *stream);
int apinfo_put (struct apinfo *ap, const char *path);

/* Populate the nodes section with the specified hostlist,
 * which must be in nodeid order.
 */
int apinfo_set_hostlist (struct apinfo *ap, const struct hostlist *hosts);

/* Populate the cmd and pes sections using the specified taskmap.
 * There is no MPMD support at this point so there is always one cmd element
 * that is assigned to all PEs.
 *
 * cmd.cpus_per_pe is set to the value provided here.  What is this used for? -jg
 */
int apinfo_set_taskmap (struct apinfo *ap, const struct taskmap *map, int cpus_per_pe);

/* Check the apinfo object for consistency.
 */
int apinfo_check (struct apinfo *ap, flux_error_t *error);

/* The following accessors are intended for testing.
 */
size_t apinfo_get_size (struct apinfo *ap);
int apinfo_get_npes (struct apinfo *ap);
int apinfo_get_nnodes (struct apinfo *ap);
const struct hostlist *apinfo_get_hostlist (struct apinfo *ap);
const struct taskmap *apinfo_get_taskmap (struct apinfo *ap);

#endif  // !_LIBAPINFO_APINFO_H

// vi:ts=4 sw=4 expandtab
