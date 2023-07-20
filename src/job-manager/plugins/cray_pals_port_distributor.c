/************************************************************\
 * Copyright 2021 Lawrence Livermore National Security, LLC
 * (c.f. AUTHORS, NOTICE.LLNS, COPYING)
 *
 * This file is part of the Flux resource manager framework.
 * For details, see https://github.com/flux-framework.
 *
 * SPDX-License-Identifier: LGPL-3.0
\************************************************************/

/* cray_pals_port_distributor.c - Distribute port numbers for use
 * by Cray's libpals. See also `src/shell/plugins/cray_pals.c`.
 */

#include <stdio.h>
#include <syslog.h>

#include <jansson.h>

#include <flux/core.h>
#include <flux/hostlist.h>
#include <flux/jobtap.h>

#define CRAY_PALS_AUX_NAME "cray::libpals::ports"

#define PLUGIN_NAME "cray_pals_port_distributor"

struct port_range {
    json_int_t *available_ports;
    json_int_t fill;
    json_int_t maxsize;
};

struct plugin_range_jobid_triple {
    flux_plugin_t *plugin;
    struct port_range *range;
    flux_jobid_t jobid;
};  // for passing to flux_future_t callback

static json_int_t get_port (struct port_range *range)
{
    if (range->fill <= 0) {
        return -1;
    }
    range->fill--;
    return range->available_ports[range->fill];
}

static json_int_t set_port (struct port_range *range, json_int_t port)
{
    if (range->fill >= range->maxsize) {
        return -1;
    }
    range->available_ports[range->fill] = port;
    range->fill++;
    return 0;
}

/*
 * Return a 'struct hostlist' containing the hostnames of every shell rank.
 */
static struct hostlist *hostlist_from_array (json_t *nodelist_array)
{
    size_t index;
    json_t *value;
    struct hostlist *hlist;
    const char *entry;

    if (!json_is_array (nodelist_array) || !(hlist = hostlist_create ())) {
        return NULL;
    }
    json_array_foreach (nodelist_array, index, value)
    {
        if (!(entry = json_string_value (value))
            || hostlist_append (hlist, entry) < 0) {
            hostlist_destroy (hlist);
            return NULL;
        }
    }
    return hlist;
}

/* Callback to KVS lookup for a job's R.
 * Calculate the number of shells in the job and then optionally
 * post a cray_port_distribution to the job's eventlog.
 */
static void count_job_shells (flux_future_t *fut, void *arg)
{
    struct plugin_range_jobid_triple *triple = arg;
    json_t *nodelist;
    struct hostlist *hlist = NULL;
    json_int_t port1, port2;
    flux_t *h;
    json_t *arr = NULL;

    if (!(h = flux_future_get_flux (fut))) {
        goto cleanup;
    }
    if (flux_kvs_lookup_get_unpack (fut,
                                    "{s:{s:o}}",
                                    "execution",
                                    "nodelist",
                                    &nodelist) < 0
        || !(hlist = hostlist_from_array (nodelist))) {
        flux_log_error (h,
                        PLUGIN_NAME ": "
                        "Error fetching R from shell-counting future");
        goto cleanup;
    }
    if (hostlist_count (hlist) == 1) {
        goto cleanup;  // no need to post ports
    }
    // assign ports to the job
    if ((port1 = get_port (triple->range)) < 0 || (port2 = get_port (triple->range)) < 0
        || !(arr = json_pack ("[I, I]", port1, port2))
        || flux_jobtap_event_post_pack (triple->plugin,
                                        triple->jobid,
                                        "cray_port_distribution",
                                        "{s:O}",
                                        "ports",
                                        arr) < 0
        || flux_jobtap_job_aux_set (triple->plugin,
                                    triple->jobid,
                                    CRAY_PALS_AUX_NAME,
                                    arr,
                                    (flux_free_f)json_decref) < 0) {
        if (arr)
            json_decref (arr);
        flux_log_error (h,
                        PLUGIN_NAME ": "
                        "Failed to post ports to job");
        goto cleanup;
    }

cleanup:
    if (flux_jobtap_prolog_finish (triple->plugin,
                                   triple->jobid,
                                   "cray-pals-port-distributor",
                                   0) < 0)
        flux_log_error (h,
                        PLUGIN_NAME ": prolog_finish");
    if (hlist)
        hostlist_destroy (hlist);
    flux_future_destroy (fut);
    free (triple);
    return;
}

/* Create a future to get a job's R. Callback to the future will grab
 * free ports and write them into the job's event log.
 */
