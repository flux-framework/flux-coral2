#!/usr/bin/env python3
##############################################################
# Copyright 2026 Lawrence Livermore National Security, LLC
# (c.f. AUTHORS, NOTICE.LLNS, LICENSE)
#
# This file is part of the Flux resource manager framework.
# For details, see https://github.com/flux-framework.
#
# SPDX-License-Identifier: LGPL-3.0
##############################################################

"""
Scan the live sched-fluxion-resource graph for orphaned resource state:
vertices that still carry allocations, reservations, planner spans, or
job tags for jobs that are no longer running.

For each of the N most recent inactive jobs (plus every running job, as
a control) the script asks the resource module which vertices still
hold state for that job, what the module itself believes the job's
status is, and what flux-core believes (eventlog, housekeeping).  It
also snapshots everything the module currently reports as allocated or
reserved so that state owned by jobs *outside* the scanned window is
accounted for, and dumps the aggregate (pruning) filter counts.

Output is a JSON document plus a human-readable summary.  Only the
`find`, `info`, `params` and `stats-get` RPCs of the resource module
are used; nothing is modified.

Note: every `find` is answered synchronously on the resource module's
main thread, so on a very large graph each query briefly delays
scheduling.  Use --delay to pace the per-job queries.
"""

import argparse
import errno
import json
import logging
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime

import flux
import flux.job
from flux.eventlog import EventLogEvent
from flux.job import JobID, JobList

RESOURCE_SERVICE = "sched-fluxion-resource"

AGFILTER_RE = re.compile(r"used:\s*(-?\d+),\s*total:\s*(-?\d+)")
# "      ---------ssd15[793:x]" : depth dashes, name, [needs:mode]
SIMPLE_RE = re.compile(r"^\s*(-+)([^\[\s]+)\[(\d+):([xs])\]\s*$")
# split a vertex name into basename + numeric id ("ssd15" -> "ssd", 15)
NAME_RE = re.compile(r"^(.*?)(\d+)$")

JOB_PREDICATES = ("jobid-alloc", "jobid-reserved", "jobid-span", "jobid-tag")
# The job predicates that do not represent an allocation.
RESIDUE_PREDICATES = tuple(p for p in JOB_PREDICATES if p != "jobid-alloc")
ORPHAN_CLASSES = (
    "orphan-module-no-record",
    "orphan-module-still-allocated",
    "module-error",
)

LOGGER = logging.getLogger("flux-rabbit-orphan-scan")


def iso(ts):
    if not ts:
        return None
    return datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds")


class ResourceModule:
    """Thin wrapper over the sched-fluxion-resource RPCs we need."""

    def __init__(self, handle, timeout):
        self.h = handle
        self.timeout = timeout
        self.n_find = 0
        self.n_simple_fallback = 0
        self.find_seconds = 0.0

    def _rpc(self, topic, payload):
        fut = self.h.rpc(topic, payload)
        fut.wait_for(self.timeout)
        return fut.get()

    def find(self, criteria):
        """
        Return the list of JGF vertex entries matching criteria.

        The JGF writer refuses to emit a vertex set that has no edges
        (check_array_sizes () fails with ENOENT). Fall back to the "simple" writer
        for this case and synthesize entries from it; they
        carry name/size but no containment path, rank or real type.
        """
        start = time.monotonic()
        topic = f"{RESOURCE_SERVICE}.find"
        try:
            resp = self._rpc(topic, {"criteria": criteria, "format": "jgf"})
            entries = None
        except OSError as exc:
            if exc.errno != errno.ENOENT:
                raise
            resp = self._rpc(topic, {"criteria": criteria, "format": "simple"})
            self.n_simple_fallback += 1
            entries = simple_to_entries(resp.get("R"))
        self.find_seconds += time.monotonic() - start
        self.n_find += 1
        if entries is not None:
            return entries
        R = resp.get("R")
        if not R:
            return []
        return R.get("graph", {}).get("nodes", [])

    def info(self, jobid):
        """Return the module's view of a job, or None if it is unknown."""
        try:
            return self._rpc(f"{RESOURCE_SERVICE}.info", {"jobid": int(jobid)})
        except OSError as exc:
            if exc.errno == errno.ENOENT:
                return None
            raise

    def params(self):
        try:
            return self._rpc(f"{RESOURCE_SERVICE}.params", {}).get("params")
        except OSError:
            return None

    def stats(self):
        try:
            return self._rpc(f"{RESOURCE_SERVICE}.stats-get", {})
        except OSError:
            return None


