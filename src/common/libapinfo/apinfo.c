/************************************************************\
 * Copyright 2025 Lawrence Livermore National Security, LLC
 * (c.f. AUTHORS, NOTICE.LLNS, COPYING)
 *
 * This file is part of the Flux resource manager framework.
 * For details, see https://github.com/flux-framework.
 *
 * SPDX-License-Identifier: LGPL-3.0
\************************************************************/

#if HAVE_CONFIG_H
#include "config.h"
#endif
#include <stdlib.h>
#include <errno.h>
#include <stdio.h>
#include <flux/core.h>
#include <flux/taskmap.h>
#include <flux/hostlist.h>

#include "src/common/libutil/errprintf.h"

#include "apinfo.h"
#include "apimpl.h"

extern struct apinfo_impl apinfo1;
extern struct apinfo_impl apinfo5;

static struct apinfo_impl *itab[] = {
    &apinfo1,
    &apinfo5,
};

struct apinfo {
    struct apinfo_impl *impl;
    void *handle;
};

static struct apinfo_impl *lookup_impl (int version)
{
    for (int i = 0; i < sizeof (itab) / sizeof (itab[0]); i++) {
        if (itab[i]->version == version)
            return itab[i];
    }
    errno = ENOENT;
    return NULL;
}

struct apinfo *apinfo_create (int version)
{
    struct apinfo *ap;

    if (!(ap = calloc (1, sizeof (*ap))))
        return NULL;
    if (!(ap->impl = lookup_impl (version)))
        goto error;
    if (!(ap->handle = ap->impl->create ()))
        goto error;
    return ap;
error:
    apinfo_destroy (ap);
    return NULL;
}

void apinfo_destroy (struct apinfo *ap)
{
    if (ap) {
        int saved_errno = errno;
        if (ap->impl)
            ap->impl->destroy (ap->handle);
        free (ap);
        errno = saved_errno;
    }
}

int apinfo_write (struct apinfo *ap, FILE *stream)
{
    if (!ap || !stream) {
        errno = EINVAL;
        return -1;
    }
    return ap->impl->write (ap->handle, stream);
}

int apinfo_put (struct apinfo *ap, const char *path)
{
    FILE *stream;
    if (!ap || !path) {
        errno = EINVAL;
        return -1;
    }
    if (!(stream = fopen (path, "w+")))
        return -1;
    if (apinfo_write (ap, stream) < 0) {
        int saved_errno = errno;
        (void)fclose (stream);
        errno = saved_errno;
        return -1;
    }
    if (fclose (stream) != 0)
        return -1;
    return 0;
}

int apinfo_set_hostlist (struct apinfo *ap, const struct hostlist *hosts)
{
    if (!ap || !hosts) {
        errno = EINVAL;
        return -1;
    }
    return ap->impl->set_hostlist (ap->handle, hosts);
}

int apinfo_set_taskmap (struct apinfo *ap, const struct taskmap *map, int cpus_per_pe)
{
    if (!ap || !map) {
        errno = EINVAL;
        return -1;
    }
    return ap->impl->set_taskmap (ap->handle, map, cpus_per_pe);
}

int apinfo_check (struct apinfo *ap, flux_error_t *error)
{
    if (!ap) {
        errprintf (error, "invalid argument");
        errno = EINVAL;
        return -1;
    }
    return ap->impl->check (ap->handle, error);
}

size_t apinfo_get_size (struct apinfo *ap)
{
    if (!ap)
        return 0;
    return ap->impl->get_size (ap->handle);
}

int apinfo_get_nnodes (struct apinfo *ap)
{
    if (!ap)
        return 0;
    return ap->impl->get_nnodes (ap->handle);
}

int apinfo_get_npes (struct apinfo *ap)
{
    if (!ap)
        return 0;
    return ap->impl->get_npes (ap->handle);
}

const struct hostlist *apinfo_get_hostlist (struct apinfo *ap)
{
    if (!ap) {
        errno = EINVAL;
        return NULL;
    }
    return ap->impl->get_hostlist (ap->handle);
}

const struct taskmap *apinfo_get_taskmap (struct apinfo *ap)
{
    if (!ap) {
        errno = EINVAL;
        return NULL;
    }
    return ap->impl->get_taskmap (ap->handle);
}

// vi:ts=4 sw=4 expandtab
