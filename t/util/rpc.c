/************************************************************\
 * Copyright 2019 Lawrence Livermore National Security, LLC
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
#include <unistd.h>
#include <getopt.h>
#include <stdio.h>
#include <flux/core.h>

#define OPTIONS "r"
static const struct option longopts[] = {
    {"raw", no_argument, 0, 'r'},
    {0, 0, 0, 0},
};

void usage (void)
{
    fprintf (stderr, "Usage: rpc [-r] topic [errnum] <payload >payload\n");
    exit (1);
}

int main (int argc, char *argv[])
{
    flux_t *h;
    flux_future_t *f;
    const char *topic;
    const char *result;
    int expected_errno = -1;
    int ch;
    bool raw = false;

    while ((ch = getopt_long (argc, argv, OPTIONS, longopts, NULL)) != -1) {
        switch (ch) {
            case 'r':
                raw = true;
                break;
            default:
                usage ();
        }
    }
    if (argc - optind != 1 && argc - optind != 2)
        usage ();
    topic = argv[optind++];
    if (argc - optind > 0)
        expected_errno = strtoul (argv[optind++], NULL, 10);

    if (!(h = flux_open (NULL, 0))) {
        fprintf (stderr, "flux_open\n");
        exit (1);
    }
    if (!(f = flux_rpc (h, topic, NULL, FLUX_NODEID_ANY, 0))) {
        fprintf (stderr, "flux_rpc %s\n", topic);
        exit (1);
    }
    if (flux_rpc_get (f, &result) < 0) {
        if (expected_errno > 0) {
            if (errno != expected_errno) {
                fprintf (stderr,
                         "%s: failed with errno=%d != expected %d\n",
                         topic,
                         errno,
                         expected_errno);
                exit (1);
            }
        } else {
            fprintf (stderr, "%s: %s\n", topic, future_strerror (f, errno));
            exit (1);
        }
    } else {
        if (expected_errno > 0) {
            fprintf (stderr,
                     "%s: succeeded but expected failure errno=%d\n",
                     topic,
                     expected_errno);
            exit (1);
        }
        fprintf (stdout, "%s\n", result);
    }
    flux_future_destroy (f);
    flux_close (h);
    return (0);
}

/*
 * vi:tabstop=4 shiftwidth=4 expandtab
 */