def simple_to_entries(text):
    """Turn "simple" writer output into JGF-like vertex entries."""
    entries = []
    if not text:
        return entries
    for line in text.splitlines():
        m = SIMPLE_RE.match(line)
        if not m:
            continue
        dashes, name, needs, _mode = m.groups()
        nm = NAME_RE.match(name)
        # names with no trailing digits carry no type information at all
        basename, rid = (nm.group(1), int(nm.group(2))) if nm else (None, None)
        md = {
            "type": basename or "unknown",
            "name": name,
            "id": rid,
            "rank": None,
            "paths": {"containment": None},
            "depth": len(dashes) // 3,
            "from_simple_writer": True,
        }
        if int(needs) != 1:
            md["size"] = int(needs)
        entries.append({"id": None, "metadata": md})
    return entries


def parse_agfilter(agfilter):
    parsed = {}
    for rtype, text in agfilter.items():
        m = AGFILTER_RE.search(text)
        if m:
            parsed[rtype] = {"used": int(m.group(1)), "total": int(m.group(2))}
        else:
            parsed[rtype] = {"raw": text}
    return parsed


def vertex_summary(entry):
    """Flatten a JGF find vertex entry into the fields we care about."""
    md = entry.get("metadata", {})
    basename = md.get("basename", md.get("type"))
    rid = md.get("id")
    name = md.get("name") or f"{basename}{rid}"
    out = {
        "uniq_id": entry.get("id"),
        "type": md.get("type") or "unknown",
        "name": name,
        "rank": md.get("rank"),
        "path": md.get("paths", {}).get("containment") or name,
    }
    if md.get("from_simple_writer"):
        # the simple writer emits the vertex name only, so the rank is
        # unknown and the type is at best a guess from the name prefix
        out["type_guessed_from_name"] = out["type"] != "unknown"
        out["depth"] = md.get("depth")
    if "size" in md:
        out["size"] = md["size"]
    if "agfilter" in md:
        out["agfilter"] = parse_agfilter(md["agfilter"])
    return out


def mark_leaves(vertices):
    """
    find emits every ancestor of a matching vertex for context, so a
    returned cluster/chassis vertex does not necessarily hold the state
    itself.  Flag the vertices that have no returned descendant; those
    are guaranteed real matches.

    Walk each path's ancestors instead of comparing every pair: on a
    graph with tens of thousands of vertices the pairwise form costs
    tens of seconds.  Splitting on "/" also keeps "/cluster0/compute-1"
    from being read as an ancestor of its sibling "/cluster0/compute-10".
    """
    paths = {v["path"] for v in vertices if v.get("path")}
    internal = set()
    for path in paths:
        parent = path
        while True:
            cut = parent.rfind("/")
            if cut <= 0:
                break
            parent = parent[:cut]
            if parent in internal:
                break  # the rest of this chain is already marked
            if parent in paths:
                internal.add(parent)
    for v in vertices:
        p = v.get("path")
        v["leaf"] = bool(p) and p not in internal
    return vertices


def type_counts(vertices):
    return dict(Counter(v["type"] for v in vertices))


def rankless_count(vertices):
    return sum(1 for v in vertices if v.get("rank") == -1)


def vertex_set_summary(vertices, include_vertices):
    out = {
        "n_vertices": len(vertices),
        "n_leaf": sum(1 for v in vertices if v.get("leaf")),
        "n_rankless": rankless_count(vertices),
        "by_type": type_counts(vertices),
        "leaf_by_type": type_counts([v for v in vertices if v.get("leaf")]),
    }
    if include_vertices:
        out["vertices"] = vertices
    return out


def find_vertices(rmod, criteria):
    """Run one find query and return leaf-marked vertex summaries."""
    return mark_leaves([vertex_summary(e) for e in rmod.find(criteria)])


def job_state_in_graph(rmod, jobid):
    """
    Return everything the graph holds for one job, keyed by predicate.
    A single combined query decides cheaply whether the job has any
    state at all; only jobs that do are broken down per predicate.
    """
    combined = rmod.find(" or ".join(f"{p}={jobid}" for p in JOB_PREDICATES))
    if not combined:
        return None
    detail = {pred: find_vertices(rmod, f"{pred}={jobid}") for pred in JOB_PREDICATES}
    return detail


