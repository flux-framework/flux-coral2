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
#include <sys/types.h>
#include <sys/stat.h>
#include <unistd.h>
#include <errno.h>
#include <unistd.h>
#include <flux/taskmap.h>
#include <flux/hostlist.h>

#include "tap.h"

#include "apinfo.h"

struct input {
    /* inputs */
    int cpus_per_pe;
    const char *hosts;
    const char *taskmap;
    /* expected outputs */
    int nnodes;
    int npes;
};

struct input good[] = {
    // RFC 34 taskmap test vectors */
    {1, "test0", "[[0,1,1,1]]", 1, 1},
    {1, "test[0-1]", "[[0,2,1,1]]", 2, 2},
    {1, "test0", "[[0,1,2,1]]", 1, 2},
    {1, "test[0-1]", "[[0,2,2,1]]", 2, 4},
    {1, "test[0-1]", "[[0,2,1,2]]", 2, 4},
    {1, "test[0-1]", "[[1,1,1,1],[0,1,1,1]]", 2, 2},
    {1, "test[0-3]", "[[0,4,4,1]]", 4, 16},
    {1, "test[0-3]", "[[0,4,1,4]]", 4, 16},
    {1, "test[0-3]", "[[0,4,2,2]]", 4, 16},
    {1, "test[0-5]", "[[0,4,2,1],[4,2,4,1]]", 6, 16},
    {1, "test[0-5]", "[[0,6,1,2],[4,2,1,2]]", 6, 16},
    {1, "test[0-5]", "[[5,1,4,1],[4,1,4,1],[3,1,2,1],[2,1,2,1],[1,1,2,1],[0,1,2,1]]", 6, 16},
    {1, "test[0-7]", "[[0,5,2,1],[6,1,2,1],[5,1,2,1],[7,1,2,1]]", 8, 16},
    {1, "test[0-3]", "[[3,1,4,1],[2,1,4,1],[1,1,4,1],[0,1,4,1]]", 4, 16},
};

bool equal_hostlists (struct hostlist *hosts1, struct hostlist *hosts2)
{
    const char *host1 = hostlist_first (hosts1);
    const char *host2 = hostlist_first (hosts2);
    while (host1 || host2) {
        if (!host1 || !host2 || strcmp (host1, host2) != 0)
            return false;
        host1 = hostlist_next (hosts1);
        host2 = hostlist_next (hosts2);
    }
    return true;
}

// see note in apinfo1.op_get_taskmap()
bool equal_taskmaps (const struct taskmap *map1, const struct taskmap *map2)
{
    char *m1 = taskmap_encode (map1, TASKMAP_ENCODE_RAW);
    char *m2 = taskmap_encode (map2, TASKMAP_ENCODE_RAW);
    if (!m1 || !m2 || strcmp (m1, m2) != 0) {
        return false;
    }
    return true;
}

int check (struct apinfo *ap, struct input *in, const char *path)
{
    struct hostlist *hosts = hostlist_decode (in->hosts);
    struct taskmap *map = taskmap_decode (in->taskmap, NULL);
    flux_error_t error;
    if (!hosts || !map)
        BAIL_OUT ("error decoding test input");
    if (apinfo_set_hostlist (ap, hosts) < 0)
        return -1;
    if (apinfo_set_taskmap (ap, map, in->cpus_per_pe) < 0)
        return -1;
    if (apinfo_get_nnodes (ap) != in->nnodes)
        return -1;
    if (apinfo_get_npes (ap) != in->npes)
        return -1;
    if (!equal_hostlists ((struct hostlist *)apinfo_get_hostlist (ap), hosts))
        return -1;
    if (!equal_taskmaps (apinfo_get_taskmap (ap), map))
        return -1;
    if (apinfo_check (ap, &error) < 0) {
        diag ("%s", error.text);
        return -1;
    }
    if (apinfo_put (ap, path) < 0)
        return -1;
    taskmap_destroy (map);
    hostlist_destroy (hosts);
    return 0;
}

void test_good (const char *path, int version)
{
    struct apinfo *ap;

    if (!(ap = apinfo_create (version)))
        BAIL_OUT ("apinfo_create failed");

    for (int i = 0; i < sizeof (good) / sizeof (good[0]); i++) {
        int rc = check (ap, &good[i], path);
        ok (rc == 0, "checked %s %s %d", good[i].hosts, good[i].taskmap, good[i].cpus_per_pe);
    }
    apinfo_destroy (ap);
}

void test_empty (const char *path, int version)
{
    struct apinfo *ap;
    struct stat sb;

    ok ((ap = apinfo_create (version)) != NULL, "apinfo_create version=%d works", version);

    ok (apinfo_check (ap, NULL) == 0, "apinfo_check says good!");

    ok (apinfo_put (ap, path) == 0, "apinfo_put works");

    ok (stat (path, &sb) == 0 && sb.st_size == apinfo_get_size (ap),
        "file size matches apinfo_get_size");

    apinfo_destroy (ap);
}

