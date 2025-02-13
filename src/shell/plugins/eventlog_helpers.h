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

bool eventlog_entry_validate (json_t *entry);

json_t *eventlog_entry_decode (const char *entry);

int eventlog_entry_parse (json_t *entry, double *timestamp, const char **name, json_t **context);

#endif /* !_EVENTLOG_HELPERS_H */