def eventlog_summary(handle, jobid):
    """Release-related events from the main eventlog."""
    try:
        data = flux.job.job_kvs_lookup(handle, jobid, keys=["eventlog"])
    except OSError:
        data = None
    if not data or not data.get("eventlog"):
        return None
    names = []
    releases = []
    for line in data["eventlog"].splitlines():
        try:
            ev = EventLogEvent(line)
        except Exception:  # malformed line; keep going
            continue
        names.append(ev.name)
        if ev.name == "release":
            releases.append(
                {
                    "t": ev.timestamp,
                    "ranks": ev.context.get("ranks"),
                    "final": ev.context.get("final"),
                }
            )
    counts = Counter(names)
    return {
        "has_alloc": counts["alloc"] > 0,
        "has_free": counts["free"] > 0,
        "has_clean": counts["clean"] > 0,
        "n_release": counts["release"],
        "releases": releases,
        "exception": counts["exception"] > 0,
    }


def job_R_summary(handle, jobid):
    try:
        data = flux.job.job_kvs_lookup(handle, jobid, keys=["R"])
    except OSError:
        data = None
    if not data or not data.get("R"):
        return None
    R = data["R"]
    execution = R.get("execution", {})
    out = {
        "has_scheduling_key": "scheduling" in R,
        "starttime": execution.get("starttime"),
        "expiration": execution.get("expiration"),
        "nodelist": execution.get("nodelist"),
    }
    sched = R.get("scheduling") or {}
    nodes = sched.get("graph", {}).get("nodes", []) if isinstance(sched, dict) else []
    if nodes:
        out["jgf_type_counts"] = dict(
            Counter(n.get("metadata", {}).get("type") for n in nodes)
        )
    return out


def jobinfo_dict(job):
    """Pull the JobInfo fields we record into a plain dict."""
    exc = getattr(job, "exception", None)
    return {
        "id": int(job.id),
        "f58": job.id.f58,
        "userid": job.userid,
        "name": getattr(job, "name", ""),
        "queue": getattr(job, "queue", ""),
        "state": str(job.state),
        "result": str(getattr(job, "result", "")) or None,
        "nnodes": getattr(job, "nnodes", None),
        "ntasks": getattr(job, "ntasks", None),
        "ranks": getattr(job, "ranks", ""),
        "t_submit": job.t_submit,
        "t_run": job.t_run,
        "t_cleanup": job.t_cleanup,
        "t_inactive": job.t_inactive,
        "t_run_iso": iso(job.t_run),
        "t_inactive_iso": iso(job.t_inactive),
        "expiration": getattr(job, "expiration", 0.0),
        "duration": getattr(job, "duration", 0.0),
        "exception": {
            "occurred": bool(getattr(exc, "occurred", False)),
            "type": getattr(exc, "type", "") or None,
            "note": getattr(exc, "note", "") or None,
        },
    }


def housekeeping_state(handle, timeout):
    """
    Jobs the job manager still holds in housekeeping, keyed by int id.

    Returns (jobs, error).  A job in housekeeping is already inactive and
    already has a `clean` event, so housekeeping is the only thing that
    distinguishes it from a real orphan: if this query fails, say so
    loudly rather than silently classifying those jobs as orphaned.
    """
    try:
        fut = handle.rpc("job-manager.stats-get", {})
        fut.wait_for(timeout)
        stats = fut.get()
    except OSError as exc:
        return {}, str(exc)
    running = stats.get("housekeeping", {}).get("running", {}) or {}
    out = {}
    for key, entry in running.items():
        try:
            jid = int(JobID(key))
        except (ValueError, TypeError):
            continue
        out[jid] = {
            "t_start": entry.get("t_start"),
            "pending_ranks": entry.get("pending"),
            "allocated_ranks": entry.get("allocated"),
        }
    return out, None


def classify(job, graph_state, module_info, evlog, hk, recent):
    """
    Decide what a job's leftover graph state means.

      running                     job is running; state is legitimate
      running-module-unknown      running job the module has no record of
      running-no-graph-state      running job with nothing in the graph
                                  (e.g. not reconstructed after a reload)
      inactive-and-clean          inactive job, nothing left anywhere
      held-pending-final-free     inactive, module record ALLOCATED, flux-core
                                  has not finished releasing (housekeeping or
                                  no clean event yet): legitimate hold
      orphan-module-still-allocated
                                  inactive and clean in flux-core, module
                                  record still ALLOCATED: the final cancel
                                  never reached the module
      orphan-module-no-record     inactive, module has no record (ENOENT),
                                  graph still holds state: a Fluxion-side leak
      module-error                module marks the job ERROR: removal failed
      reservation                 module RESERVED for an inactive job
      scan-error                  the scan of the job itself failed (see
                                  the "error" key in the JSON); not set by
                                  this function, see scan()
      recent-*                    same, but the job went inactive within
                                  --settle seconds, so it may still be
                                  mid-release; excluded from orphan totals
    """
    status = (module_info or {}).get("status")
    if str(job.state) in ("RUN", "CLEANUP"):
        if graph_state is None:
            return "running-no-graph-state"
        if status is None:
            return "running-module-unknown"
        return "running"
    if graph_state is None:
        return "inactive-and-clean"
    if status == "ERROR":
        classification = "module-error"
    elif status == "RESERVED":
        classification = "reservation"
    elif status == "ALLOCATED":
        if hk is not None or (evlog and not evlog["has_clean"]):
            classification = "held-pending-final-free"
        else:
            classification = "orphan-module-still-allocated"
    elif status is None:
        classification = "orphan-module-no-record"
    else:
        classification = f"unexpected-{status}"
    if recent and classification != "held-pending-final-free":
        classification = "recent-" + classification
    return classification


