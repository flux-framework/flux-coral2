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
#include <string.h>
#include <flux/hostlist.h>
#include <flux/idset.h>
#include <flux/taskmap.h>

#include "src/common/libutil/errprintf.h"

#include "apinfo5.h"
#include "apimpl.h"

struct apinfo5 {
    pals_header_t hdr;
    pals_comm_profile_t *comms;
    pals_cmd_t *cmds;
    pals_pe_t *pes;
    pals_node_t *nodes;
    pals_hsn_nic_t *nics;
    pals_distance_t *dist;
    int *status;

    // missing from pals_header_t
    int ndist;
    int nstatus;
    size_t status_size;

    struct hostlist *hosts;  // cache for op_get_hostlist()
    struct taskmap *map;     // cache for op_get_taskmap()
};

/* Assign section offsets after section element counts have been updated.
 */
static void set_offsets (struct apinfo5 *ap)
{
    pals_header_t *hdr = &ap->hdr;
    size_t offset = sizeof (*hdr);

    hdr->comm_profile_offset = offset;
    offset += hdr->comm_profile_size * hdr->ncomm_profiles;
    hdr->cmd_offset = offset;
    offset += hdr->cmd_size * hdr->ncmds;
    hdr->pe_offset = offset;
    offset += hdr->pe_size * hdr->npes;
    hdr->node_offset = offset;
    offset += hdr->node_size * hdr->nnodes;
    hdr->nic_offset = offset;
    offset += hdr->nic_size * hdr->nnics;

    /* Breaking from the pattern above:
     - pals_header_t does not contain "ndist", so set dist_offset=0 if unused
     - pals_header_t does not contain "nstatus", so set status_offset=0 if unused.
     * pals_header_t does not contain "status_size"
     */
    hdr->dist_offset = ap->ndist > 0 ? offset : 0;
    offset += hdr->dist_size * ap->ndist;
    hdr->status_offset = ap->nstatus > 0 ? offset : 0;
    offset += ap->status_size * ap->nstatus;

    hdr->total_size = offset;
}

/* Assign section element sizes.
 */
static void set_sizes (struct apinfo5 *ap)
{
    pals_header_t *hdr = &ap->hdr;

    hdr->comm_profile_size = sizeof (ap->comms[0]);
    hdr->cmd_size = sizeof (ap->cmds[0]);
    hdr->pe_size = sizeof (ap->pes[0]);
    hdr->node_size = sizeof (ap->nodes[0]);
    hdr->nic_size = sizeof (ap->nics[0]);
    hdr->dist_size = sizeof (ap->dist[0]);
    ap->status_size = sizeof (ap->status[0]);
}

/* Write the entire apinfo object to the specified stream.
 */
static int op_write (void *handle, FILE *stream)
{
    struct apinfo5 *ap = handle;

    if (fwrite (&ap->hdr, sizeof (ap->hdr), 1, stream) != 1)
        return -1;
    if (fwrite (ap->comms, ap->hdr.comm_profile_size, ap->hdr.ncomm_profiles, stream)
        != ap->hdr.ncomm_profiles)
        return -1;
    if (fwrite (ap->cmds, ap->hdr.cmd_size, ap->hdr.ncmds, stream) != ap->hdr.ncmds)
        return -1;
    if (fwrite (ap->pes, ap->hdr.pe_size, ap->hdr.npes, stream) != ap->hdr.npes)
        return -1;
    if (fwrite (ap->nodes, ap->hdr.node_size, ap->hdr.nnodes, stream) != ap->hdr.nnodes)
        return -1;
    if (fwrite (ap->nics, ap->hdr.nic_size, ap->hdr.nnics, stream) != ap->hdr.nnics)
        return -1;
    if (fwrite (ap->dist, ap->hdr.dist_size, ap->ndist, stream) != ap->ndist)
        return -1;
    if (fwrite (ap->status, ap->status_size, ap->nstatus, stream) != ap->nstatus)
        return -1;

    return 0;
}

/* Find the maximum number of tasks per node.
 * Helper for set_cmd()
 */
static int max_ntasks (const struct taskmap *map)
{
    int max_ntasks = 0;

    for (int nodeid = 0; nodeid < taskmap_nnodes (map); nodeid++) {
        int ntasks = taskmap_ntasks (map, nodeid);

        if (max_ntasks < ntasks)
            max_ntasks = ntasks;
    }

    return max_ntasks;
}

/* For now, no MPMD support - just one cmd element.
 */
static int set_cmd (struct apinfo5 *ap, const struct taskmap *map, int cpus_per_pe)
{
    int ncmds = 1;
    pals_cmd_t *cmds;

    if (!(cmds = calloc (ncmds, sizeof (*cmds))))
        return -1;

    cmds[0].npes = taskmap_total_ntasks (map);
    cmds[0].pes_per_node = max_ntasks (map);
    cmds[0].cpus_per_pe = cpus_per_pe;

    free (ap->cmds);
    ap->cmds = cmds;
    ap->hdr.ncmds = ncmds;
    set_offsets (ap);

    return 0;
}

/* Given a global taskid and a nodeid, find the task's localidx.
 * Helper for set_pes().
 */
static int localidx (const struct taskmap *map, int nodeid, int taskid)
{
    const struct idset *ids;
    unsigned int id;
    int localidx = 0;

    if (!(ids = taskmap_taskids (map, nodeid)))
        return -1;

    id = idset_first (ids);
    while (id != IDSET_INVALID_ID) {
        if (id == taskid)
            return localidx;
        localidx++;
        id = idset_next (ids, id);
    }

    return -1;
}

