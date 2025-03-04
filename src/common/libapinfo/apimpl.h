/************************************************************\
 * Copyright 2025 Lawrence Livermore National Security, LLC
 * (c.f. AUTHORS, NOTICE.LLNS, COPYING)
 *
 * This file is part of the Flux resource manager framework.
 * For details, see https://github.com/flux-framework.
 *
 * SPDX-License-Identifier: LGPL-3.0
\************************************************************/

#ifndef _LIBAPINFO_IMPL_H
#define _LIBAPINFO_IMPL_H

#include <stdio.h>
#include <flux/core.h>
#include <flux/hostlist.h>
#include <flux/taskmap.h>

struct apinfo_impl {
    int version;
    void *(*create) (void);
    void (*destroy) (void *impl);
    int (*write) (void *impl, FILE *stream);
    int (*set_taskmap) (void *impl, const struct taskmap *map, int cpus_per_pe);
    int (*set_hostlist) (void *impl, const struct hostlist *hosts);
    int (*check) (void *impl, flux_error_t *error);
    size_t (*get_size) (void *impl);
    int (*get_nnodes) (void *impl);
    int (*get_npes) (void *impl);
    const struct hostlist *(*get_hostlist) (void *impl);
    const struct taskmap *(*get_taskmap) (void *impl);
};

#endif  // !_LIBAPINFO_IMPL_H

// vi:ts=4 sw=4 expandtab