def agfilter_in_use(vertex):
    """True if any resource type in the vertex's aggregate filter is in use."""
    return any(c.get("used", 0) != 0 for c in vertex["agfilter"].values())


def collect_agfilters(rmod, full_vertices):
    """Snapshot the aggregate (pruning) filters of every filter-bearing vertex."""
    # With agfilter=true the traverser emits only vertices that carry a
    # filter planner, so the key test is a guard against writer changes.
    filter_vertices = [
        v
        for v in find_vertices(rmod, "(status=up or status=down) and agfilter=true")
        if "agfilter" in v
    ]
    nonzero_filters = [v for v in filter_vertices if agfilter_in_use(v)]
    return {
        "n_filter_vertices": len(filter_vertices),
        "n_with_nonzero_used": len(nonzero_filters),
        "nonzero": nonzero_filters,
        "all": filter_vertices if full_vertices else None,
    }


def list_jobs(handle, args):
    """Every running job (control group) plus the N most recent inactive."""
    # max_entries=0 means unlimited: every running job is a control group,
    # and a running job missed here looks like an unexplained allocation.
    running = JobList(handle, filters=["running"], user="all", max_entries=0).jobs()
    inactive = JobList(
        handle, filters=["inactive"], max_entries=args.count, user="all"
    ).jobs()
    inactive.sort(key=lambda j: j.t_inactive, reverse=True)
    if args.only_with_R:
        running = [j for j in running if j.t_run > 0]
        inactive = [j for j in inactive if j.t_run > 0]
    jobs = list(running) + list(inactive)
    return running, inactive, jobs


def scan_job(handle, rmod, job, housekeeping, args, started):
    """Collect one job's record; return it with the raw graph state."""
    jobid = int(job.id)
    graph_state = job_state_in_graph(rmod, jobid)
    record = {
        "job": jobinfo_dict(job),
        "module_info": rmod.info(jobid),
        "housekeeping": housekeeping.get(jobid),
        "eventlog": None,
        "R": None,
        "graph_state": None,
        "agfilter_error": None,
    }
    if graph_state is not None or args.eventlog_all:
        record["eventlog"] = eventlog_summary(handle, jobid)
        record["R"] = job_R_summary(handle, jobid)
    record["recent"] = job.t_inactive > 0 and (started - job.t_inactive) < args.settle
    record["class"] = classify(
        job,
        graph_state,
        record["module_info"],
        record["eventlog"],
        record["housekeeping"],
        record["recent"],
    )
    if graph_state is not None:
        # A partial removal can leave spans on descendants but not their
        # ancestors. The per-job filter query then fails; preserve the
        # predicate results that establish the job's remaining state.
        try:
            graph_state["agfilter-per-job"] = find_vertices(
                rmod, f"jobid-span={jobid} and agfilter=true"
            )
        except OSError as exc:
            graph_state["agfilter-per-job"] = None
            record["agfilter_error"] = f"{type(exc).__name__}: {exc}"
            LOGGER.warning(
                "%s: per-job aggregate-filter query failed: %s", job.id.f58, exc
            )
        include = args.full_vertices or record["class"] != "running"
        record["graph_state"] = {
            pred: vertex_set_summary(verts, include) if verts is not None else None
            for pred, verts in graph_state.items()
        }
    return record, graph_state


def scan_error_record(job, exc):
    """Stand-in record for a job whose scan raised, so the scan can go on."""
    try:
        jobinfo = jobinfo_dict(job)
    except Exception:  # the JobInfo itself is unusable
        jobinfo = {
            "id": int(job.id),
            "f58": job.id.f58,
            "t_run_iso": None,
            "t_inactive_iso": None,
        }
    return {
        "job": jobinfo,
        "module_info": None,
        "housekeeping": None,
        "eventlog": None,
        "R": None,
        "graph_state": None,
        "recent": False,
        "class": "scan-error",
        "agfilter_error": None,
        "error": f"{type(exc).__name__}: {exc}",
    }


