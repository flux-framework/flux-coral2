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
#include <errno.h>
#include <unistd.h>
#include <flux/taskmap.h>
#include <flux/hostlist.h>
#include <pals.h>

#include "tap.h"

#include "apinfo.h"

void empty_apinfo1 (char *path)
{
    struct apinfo *ap;
    pals_rc_t rc;
    pals_state_t *state;

    if (!(ap = apinfo_create (1)))
        BAIL_OUT ("apinfo_create version=1 failed");
    if (apinfo_put (ap, path) < 0)
        BAIL_OUT ("apinfo_put path=simple failed");
    apinfo_destroy (ap);
    diag ("created %s: empty", path);

    rc = pals_init2 (&state);
    ok (rc == PALS_OK, "pals_init2 is OK");

    int nodeidx = -1;
    rc = pals_get_nodeidx (state, &nodeidx);
    ok (rc == PALS_OK && nodeidx == 0, "pals_get_nodeidx is OK and returned 0");

    int peidx = -1;
    rc = pals_get_peidx (state, &peidx);
    ok (rc == PALS_OK && peidx == 0, "pals_get_peidx is OK and returned 0");

    int nnodes = -1;
    rc = pals_get_num_nodes (state, &nnodes);
    ok (rc == PALS_OK && nnodes == 0, "pals_get_nnodes is OK and returned 0");

    int ncmds = -1;
    rc = pals_get_num_cmds (state, &ncmds);
    ok (rc == PALS_OK && ncmds == 0, "pals_get_num_cmds is OK and returned 0");

    int npes = -1;
    rc = pals_get_num_pes (state, &npes);
    ok (rc == PALS_OK && npes == 0, "pals_get_num_pes is OK and returned 0");

    int ncomm_profiles = -1;
    rc = pals_get_num_comm_profiles (state, &ncomm_profiles);
    ok (rc == PALS_OK && ncomm_profiles == 0, "pals_get_num_comm_profiles is OK and returned 0");

    int nnics = -1;
    rc = pals_get_num_nics (state, &nnics);
    ok (rc == PALS_OK && nnics == 0, "pals_get_num_nics is OK and returned 0");

    nnics = -1;
    rc = pals_get_num_hsn_nics (state, &nnics);
    ok (rc == PALS_OK && nnics == 0, "pals_get_num_hsn_nics is OK and returned 0");

    rc = pals_fini (state);
    ok (rc == PALS_OK, "pals_fini is OK");
}

void simple_apinfo1 (char *path)
{
    struct apinfo *ap;
    pals_rc_t rc;
    pals_state_t *state;
    struct hostlist *hosts;
    struct taskmap *map;

    if (!(ap = apinfo_create (1)))
        BAIL_OUT ("apinfo_create version=1 failed");
    if (!(hosts = hostlist_decode ("test[0-3]")) || apinfo_set_hostlist (ap, hosts) < 0)
        BAIL_OUT ("error setting hostlist");
    if (!(map = taskmap_decode ("[[0,4,256,1]]", NULL)) || apinfo_set_taskmap (ap, map, 1) < 0)
        BAIL_OUT ("error setting taskmap");
    if (apinfo_put (ap, path) < 0)
        BAIL_OUT ("apinfo_put path=simple failed");
    apinfo_destroy (ap);
    hostlist_destroy (hosts);
    taskmap_destroy (map);
    diag ("created %s: 4n1024p, block distribution", path);

    rc = pals_init2 (&state);
    ok (rc == PALS_OK, "pals_init2 is OK");

    int nodeidx = -1;
    rc = pals_get_nodeidx (state, &nodeidx);
    ok (rc == PALS_OK && nodeidx == 0, "pals_get_nodeidx is OK and returned 0");

    int peidx = -1;
    rc = pals_get_peidx (state, &peidx);
    ok (rc == PALS_OK && peidx == 0, "pals_get_peidx failed");

    int nnodes = -1;
    rc = pals_get_num_nodes (state, &nnodes);
    ok (rc == PALS_OK && nnodes == 4, "pals_get_nnodes is OK and returned 4");

    nnodes = -1;
    pals_node_t *nodes = NULL;
    rc = pals_get_nodes (state, &nodes, &nnodes);
    ok (rc == PALS_OK && nnodes == 4 && nodes != NULL && nodes[0].nid == 0
            && !strcmp (nodes[0].hostname, "test0") && nodes[1].nid == 1
            && !strcmp (nodes[1].hostname, "test1") && nodes[2].nid == 2
            && !strcmp (nodes[2].hostname, "test2") && nodes[3].nid == 3
            && !strcmp (nodes[3].hostname, "test3"),
        "pals_get_nodes is OK and returned expected content");

    int ncmds = -1;
    rc = pals_get_num_cmds (state, &ncmds);
    ok (rc == PALS_OK && ncmds == 1, "pals_get_num_cmds is OK and returned 1");

    ncmds = 0;
    pals_cmd_t *cmds = NULL;
    rc = pals_get_cmds (state, &cmds, &ncmds);
    ok (rc == PALS_OK && ncmds == 1 && cmds != NULL && cmds[0].npes == 1024
            && cmds[0].pes_per_node == 256 && cmds[0].cpus_per_pe == 1,
        "pals_get_cmds is OK and returned expected content");

    int npes = -1;
    rc = pals_get_num_pes (state, &npes);
    ok (rc == PALS_OK && npes == 1024, "pals_get_num_pes is OK and returned 1024");

    // just spot check this one
    npes = 0;
    pals_pe_t *pes = NULL;
    rc = pals_get_pes (state, &pes, &npes);
    ok (rc == PALS_OK && npes == 1024 && pes != NULL && pes[0].localidx == 0 && pes[0].cmdidx == 0
            && pes[0].nodeidx == 0 && pes[513].localidx == 1 && pes[513].cmdidx == 0
            && pes[513].nodeidx == 2 && pes[1023].localidx == 255 && pes[1023].cmdidx == 0
            && pes[1023].nodeidx == 3,
        "pals_get_pes is OK and returned expected content");

    int ncomm_profiles = -1;
    rc = pals_get_num_comm_profiles (state, &ncomm_profiles);
    ok (rc == PALS_OK && ncomm_profiles == 0, "pals_get_num_comm_profiles is OK and returned 0");

    int nnics = -1;
    rc = pals_get_num_nics (state, &nnics);
    ok (rc == PALS_OK && nnics == 0, "pals_get_num_nics is OK and returned 0");

    nnics = -1;
    rc = pals_get_num_hsn_nics (state, &nnics);
    ok (rc == PALS_OK && nnics == 0, "pals_get_num_hsn_nics is OK and returned 0");

    rc = pals_fini (state);
    ok (rc == PALS_OK, "pals_fini is OK");
}

int main (int argc, char *argv[])
{
    char path[1024] = "/tmp/apinfo.XXXXXX";

    plan (NO_PLAN);

    if (mkstemp (path) < 0)
        BAIL_OUT ("mkstemp failed");
    if (setenv ("PALS_APINFO", path, 1) < 0 || setenv ("PALS_RANKID", "0", 1) < 0
        || setenv ("PALS_NODEID", "0", 1) < 0)
        BAIL_OUT ("error setting PALS environment variables");

    empty_apinfo1 (path);
    simple_apinfo1 (path);

    unlink (path);

    done_testing ();
}

// vi:ts=4 sw=4 expandtab
