/************************************************************\
 * Copyright 2021 Lawrence Livermore National Security, LLC
 * (c.f. AUTHORS, NOTICE.LLNS, COPYING)
 *
 * This file is part of the Flux resource manager framework.
 * For details, see https://github.com/flux-framework.
 *
 * SPDX-License-Identifier: LGPL-3.0
\************************************************************/

#ifndef _EVENTLOG_HELPERS_H
#define _EVENTLOG_HELPERS_H

#include <stdbool.h>

#include <jansson.h>
#include <flux/core.h>

bool eventlog_entry_validate (json_t *entry);

json_t *eventlog_entry_decode (const char *entry);

int eventlog_entry_parse (json_t *entry, double *timestamp, const char **name, json_t **context);

/* Keep reading from 'f' until the optional named event is posted,
 * then return the event context in *obj (caller must free).
 * Return 0 on success, or -1 on error with 'error' set.
 *
 * If a surpassing event is posted before the named event, set *obj
 * to NULL and return success.  An exception or the "start" event
 * is assumed to be surpassing.
 *
 * If timeout is set to a non-negative number of seconds, and neither
 * the named event nor the above surpassing events have been posted,
 * return failure.
 *
 * N.B. the eventlog should be requested with:
 *   flux_job_event_watch (h, jobid, "eventlog", 0);
 */
int eventlog_wait_for (flux_future_t *f,
                       const char *event_name,
                       double timeout,
                       json_t **obj,
                       flux_error_t *error);

#endif /* !_EVENTLOG_HELPERS_H */

// vi:ts=4 sw=4 expandtab