def merge_residue_vertices(graph_state):
    """Merge residue query results, retaining the predicates for each vertex."""
    merged = {}
    for pred in RESIDUE_PREDICATES:
        for index, vertex in enumerate(graph_state[pred]):
            uniq_id = vertex.get("uniq_id")
            path = vertex.get("path")
            if uniq_id is not None:
                key = ("id", uniq_id)
            elif (
                path and path.startswith("/") and "type_guessed_from_name" not in vertex
            ):
                key = ("path", path)
            else:
                # Bare names from the simple writer cannot identify a vertex
                # across queries. Preserve each occurrence rather than merge
                # distinct vertices that happen to have the same name.
                key = ("unknown", pred, index)
            if key not in merged:
                merged[key] = {**vertex, "predicates": []}
            if pred not in merged[key]["predicates"]:
                merged[key]["predicates"].append(pred)
    # A vertex can be a leaf in one query and an ancestor in another. Work
    # on copies so this union does not change the individual query results.
    return mark_leaves(list(merged.values()))


class ScanTotals:
    """Tallies accumulated across the scanned jobs."""

    def __init__(self):
        self.classes = Counter()
        self.orphaned_vertices = []
        self.orphaned_residue = []
        self.held_vertices = []
        self.explained_alloc_paths = set()

    def add(self, job, record, graph_state):
        classification = record["class"]
        self.classes[classification] += 1
        if graph_state is None:
            return
        allocated = graph_state["jobid-alloc"]
        self.explained_alloc_paths.update(v["path"] for v in allocated)
        if classification in ORPHAN_CLASSES:
            self.orphaned_vertices.extend(
                {"jobid": job.id.f58, "class": classification, **v} for v in allocated
            )
            # Allocation query results include ancestors for context, so
            # membership there cannot justify discarding residue. Keep one
            # identifiable vertex per job, with all queries that returned it.
            self.orphaned_residue.extend(
                {"jobid": job.id.f58, "class": classification, **v}
                for v in merge_residue_vertices(graph_state)
            )
        elif classification == "held-pending-final-free":
            self.held_vertices.extend(allocated)


def build_summary(totals, allocated, job_counts, rmod, args, started):
    # Anything allocated that no scanned job explains is owned by a job
    # outside the window (older than --count), by a non-job allocation
    # (e.g. a raw match RPC), or by a job whose scan failed.
    unexplained = [
        v for v in allocated if v["path"] not in totals.explained_alloc_paths
    ]
    orphaned = totals.orphaned_vertices
    return {
        "classes": dict(totals.classes),
        **job_counts,
        "n_jobs_failed": totals.classes["scan-error"],
        "orphaned_vertices_by_type": type_counts(orphaned),
        "orphaned_leaf_by_type": type_counts([v for v in orphaned if v.get("leaf")]),
        "orphaned_vertices": orphaned,
        "orphaned_residue_by_type": type_counts(totals.orphaned_residue),
        "orphaned_residue": totals.orphaned_residue,
        "held_by_core_vertices_by_type": type_counts(totals.held_vertices),
        "allocated_unexplained_by_scanned_jobs": vertex_set_summary(
            unexplained, args.full_vertices or len(unexplained) <= 500
        ),
        "find_rpcs": rmod.n_find,
        "find_simple_writer_fallbacks": rmod.n_simple_fallback,
        "find_seconds_total": round(rmod.find_seconds, 3),
        "find_seconds_mean": (
            round(rmod.find_seconds / rmod.n_find, 4) if rmod.n_find else None
        ),
        "elapsed_seconds": round(time.time() - started, 1),
    }