static int set_pes (struct apinfo5 *ap, const struct taskmap *map)
{
    int npes = taskmap_total_ntasks (map);
    pals_pe_t *pes;

    if (!(pes = calloc (npes, sizeof (*pes))))
        return -1;

    for (int taskid = 0; taskid < npes; taskid++) {
        int nodeid = taskmap_nodeid (map, taskid);
        pes[taskid].nodeidx = nodeid;
        pes[taskid].localidx = localidx (map, nodeid, taskid);
        pes[taskid].cmdidx = 0;
    }

    free (ap->pes);
    ap->pes = pes;
    ap->hdr.npes = npes;
    set_offsets (ap);

    return 0;
}

static int op_set_taskmap (void *handle, const struct taskmap *map, int cpus_per_pe)
{
    struct apinfo5 *ap = handle;

    if (set_pes (ap, map) < 0 || set_cmd (ap, map, cpus_per_pe) < 0)
        return -1;

    return 0;
}

static int op_set_hostlist (void *handle, const struct hostlist *hosts)
{
    struct apinfo5 *ap = handle;
    int nnodes = hostlist_count ((struct hostlist *)hosts);
    pals_node_t *nodes;

    if (!(nodes = calloc (nnodes, sizeof (*nodes))))
        return -1;

    for (int nodeid = 0; nodeid < nnodes; nodeid++) {
        const char *host = hostlist_nth ((struct hostlist *)hosts, nodeid);
        snprintf (nodes[nodeid].hostname, sizeof (nodes[nodeid].hostname), "%s", host);
        nodes[nodeid].nid = nodeid;
    }
    free (ap->nodes);
    ap->nodes = nodes;
    ap->hdr.nnodes = nnodes;
    set_offsets (ap);

    return 0;
}

static int op_check (void *handle, flux_error_t *error)
{
    struct apinfo5 *ap = handle;

    // check that the all nodeidx referenced from pes are valid
    for (int taskid = 0; taskid < ap->hdr.npes; taskid++) {
        if (ap->pes[taskid].nodeidx >= ap->hdr.nnodes) {
            errprintf (error, "pes[%d].nodeidx >= nnodes (%d)", taskid, ap->hdr.nnodes);
            goto error;
        }
    }

    // check that all nodes have a PE reference
    for (int nodeid = 0; nodeid < ap->hdr.nnodes; nodeid++) {
        bool found = false;
        for (int taskid = 0; taskid < ap->hdr.npes; taskid++) {
            if (ap->pes[taskid].nodeidx == ap->nodes[nodeid].nid) {
                found = true;
                break;
            }
        }
        if (!found) {
            errprintf (error,
                       "no PE references nodeid %d (%s)",
                       ap->nodes[nodeid].nid,
                       ap->nodes[nodeid].hostname);
            goto error;
        }
    }
    return 0;
error:
    errno = EINVAL;
    return -1;
}

static size_t op_get_size (void *handle)
{
    struct apinfo5 *ap = handle;
    return ap->hdr.total_size;
}

static int op_get_nnodes (void *handle)
{
    struct apinfo5 *ap = handle;
    return ap->hdr.nnodes;
}

static int op_get_npes (void *handle)
{
    struct apinfo5 *ap = handle;
    return ap->hdr.npes;
}

static const struct hostlist *op_get_hostlist (void *handle)
{
    struct apinfo5 *ap = handle;
    struct hostlist *hosts;

    if (!(hosts = hostlist_create ()))
        return NULL;
    for (int nodeid = 0; nodeid < ap->hdr.nnodes; nodeid++) {
        if (hostlist_append (hosts, ap->nodes[nodeid].hostname) < 0) {
            hostlist_destroy (hosts);
            return NULL;
        }
    }
    hostlist_destroy (ap->hosts);
    ap->hosts = hosts;
    return ap->hosts;
}

// see note in apinfo1.c
static const struct taskmap *op_get_taskmap (void *handle)
{
    struct apinfo5 *ap = handle;
    struct taskmap *map;

    if (!(map = taskmap_create ()))
        return NULL;
    for (int taskid = 0; taskid < ap->hdr.npes; taskid++) {
        if (taskmap_append (map, ap->pes[taskid].nodeidx, 1, 1) < 0) {
            taskmap_destroy (map);
            return NULL;
        }
    }
    taskmap_destroy (ap->map);
    ap->map = map;
    return ap->map;
}

static void *op_create (void)
{
    struct apinfo5 *ap;

    if (!(ap = calloc (1, sizeof (*ap))))
        return NULL;

    ap->hdr.version = PALS_APINFO_VERSION;
    set_sizes (ap);
    set_offsets (ap);

    return ap;
}

static void op_destroy (void *handle)
{
    struct apinfo5 *ap = handle;

    if (ap) {
        int saved_errno = errno;
        taskmap_destroy (ap->map);
        hostlist_destroy (ap->hosts);
        free (ap->comms);
        free (ap->cmds);
        free (ap->pes);
        free (ap->nodes);
        free (ap->nics);
        free (ap->status);
        free (ap);
        errno = saved_errno;
    }
}

struct apinfo_impl apinfo5 = {
    .version = PALS_APINFO_VERSION,
    .create = op_create,
    .destroy = op_destroy,
    .write = op_write,
    .set_hostlist = op_set_hostlist,
    .set_taskmap = op_set_taskmap,
    .check = op_check,
    .get_size = op_get_size,
    .get_nnodes = op_get_nnodes,
    .get_npes = op_get_npes,
    .get_hostlist = op_get_hostlist,
    .get_taskmap = op_get_taskmap,
};

// vi:ts=4 sw=4 expandtab