void test_check (const char *path, int version)
{
    struct apinfo *ap;
    struct hostlist *hosts;
    struct taskmap *map;
    flux_error_t error;

    if (!((ap = apinfo_create (version))))
        BAIL_OUT ("apinfo_create failed");
    if (!((map = taskmap_decode ("[[0,2,1,1]]", NULL))))
        BAIL_OUT ("taskmap_decode failed");
    if (!((hosts = hostlist_decode ("test[0-3]"))))
        BAIL_OUT ("taskmap_decode failed");
    if (apinfo_set_taskmap (ap, map, 1) < 0)
        BAIL_OUT ("apinfo_set_taskmap failed");

    errno = 0;
    error.text[0] = '\0';
    ok (apinfo_check (ap, &error) < 0 && errno == EINVAL,
        "apinfo_check finds pe referencing invalid nodeid");
    diag ("%s", error.text);

    if (apinfo_set_hostlist (ap, hosts) < 0)
        BAIL_OUT ("apinfo_set_hostlist failed");

    errno = 0;
    error.text[0] = '\0';
    ok (apinfo_check (ap, &error) < 0 && errno == EINVAL, "apinfo_check finds unreferenced nodeid");
    diag ("%s", error.text);

    apinfo_destroy (ap);
    taskmap_destroy (map);
    hostlist_destroy (hosts);
}

void test_inval (const char *path, int version)
{
    struct apinfo *ap;
    struct hostlist *hosts;
    struct taskmap *map;
    flux_error_t error;

    if (!((ap = apinfo_create (version))))
        BAIL_OUT ("apinfo_create failed");
    if (!((hosts = hostlist_decode ("test[0-1]"))))
        BAIL_OUT ("hostlist_decode failed");
    if (!((map = taskmap_decode ("[[0,2,1,1]]", NULL))))
        BAIL_OUT ("taskmap_decode failed");

    errno = 0;
    ok (apinfo_create (42) == NULL && errno == ENOENT,
        "apinfo_create version=42 fails with ENOENT");
    errno = 0;
    error.text[0] = '\0';
    ok (apinfo_check (NULL, &error) < 0 && errno == EINVAL,
        "apinfo_check ap=NULL fails with EINVAL");
    diag ("%s", error.text);
    errno = 0;
    ok (apinfo_write (NULL, stdout) < 0 && errno == EINVAL,
        "apinfo_write ap=NULL fails with EINVAL");
    errno = 0;
    ok (apinfo_write (ap, NULL) < 0 && errno == EINVAL,
        "apinfo_write stream=NULL fails with EINVAL");
    errno = 0;
    ok (apinfo_put (NULL, "foo") < 0 && errno == EINVAL, "apinfo_put ap=NULL fails with EINVAL");
    errno = 0;
    ok (apinfo_put (ap, NULL) < 0 && errno == EINVAL, "apinfo_put path=NULL fails with EINVAL");
    errno = 0;
    ok (apinfo_set_hostlist (ap, NULL) < 0 && errno == EINVAL,
        "apinfo_set_hostlist hosts=NULL fails with EINVAL");
    errno = 0;
    ok (apinfo_set_hostlist (NULL, hosts) < 0 && errno == EINVAL,
        "apinfo_set_hostlist ap=NULL fails with EINVAL");
    errno = 0;
    ok (apinfo_get_hostlist (NULL) == NULL && errno == EINVAL,
        "apinfo_get_hostlist ap=NULL fails with EINVAL");
    errno = 0;
    ok (apinfo_set_taskmap (NULL, map, 1) < 0 && errno == EINVAL,
        "apinfo_set_taskmap ap=NULL fails with EINVAL");
    errno = 0;
    ok (apinfo_set_taskmap (ap, NULL, 1) < 0 && errno == EINVAL,
        "apinfo_set_taskmap map=NULL fails with EINVAL");
    errno = 0;
    ok (apinfo_get_taskmap (NULL) == NULL && errno == EINVAL,
        "apinfo_get_taskmap map=NULL fails with EINVAL");

    lives_ok ({ apinfo_destroy (NULL); }, "apinfo_destroy NULL doesn't crash");

    hostlist_destroy (hosts);
    taskmap_destroy (map);
    apinfo_destroy (ap);
}

int main (int argc, char *argv[])
{
    char path[1024] = "/tmp/apinfo.XXXXXX";

    plan (NO_PLAN);

    if (mkstemp (path) < 0)
        BAIL_OUT ("mkstemp failed");

    diag ("testing APINFO v1");
    test_empty (path, 1);
    test_good (path, 1);
    test_check (path, 1);
    test_inval (path, 1);

    diag ("testing APINFO v5");
    test_empty (path, 5);
    test_good (path, 5);
    test_check (path, 5);
    test_inval (path, 5);

    unlink (path);

    done_testing ();
}

// vi:ts=4 sw=4 expandtab