def scan(args):
    handle = flux.Flux()
    rmod = ResourceModule(handle, args.timeout)
    started = time.time()
    report = {
        "meta": {
            "started": iso(started),
            "hostname": os.uname().nodename,
            "flux_core_version": handle.attr_get("version"),
            "instance_size": int(handle.attr_get("size")),
            "scanned_inactive_jobs": args.count,
            "args": vars(args),
        }
    }

    LOGGER.info("collecting module parameters and stats")
    report["module"] = {"params": rmod.params(), "stats": rmod.stats()}

    # Global graph snapshots: ground truth for "what does the scheduler
    # think is in use right now", independent of any job listing.
    LOGGER.info("snapshotting allocated/reserved/down vertices")
    allocated = find_vertices(rmod, "sched-now=allocated")
    reserved = find_vertices(rmod, "sched-future=reserved")
    down = find_vertices(rmod, "status=down")
    report["graph"] = {
        "allocated": vertex_set_summary(allocated, True),
        "reserved": vertex_set_summary(reserved, True),
        "down": vertex_set_summary(down, args.full_vertices),
    }
    LOGGER.info("reading aggregate (pruning) filters")
    report["agfilter"] = collect_agfilters(rmod, args.full_vertices)

    LOGGER.info("listing jobs")
    running_jobs, inactive_jobs, jobs = list_jobs(handle, args)
    housekeeping, hk_error = housekeeping_state(handle, args.timeout)
    report["housekeeping"] = {str(k): v for k, v in housekeeping.items()}
    report["meta"]["housekeeping_error"] = hk_error
    if hk_error:
        LOGGER.warning("housekeeping query failed: %s", hk_error)

    totals = ScanTotals()
    report["jobs"] = []
    for index, job in enumerate(jobs, 1):
        LOGGER.info("[%d/%d] %s (%s)", index, len(jobs), job.id.f58, job.state)
        try:
            record, graph_state = scan_job(
                handle, rmod, job, housekeeping, args, started
            )
        except Exception as exc:
            # one unscannable job must not cost us the whole scan
            LOGGER.warning("%s: scan failed: %s", job.id.f58, exc)
            record, graph_state = scan_error_record(job, exc), None
        report["jobs"].append(record)
        totals.add(job, record, graph_state)
        if args.delay:
            time.sleep(args.delay)

    job_counts = {
        "n_jobs_scanned": len(jobs),
        "n_running": len(running_jobs),
        "n_inactive": len(inactive_jobs),
    }
    report["summary"] = build_summary(
        totals, allocated, job_counts, rmod, args, started
    )
    return report


# Classes that get no line in the per-job table of the text summary.
UNREMARKABLE_CLASSES = ("running", "inactive-and-clean")


def write_truncated(emit, items, limit, format_item):
    """Emit at most limit items, then a count of what was left out."""
    for item in items[:limit]:
        emit(format_item(item))
    if len(items) > limit:
        emit(f"... {len(items) - limit} more (see JSON)\n")


def write_header(emit, report):
    meta = report["meta"]
    emit(f"# fluxion orphan scan  {meta['started']}  host={meta['hostname']}\n")
    emit(f"# flux-core {meta['flux_core_version']}  size={meta['instance_size']}\n")
    params = (report.get("module") or {}).get("params") or {}
    if params:
        emit(
            f"# resource module: policy={params.get('policy')} "
            f"match-format={params.get('match-format')} "
            f"prune-filters={params.get('prune-filters')} "
            f"load-format={params.get('load-format')}\n"
        )
    failed = report["summary"]["n_jobs_failed"]
    if failed:
        emit(
            f"\n## WARNING: scan incomplete: {failed} job scans failed;\n"
            "## orphan totals exclude those jobs. Resolve the reported errors "
            "and rerun.\n"
        )
    for record in report.get("jobs", []):
        if record.get("agfilter_error"):
            emit(
                f"\n## WARNING: {record['job']['f58']}: per-job aggregate-filter "
                f"query failed ({record['agfilter_error']});\n"
                "## predicate results and orphan totals were preserved.\n"
            )
    if meta.get("housekeeping_error"):
        emit(
            f"\n## WARNING: the job-manager.stats-get RPC failed "
            f"({meta['housekeeping_error']}),\n"
            "## so no job could be recognized as being in housekeeping.  Jobs "
            "reported as\n"
            "## orphan-module-still-allocated may simply be in housekeeping; "
            "check\n"
            "## flux-housekeeping(1) before treating them as orphaned.\n"
        )


def write_graph_snapshot(emit, graph):
    emit("\n## graph snapshot\n")
    emit("## (find also emits the ancestors of matching vertices; 'leaf' counts only\n")
    emit("## vertices with no matching descendant, which certainly hold the state)\n")
    for key in ("allocated", "reserved", "down"):
        snap = graph[key]
        emit(
            f"  {key:10s} {snap['n_vertices']:7d} vertices, "
            f"{snap['n_leaf']:7d} leaf, {snap['n_rankless']:6d} rank-less   "
            f"leaf by type: {snap['leaf_by_type']}\n"
        )


def format_agfilter_counts(agfilter):
    return ", ".join(
        f"{rtype}={counts.get('used')}/{counts.get('total')}"
        for rtype, counts in sorted(agfilter.items())
        if counts.get("total") or counts.get("used")
    )