static int run_cb (flux_plugin_t *p,
                   const char *topic,
                   flux_plugin_arg_t *args,
                   void *arg)
{
    flux_t *h;
    flux_jobid_t jobid;
    char buf[1024];
    flux_future_t *fut = NULL;
    struct plugin_range_jobid_triple *triple;
    // 'arg' is 'struct port_range *'

    if (!(h = flux_jobtap_get_flux (p))
        || flux_plugin_arg_unpack (args, FLUX_PLUGIN_ARG_IN, "{s:I}", "id", &jobid) < 0
        || !(triple = malloc (sizeof (struct plugin_range_jobid_triple))))
        return -1;
    triple->range = arg;
    triple->jobid = jobid;
    triple->plugin = p;
    if (flux_job_kvs_key (buf, sizeof (buf), jobid, "R") < 0
        || !(fut = flux_kvs_lookup (h, NULL, 0, buf))
        || flux_future_then (fut, -1., count_job_shells, triple) < 0) {
        if (fut)
            flux_future_destroy (fut);
        flux_log_error (h,
                        PLUGIN_NAME ": "
                        "Error creating shell-counting future");
        goto error;
    }
    if (flux_jobtap_prolog_start (p, "cray-pals-port-distributor") < 0) {
        flux_log_error (h, PLUGIN_NAME ": prolog_start");
        goto error;
    }
    // 'triple' freed in callback
    return 0;
error:
    free (triple);
    return -1;
}

/* On a job's cleanup event, get the ports and return them
 * to the pool.
 */
static int cleanup_cb (flux_plugin_t *p,
                       const char *topic,
                       flux_plugin_arg_t *args,
                       void *arg)
{
    struct port_range *range = arg;
    flux_t *h;
    json_t *array, *value;
    json_int_t portnum;
    size_t index;

    if (!(h = flux_jobtap_get_flux (p)))
        return -1;
    if (!(array =
              flux_jobtap_job_aux_get (p, FLUX_JOBTAP_CURRENT_JOB, CRAY_PALS_AUX_NAME)))
        return 0;
    if (!json_is_array (array)) {
        flux_log_error (h,
                        PLUGIN_NAME ": " CRAY_PALS_AUX_NAME
                        " aux is not array");
        return -1;
    }
    json_array_foreach (array, index, value)
    {
        if ((portnum = json_integer_value (value)) == 0) {
            flux_log_error (h,
                            PLUGIN_NAME ": "
                            "Malformed cray_port_distribution event");
            return -1;
        }
        if (set_port (range, portnum) < 0) {
            flux_log_error (h, PLUGIN_NAME ": Port overflow");
            return -1;
        }
    }
    return 0;
}

static void port_range_destroy (struct port_range *range)
{
    if (range) {
        free (range->available_ports);
        free (range);
    }
}

/* Create a port_range array and register callbacks
 * to distribute and re-collect the ports.
 */
int flux_plugin_init (flux_plugin_t *p)
{
    struct port_range *range = NULL;
    json_int_t port_min, port_max, size;
    flux_t *h;

    if (!(h = flux_jobtap_get_flux (p)) || flux_plugin_set_name (p, "cray-pals") < 0)
        return -1;
    if (flux_plugin_conf_unpack (p,
                                 "{s:I, s:I}",
                                 "port-min",
                                 &port_min,
                                 "port-max",
                                 &port_max) < 0) {
        port_min = 11000;
        port_max = 12000;
        flux_log (h,
                  LOG_NOTICE,
                  "Port range not specified in config with port-min and port-max. "
                  "Using defaults of %" JSON_INTEGER_FORMAT " and %" JSON_INTEGER_FORMAT ".",
                  port_min,
                  port_max);
    }

    // check that port range falls within acceptable bounds
    // ports less than 1024 require root, max port is 2^16 -
    if (port_min < 1024 || port_max < 1024 || port_max > (1 << 16)) {
        flux_log_error (h, PLUGIN_NAME ": invalid port min/max");
        return -1;
    }
    size = (port_max - port_min);
    if (size < 50) {
        flux_log_error (h,
                        PLUGIN_NAME ": "
                        "Not enough ports specified: %" JSON_INTEGER_FORMAT,
                        size);
        return -1;
    }

    if (!(range = malloc (sizeof (struct port_range)))
        || !(range->available_ports = malloc (size * sizeof (port_min)))) {
        free (range);
        flux_log_error (h,
                        PLUGIN_NAME ": "
                        "Error allocating port range");
        return -1;
    }
    range->maxsize = size;
    range->fill = size;
    for (int i = 0; i < size; ++i) {
        range->available_ports[i] = port_min + i;
    }
    if (flux_plugin_add_handler (p, "job.state.run", run_cb, range) < 0
        || flux_plugin_add_handler (p, "job.state.cleanup", cleanup_cb, range) < 0
        || flux_plugin_aux_set (p, NULL, range, (flux_free_f)port_range_destroy) < 0) {
        port_range_destroy (range);
        return -1;
    }
    return 0;
}
