/************************************************************\
 * Copyright 2021 Lawrence Livermore National Security, LLC
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
#include <fcntl.h>
#include <stdint.h>
#include <stdlib.h>
#include <unistd.h>
#include <string.h>
#include <jansson.h>
#include <flux/core.h>

#include "errprintf.h"
#include "monotime.h"
#include "ccan/str/str.h"

#include "eventlog.h"

bool eventlog_entry_validate (json_t *entry)
{
    json_t *name;
    json_t *timestamp;
    json_t *context;

    if (!json_is_object (entry) || !(name = json_object_get (entry, "name"))
        || !json_is_string (name) || !(timestamp = json_object_get (entry, "timestamp"))
        || !json_is_number (timestamp))
        return false;

    if ((context = json_object_get (entry, "context"))) {
        if (!json_is_object (context))
            return false;
    }

    return true;
}

json_t *eventlog_entry_decode (const char *entry)
{
    int len;
    char *ptr;
    json_t *o;

    if (!entry)
        goto einval;

    if (!(len = strlen (entry)))
        goto einval;

    if (entry[len - 1] != '\n')
        goto einval;

    if (entry[len - 1] != '\n')
        goto einval;

    ptr = strchr (entry, '\n');
    if (ptr != &entry[len - 1])
        goto einval;

    if (!(o = json_loads (entry, JSON_ALLOW_NUL, NULL)))
        goto einval;

    if (!eventlog_entry_validate (o)) {
        json_decref (o);
        goto einval;
    }

    return o;

einval:
    errno = EINVAL;
    return NULL;
}

int eventlog_entry_parse (json_t *entry, double *timestamp, const char **name, json_t **context)
{
    double t;
    const char *n;
    json_t *c;

    if (!entry) {
        errno = EINVAL;
        return -1;
    }

    if (json_unpack (entry, "{ s:F s:s }", "timestamp", &t, "name", &n) < 0) {
        errno = EINVAL;
        return -1;
    }

    if (!json_unpack (entry, "{ s:o }", "context", &c)) {
        if (!json_is_object (c)) {
            errno = EINVAL;
            return -1;
        }
    } else
        c = NULL;

    if (timestamp)
        (*timestamp) = t;
    if (name)
        (*name) = n;
    if (context)
        (*context) = c;

    return 0;
}

static double adjust_timeout (double timeout, struct timespec t0)
{
    return timeout - (1E-3 * monotime_since (t0));
}

int eventlog_wait_for (flux_future_t *f,
                       const char *event_name,
                       double timeout,
                       json_t **obj,
                       flux_error_t *error)
{
    bool done = false;
    json_t *res = NULL;

    while (!done) {
        const char *s;
        json_t *entry;
        const char *name;
        json_t *context;
        struct timespec t0;

        monotime (&t0);
        if (flux_future_wait_for (f, timeout) < 0 || flux_job_event_watch_get (f, &s) < 0) {
            errprintf (error, "error reading job eventlog: %s", future_strerror (f, errno));
            return -1;
        }
        if (!(entry = eventlog_entry_decode (s))
            || eventlog_entry_parse (entry, NULL, &name, &context) < 0) {
            errprintf (error, "error parsing eventlog entry");
            json_decref (entry);
            return -1;
        }
        if (streq (name, "start")) {
            done = true;
        } else if (streq (name, "exception")) {
            int severity;
            if (json_unpack (context, "{s:i}", "severity", &severity) == 0 && severity == 0)
                done = true;
        } else if (streq (name, event_name)) {
            res = json_incref (context);
            done = true;
        }
        json_decref (entry);
        flux_future_reset (f);
        if (timeout >= 0.)
            timeout = adjust_timeout (timeout, t0);
    }
    *obj = res;
    return 0;
}

// vi:ts=4 sw=4 expandtab