def write_agfilters(emit, agfilter_report):
    emit("\n## aggregate (pruning) filters with used != 0, shallowest vertices first\n")
    nonzero_filters = sorted(
        agfilter_report["nonzero"],
        key=lambda v: ((v["path"] or "").count("/"), v["path"] or ""),
    )
    emit(
        f"{len(nonzero_filters)} of {agfilter_report['n_filter_vertices']} "
        f"filter-bearing vertices have used != 0\n"
    )

    def format_row(vertex):
        counts = format_agfilter_counts(vertex["agfilter"])
        return f"{vertex['type']:12s} {vertex['path']:50s} {counts}\n"

    write_truncated(emit, nonzero_filters, 40, format_row)


def write_job_classes(emit, summary):
    emit("\n## job classification\n")
    if not summary["classes"]:
        emit("(no jobs scanned)\n")
    for classification, count in sorted(
        summary["classes"].items(), key=lambda kv: -kv[1]
    ):
        emit(f"{classification:36s} {count}\n")


def eventlog_flags(eventlog):
    """Compact A / R<n> / F / C / X flags for the per-job table."""
    if not eventlog:
        return "-----"
    return "".join(
        [
            "A" if eventlog.get("has_alloc") else "-",
            f"R{eventlog.get('n_release', 0)}",
            "F" if eventlog.get("has_free") else "-",
            "C" if eventlog.get("has_clean") else "-",
            "X" if eventlog.get("exception") else "-",
        ]
    )


def format_job_row(record):
    classification = record["class"]
    f58 = record["job"]["f58"]
    if classification == "running-no-graph-state":
        return f"{f58:>12s} {classification:36s} (running, nothing in graph)\n"
    if classification == "scan-error":
        return f"{f58:>12s} {classification:36s} {record.get('error', '')}\n"
    graph_state = record["graph_state"] or {}
    module_status = (record["module_info"] or {}).get("status") or "ENOENT"
    allocated = graph_state.get("jobid-alloc", {})

    def count(pred):
        return graph_state.get(pred, {}).get("n_vertices", 0)

    return (
        f"{f58:>12s} {classification:36s} {module_status:10s} "
        f"{count('jobid-alloc'):6d} {count('jobid-reserved'):5d} "
        f"{count('jobid-span'):5d} {count('jobid-tag'):5d} "
        f"{allocated.get('n_rankless', 0):8d}  "
        f"{eventlog_flags(record['eventlog']):12s} "
        f"{(record['job']['t_run_iso'] or '')[5:21]:16s} "
        f"{(record['job']['t_inactive_iso'] or '')[5:21]:16s}  "
        f"{allocated.get('leaf_by_type', {})}\n"
    )


def write_job_table(emit, records):
    emit("\n## jobs with leftover graph state (excluding running jobs)\n")
    emit(
        f"{'jobid':>12s} {'class':36s} {'module':10s} {'alloc':>6s} {'resv':>5s} "
        f"{'span':>5s} {'tag':>5s} {'rankless':>8s}  {'eventlog':12s} "
        f"{'t_run':16s} {'t_inactive':16s}  leaf types\n"
    )
    rows = [r for r in records if r["class"] not in UNREMARKABLE_CLASSES]
    for record in rows:
        emit(format_job_row(record))
    if not rows:
        emit("(none)\n")
    emit("eventlog flags: A=alloc R<n>=release events F=free C=clean X=exception\n")


def write_orphans(emit, summary):
    emit("\n## orphaned vertices\n")
    emit("## (allocated to inactive jobs that the module has no record of, still\n")
    emit("## records as ALLOCATED although flux-core completed them, or marks ERROR)\n")
    emit(
        f"by type: {summary['orphaned_vertices_by_type']}   "
        f"leaf only: {summary['orphaned_leaf_by_type']}\n"
    )
    held = summary.get("held_by_core_vertices_by_type") or {}
    if held:
        emit(f"(not counted above -- held pending flux-core's final free: {held})\n")
    residue = summary.get("orphaned_residue_by_type") or {}
    if residue:
        emit(
            f"(vertices returned by span/tag/reservation queries: {residue}; "
            "may overlap allocation totals, do not add the counts)\n"
        )

    def format_row(vertex):
        return (
            f"{vertex['jobid']:>12s} {vertex['class']:30s} {vertex['type']:12s} "
            f"rank={str(vertex['rank']):<5} {vertex['path']}\n"
        )

    write_truncated(emit, summary["orphaned_vertices"], 100, format_row)


def write_unexplained(emit, summary):
    unexplained = summary["allocated_unexplained_by_scanned_jobs"]
    emit("\n## allocated vertices not explained by scanned jobs\n")
    emit(
        f"{unexplained['n_vertices']} vertices, {unexplained['n_leaf']} leaf  "
        f"{unexplained['leaf_by_type']}\n"
    )
    if unexplained["n_vertices"]:
        if summary["n_jobs_failed"]:
            emit(
                "(scan incomplete: allocations may belong to jobs whose scans "
                "failed; resolve their errors and rerun before increasing "
                "--count)\n"
            )
        else:
            emit(
                "(owned by jobs older than the scan window, or by non-job "
                "allocations; rerun with a larger --count)\n"
            )


def format_housekeeping_row(jobid, entry):
    return (
        f"{JobID(int(jobid)).f58:>12s} started={iso(entry.get('t_start'))} "
        f"pending={entry.get('pending_ranks')} "
        f"allocated={entry.get('allocated_ranks')}\n"
    )


def write_housekeeping(emit, housekeeping, error=None):
    if error:
        emit(f"\n## housekeeping: unknown, the query failed ({error})\n")
        return
    emit(f"\n## housekeeping: {len(housekeeping)} jobs still in housekeeping\n")
    write_truncated(
        emit, list(housekeeping.items()), 50, lambda kv: format_housekeeping_row(*kv)
    )


def write_scan_stats(emit, summary):
    emit(
        f"\n## scan stats: {summary['n_jobs_scanned']} jobs "
        f"({summary['n_running']} running, {summary['n_inactive']} inactive), "
        f"{summary['n_jobs_failed']} failed, "
        f"{summary['find_rpcs']} find RPCs "
        f"({summary['find_simple_writer_fallbacks']} fell back to the simple writer), "
        f"mean {summary['find_seconds_mean']}s each, "
        f"{summary['elapsed_seconds']}s total\n"
    )


def write_summary(report, out):
    emit = out.write
    write_header(emit, report)
    write_graph_snapshot(emit, report["graph"])
    write_agfilters(emit, report["agfilter"])
    write_job_classes(emit, report["summary"])
    write_job_table(emit, report["jobs"])
    write_orphans(emit, report["summary"])
    write_unexplained(emit, report["summary"])
    write_housekeeping(
        emit,
        report.get("housekeeping") or {},
        report["meta"].get("housekeeping_error"),
    )
    write_scan_stats(emit, report["summary"])


def parse_args():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "-n",
        "--count",
        type=int,
        default=300,
        help="number of recent inactive jobs to scan (default 300)",
    )
    ap.add_argument(
        "-o",
        "--output",
        default=None,
        help="output file prefix (default flux-rabbit-orphan-scan.<timestamp>); "
        "writes <prefix>.json and <prefix>.txt",
    )
    ap.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help="seconds to sleep between jobs, to pace load on the resource module",
    )
    ap.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="per-RPC timeout in seconds (default 120)",
    )
    ap.add_argument(
        "--settle",
        type=float,
        default=60.0,
        help="jobs inactive for fewer seconds than this are reported but not "
        "counted as orphaned, since their release may still be in flight",
    )
    ap.add_argument(
        "--full-vertices",
        action="store_true",
        help="include full vertex lists for down vertices, all aggregate "
        "filters and running jobs (large)",
    )
    ap.add_argument(
        "--eventlog-all",
        action="store_true",
        help="read the eventlog and R for every scanned job, not only those "
        "with leftover state",
    )
    ap.add_argument(
        "--only-with-R",
        action="store_true",
        help="skip inactive jobs that never ran; they cannot hold allocations",
    )
    ap.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="no progress output on stderr; warnings are still written",
    )
    return ap.parse_args()


def main():
    args = parse_args()
    # progress is INFO and goes to stderr; --quiet drops it but keeps
    # warnings, which report scan failures the caller needs to know about
    logging.basicConfig(format="%(levelname)s - %(message)s")
    LOGGER.setLevel(logging.WARNING if args.quiet else logging.INFO)
    prefix = args.output or (
        f"flux-rabbit-orphan-scan.{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    )
    try:
        report = scan(args)
    except OSError as exc:
        # the global phase (module parameters, the graph snapshots, the
        # job listing) has no partial result to write: say so in one
        # line rather than with a traceback, and use a status distinct
        # from the one that means "the scan ran, some jobs failed"
        LOGGER.error("scan failed: %s", exc)
        return 2
    json_path = f"{prefix}.json"
    txt_path = f"{prefix}.txt"
    with open(json_path, "w") as fp:
        json.dump(report, fp, indent=1, default=str)
    with open(txt_path, "w") as fp:
        write_summary(report, fp)
    LOGGER.info("wrote %s and %s", json_path, txt_path)
    if not args.quiet:
        with open(txt_path) as fp:
            sys.stderr.write(fp.read())
    return 1 if report["summary"]["n_jobs_failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
