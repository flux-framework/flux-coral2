#!/usr/bin/env python3
###############################################################
# Copyright 2026 Lawrence Livermore National Security, LLC
# (c.f. AUTHORS, NOTICE.LLNS, COPYING)
#
# This file is part of the Flux resource manager framework.
# For details, see https://github.com/flux-framework.
#
# SPDX-License-Identifier: LGPL-3.0
###############################################################

"""
Unit tests for the pure parsing, classification and formatting helpers of
flux-rabbit-orphan-scan.

Everything that needs a resource graph is covered end to end against a
real sched-fluxion-resource module by t2004-rabbit-orphan-scan.t.  What
is left here is what a live test cannot reach or cannot pin precisely:
the "simple" writer fallback, the full classify() truth table, and the
wording of the warnings that tell an operator whether to trust the
report.
"""

import copy
import errno
import importlib.util
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from flux.job import JobID
from pycotap import TAPTestRunner

COMMAND = Path(__file__).resolve().parents[2] / "src/cmd/flux-rabbit-orphan-scan.py"


def load_command():
    """Import the command by path; it is installed as flux-rabbit-orphan-scan."""
    spec = importlib.util.spec_from_file_location("rabbit_orphan_scan", COMMAND)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scan = load_command()


def naive_mark_leaves(vertices):
    """The obvious O(n^2) definition of a leaf, as a test oracle."""
    paths = [v["path"] for v in vertices if v.get("path")]
    return [
        bool(v.get("path"))
        and not any(q != v["path"] and q.startswith(v["path"] + "/") for q in paths)
        for v in vertices
    ]


def job(state="INACTIVE", t_inactive=100.0):
    return SimpleNamespace(state=state, t_inactive=t_inactive)


class TestSimpleWriter(unittest.TestCase):
    """
    The JGF writer cannot emit a vertex set with no edges, so find() falls
    back to the "simple" writer.  That output has no rank, type or
    containment path, and these are the only tests of what is inferred
    from it: a live module will not reliably produce the fallback.
    """

    def test_name_with_trailing_digits_yields_type_and_id(self):
        (entry,) = scan.simple_to_entries("      ---------ssd15[793:x]\n")
        metadata = entry["metadata"]
        self.assertEqual(metadata["type"], "ssd")
        self.assertEqual(metadata["id"], 15)
        self.assertEqual(metadata["name"], "ssd15")
        self.assertEqual(metadata["size"], 793)
        self.assertIsNone(metadata["rank"])
        self.assertEqual(metadata["depth"], 3)

    def test_size_is_omitted_when_the_vertex_needs_one_unit(self):
        (entry,) = scan.simple_to_entries("      ---------core0[1:x]\n")
        self.assertNotIn("size", entry["metadata"])

    def test_name_without_trailing_digits_has_no_type(self):
        """A cluster named "hetchy" gives no prefix to guess a type from."""
        (entry,) = scan.simple_to_entries("      ---hetchy[1:x]\n")
        self.assertEqual(entry["metadata"]["type"], "unknown")
        self.assertIsNone(entry["metadata"]["id"])

    def test_unknown_type_is_not_reported_as_a_guess(self):
        (entry,) = scan.simple_to_entries("      ---hetchy[1:x]\n")
        summary = scan.vertex_summary(entry)
        self.assertEqual(summary["type"], "unknown")
        self.assertFalse(summary["type_guessed_from_name"])
        # with no containment path the bare name has to stand in for one
        self.assertEqual(summary["path"], "hetchy")

    def test_guessed_type_is_flagged_as_a_guess(self):
        (entry,) = scan.simple_to_entries("      ---------ssd15[793:x]\n")
        self.assertTrue(scan.vertex_summary(entry)["type_guessed_from_name"])

    def test_unparsable_lines_are_skipped(self):
        text = "not a vertex\n      ---------ssd15[793:x]\n\n"
        self.assertEqual(len(scan.simple_to_entries(text)), 1)
        self.assertEqual(scan.simple_to_entries(""), [])
        self.assertEqual(scan.simple_to_entries(None), [])


class TestVertexSummary(unittest.TestCase):
    def test_core_vertices_have_no_name_of_their_own(self):
        """Real fluxion emits a name for node vertices but not for cores."""
        summary = scan.vertex_summary(
            {
                "id": "13",
                "metadata": {
                    "type": "core",
                    "id": 0,
                    "rank": 1,
                    "paths": {"containment": "/cluster0/compute-01/core0"},
                },
            }
        )
        self.assertEqual(summary["name"], "core0")
        self.assertEqual(summary["type"], "core")
        self.assertEqual(summary["rank"], 1)
        self.assertEqual(summary["path"], "/cluster0/compute-01/core0")

    def test_basename_is_preferred_over_type_when_building_a_name(self):
        summary = scan.vertex_summary(
            {
                "id": "12",
                "metadata": {
                    "type": "node",
                    "basename": "compute-",
                    "name": "compute-01",
                    "id": 1,
                    "rank": 1,
                    "paths": {"containment": "/cluster0/compute-01"},
                },
            }
        )
        self.assertEqual(summary["name"], "compute-01")


class TestMarkLeaves(unittest.TestCase):
    """
    find() returns the ancestors of every match, so only vertices with no
    returned descendant certainly hold the state themselves.
    """

    def leaves(self, paths):
        vertices = scan.mark_leaves([{"path": p} for p in paths])
        return {v["path"] for v in vertices if v["leaf"]}

    def test_ancestors_of_a_match_are_not_leaves(self):
        self.assertEqual(
            self.leaves(
                ["/cluster0", "/cluster0/compute-01", "/cluster0/compute-01/core0"]
            ),
            {"/cluster0/compute-01/core0"},
        )

    def test_a_sibling_is_not_mistaken_for_a_descendant(self):
        """compute-1 is a string prefix of compute-10 but not its ancestor."""
        self.assertEqual(
            self.leaves(["/cluster0/compute-1", "/cluster0/compute-10"]),
            {"/cluster0/compute-1", "/cluster0/compute-10"},
        )

    def test_a_gap_in_the_returned_ancestry_still_marks_the_ancestor(self):
        """The intermediate rack vertex need not be present in the result."""
        self.assertEqual(
            self.leaves(["/cluster0", "/cluster0/rack1/compute-01"]),
            {"/cluster0/rack1/compute-01"},
        )

    def test_pathless_vertices_are_never_leaves(self):
        vertices = scan.mark_leaves([{"path": None}, {"path": ""}])
        self.assertEqual([v["leaf"] for v in vertices], [False, False])

    def test_matches_the_naive_definition_on_a_realistic_graph(self):
        paths = ["/cluster0"]
        for node in range(12):
            paths.append(f"/cluster0/compute-{node}")
            paths.extend(f"/cluster0/compute-{node}/core{c}" for c in range(8))
        paths.extend(["/cluster0/rack1/chassis2/ssd3", "hetchy"])
        vertices = [{"path": p} for p in paths]
        expected = naive_mark_leaves(vertices)
        scan.mark_leaves(vertices)
        self.assertEqual([v["leaf"] for v in vertices], expected)


class TestAgfilter(unittest.TestCase):
    def test_used_and_total_are_parsed(self):
        self.assertEqual(
            scan.parse_agfilter({"core": "used: 10, total: 20"}),
            {"core": {"used": 10, "total": 20}},
        )

    def test_unparsable_text_is_preserved_verbatim(self):
        """Keep what the module said rather than inventing a count."""
        self.assertEqual(
            scan.parse_agfilter({"core": "surprising"}), {"core": {"raw": "surprising"}}
        )

    def test_a_vertex_with_only_raw_counts_does_not_read_as_in_use(self):
        vertex = {"agfilter": scan.parse_agfilter({"core": "surprising"})}
        self.assertFalse(scan.agfilter_in_use(vertex))

    def test_a_negative_used_count_reads_as_in_use(self):
        """A negative count is itself corruption worth surfacing."""
        vertex = {"agfilter": scan.parse_agfilter({"core": "used: -1, total: 10"})}
        self.assertTrue(scan.agfilter_in_use(vertex))

    def test_a_zero_used_count_does_not_read_as_in_use(self):
        vertex = {"agfilter": scan.parse_agfilter({"core": "used: 0, total: 10"})}
        self.assertFalse(scan.agfilter_in_use(vertex))

    def test_counts_are_formatted_only_when_present(self):
        formatted = scan.format_agfilter_counts(
            {
                "core": {"used": 1, "total": 2},
                "node": {"used": 0, "total": 0},
                "ssd": {"raw": "surprising"},
            }
        )
        self.assertEqual(formatted, "core=1/2")


class TestClassify(unittest.TestCase):
    """
    The truth table of classify().  t2004 covers the classes that a live
    module can be driven into; these cover the rest, and pin the exact
    conditions that separate a real orphan from a legitimate hold.
    """

    def classify(self, state="INACTIVE", graph=True, status=None, **kwargs):
        kwargs.setdefault("evlog", None)
        kwargs.setdefault("hk", None)
        kwargs.setdefault("recent", False)
        return scan.classify(
            job(state=state),
            {"jobid-alloc": []} if graph else None,
            {"status": status} if status else None,
            kwargs["evlog"],
            kwargs["hk"],
            kwargs["recent"],
        )

    def test_running_job_with_state_is_legitimate(self):
        self.assertEqual(self.classify(state="RUN", status="ALLOCATED"), "running")
        self.assertEqual(self.classify(state="CLEANUP", status="ALLOCATED"), "running")

    def test_running_job_the_module_does_not_know(self):
        self.assertEqual(
            self.classify(state="RUN", status=None), "running-module-unknown"
        )

    def test_running_job_with_nothing_in_the_graph(self):
        self.assertEqual(
            self.classify(state="RUN", graph=False, status="ALLOCATED"),
            "running-no-graph-state",
        )

    def test_inactive_job_with_nothing_left(self):
        self.assertEqual(self.classify(graph=False), "inactive-and-clean")

    def test_module_record_without_graph_state_is_still_clean(self):
        """graph_state is checked first: no vertices, nothing to reclaim."""
        self.assertEqual(
            self.classify(graph=False, status="ALLOCATED"), "inactive-and-clean"
        )

    def test_allocated_and_clean_in_core_is_an_orphan(self):
        evlog = {"has_clean": True}
        self.assertEqual(
            self.classify(status="ALLOCATED", evlog=evlog),
            "orphan-module-still-allocated",
        )

    def test_allocated_while_in_housekeeping_is_a_legitimate_hold(self):
        evlog = {"has_clean": True}
        self.assertEqual(
            self.classify(status="ALLOCATED", evlog=evlog, hk={"t_start": 1.0}),
            "held-pending-final-free",
        )

    def test_allocated_without_a_clean_event_is_a_legitimate_hold(self):
        self.assertEqual(
            self.classify(status="ALLOCATED", evlog={"has_clean": False}),
            "held-pending-final-free",
        )

    def test_no_module_record_with_graph_state_is_a_fluxion_leak(self):
        self.assertEqual(self.classify(status=None), "orphan-module-no-record")

    def test_module_error_is_reported(self):
        self.assertEqual(self.classify(status="ERROR"), "module-error")

    def test_reserved_for_an_inactive_job(self):
        self.assertEqual(self.classify(status="RESERVED"), "reservation")

    def test_an_unknown_status_is_surfaced_rather_than_swallowed(self):
        self.assertEqual(self.classify(status="PARTIAL"), "unexpected-PARTIAL")

    def test_recent_jobs_are_prefixed(self):
        self.assertEqual(
            self.classify(status="ERROR", recent=True), "recent-module-error"
        )
        self.assertEqual(
            self.classify(status=None, recent=True), "recent-orphan-module-no-record"
        )

    def test_a_legitimate_hold_is_not_prefixed_when_recent(self):
        """It is already excused; "recent-" would only muddy the class."""
        self.assertEqual(
            self.classify(
                status="ALLOCATED", evlog={"has_clean": True}, hk={}, recent=True
            ),
            "held-pending-final-free",
        )

    def test_every_orphan_class_is_counted_as_an_orphan(self):
        """ORPHAN_CLASSES drives the totals, so it must stay in step."""
        for classification in ("orphan-module-no-record", "module-error"):
            self.assertIn(classification, scan.ORPHAN_CLASSES)
        self.assertIn("orphan-module-still-allocated", scan.ORPHAN_CLASSES)
        self.assertNotIn("held-pending-final-free", scan.ORPHAN_CLASSES)
        self.assertNotIn("reservation", scan.ORPHAN_CLASSES)


class TestPerJobAgfilter(unittest.TestCase):
    """A failed diagnostic must preserve the state used to identify orphans."""

    def scan_job(self, agfilter_error=None, predicate_error=None):
        entry = {
            "id": "13",
            "metadata": {
                "type": "core",
                "rank": 0,
                "paths": {"containment": "/cluster0/node0/core0"},
                "agfilter": {"core": "used:1, total:2"},
            },
        }

        def find(criteria):
            if "agfilter=true" in criteria and agfilter_error:
                raise agfilter_error
            if criteria == "jobid-tag=1" and predicate_error:
                raise predicate_error
            return [] if criteria == "jobid-reserved=1" else [entry]

        rmod = SimpleNamespace(find=find, info=lambda jid: None)
        scanned_job = SimpleNamespace(
            id=JobID(1),
            userid=0,
            state="INACTIVE",
            t_submit=1.0,
            t_run=2.0,
            t_cleanup=3.0,
            t_inactive=4.0,
        )
        args = SimpleNamespace(eventlog_all=False, settle=0, full_vertices=False)
        with patch.object(scan, "eventlog_summary", return_value=None), patch.object(
            scan, "job_R_summary", return_value=None
        ):
            record, state = scan.scan_job(None, rmod, scanned_job, {}, args, 100.0)
        return scanned_job, record, state

    def test_missing_ancestor_span_preserves_orphan_evidence(self):
        error = OSError(errno.ENOENT, "span missing in job2span for ancestor")
        with self.assertLogs(scan.LOGGER, level="WARNING"):
            scanned_job, record, state = self.scan_job(agfilter_error=error)
        self.assertEqual(record["class"], "orphan-module-no-record")
        self.assertIn("span missing", record["agfilter_error"])
        self.assertIsNone(record["graph_state"]["agfilter-per-job"])
        for pred in ("jobid-alloc", "jobid-span", "jobid-tag"):
            self.assertEqual(record["graph_state"][pred]["n_vertices"], 1)
        totals = scan.ScanTotals()
        totals.add(scanned_job, record, state)
        self.assertEqual(totals.classes["scan-error"], 0)
        self.assertEqual(len(totals.orphaned_vertices), 1)
        self.assertEqual(len(totals.orphaned_residue), 1)
        report = {
            "meta": {
                "started": "now",
                "hostname": "test",
                "flux_core_version": "0",
                "instance_size": 1,
            },
            "summary": {"n_jobs_failed": 0},
            "jobs": [record],
        }
        out = io.StringIO()
        scan.write_header(out.write, report)
        self.assertIn("span missing", out.getvalue())
        self.assertIn("orphan totals were preserved", out.getvalue())

    def test_successful_diagnostic_keeps_filter_counts(self):
        _, record, _ = self.scan_job()
        self.assertIsNone(record["agfilter_error"])
        diagnostic = record["graph_state"]["agfilter-per-job"]
        self.assertEqual(diagnostic["n_vertices"], 1)
        self.assertEqual(diagnostic["vertices"][0]["agfilter"]["core"]["used"], 1)

    def test_required_predicate_errors_still_fail_the_job_scan(self):
        with self.assertRaises(OSError):
            self.scan_job(predicate_error=OSError(errno.EIO, "find failed"))


class TestEventlogSummary(unittest.TestCase):
    """Parses real eventlog lines through flux.eventlog.EventLogEvent."""

    def summarize(self, lines):
        import flux.job

        original = flux.job.job_kvs_lookup
        flux.job.job_kvs_lookup = lambda *a, **kw: {"eventlog": "\n".join(lines)}
        try:
            return scan.eventlog_summary(None, 1)
        finally:
            flux.job.job_kvs_lookup = original

    def test_a_completed_job_has_alloc_free_and_clean(self):
        summary = self.summarize(
            [
                '{"timestamp":1.0,"name":"alloc"}',
                '{"timestamp":2.0,"name":"release",'
                '"context":{"ranks":"all","final":true}}',
                '{"timestamp":3.0,"name":"free"}',
                '{"timestamp":4.0,"name":"clean"}',
            ]
        )
        self.assertTrue(summary["has_alloc"])
        self.assertTrue(summary["has_free"])
        self.assertTrue(summary["has_clean"])
        self.assertFalse(summary["exception"])
        self.assertEqual(summary["n_release"], 1)
        self.assertEqual(
            summary["releases"], [{"t": 2.0, "ranks": "all", "final": True}]
        )

    def test_an_exception_is_recorded(self):
        summary = self.summarize(
            [
                '{"timestamp":1.0,"name":"exception",'
                '"context":{"type":"cancel","severity":0}}',
                '{"timestamp":2.0,"name":"clean"}',
            ]
        )
        self.assertTrue(summary["exception"])
        self.assertFalse(summary["has_alloc"])

    def test_a_malformed_line_does_not_lose_the_rest(self):
        """EventLogEvent raises JSONDecodeError, not a generic error."""
        summary = self.summarize(
            ["this is not an event", '{"timestamp":1.0,"name":"clean"}']
        )
        self.assertTrue(summary["has_clean"])

    def test_a_job_with_no_eventlog_has_no_summary(self):
        import flux.job

        original = flux.job.job_kvs_lookup
        flux.job.job_kvs_lookup = lambda *a, **kw: None
        try:
            self.assertIsNone(scan.eventlog_summary(None, 1))
        finally:
            flux.job.job_kvs_lookup = original


class TestFormatting(unittest.TestCase):
    """The summary is what an operator acts on, so pin its warnings."""

    def render(self, writer, *args):
        out = io.StringIO()
        writer(out.write, *args)
        return out.getvalue()

    def report(self, **summary):
        base = {
            "n_jobs_failed": 0,
            "classes": {},
            "orphaned_vertices": [],
            "orphaned_vertices_by_type": {},
            "orphaned_leaf_by_type": {},
            "held_by_core_vertices_by_type": {},
            "allocated_unexplained_by_scanned_jobs": {
                "n_vertices": 0,
                "n_leaf": 0,
                "leaf_by_type": {},
            },
        }
        base.update(summary)
        return {
            "meta": {
                "started": "now",
                "hostname": "test",
                "flux_core_version": "0",
                "instance_size": 2,
                "housekeeping_error": None,
            },
            "module": {"params": {}},
            "summary": base,
        }

    def test_a_clean_scan_warns_about_nothing(self):
        text = self.render(scan.write_header, self.report())
        self.assertNotIn("WARNING", text)

    def test_failed_job_scans_warn_that_the_totals_are_incomplete(self):
        text = self.render(scan.write_header, self.report(n_jobs_failed=3))
        self.assertIn("scan incomplete: 3 job scans failed", text)
        self.assertIn("orphan totals exclude those jobs", text)

    def test_a_failed_housekeeping_query_warns_against_trusting_orphans(self):
        report = self.report()
        report["meta"]["housekeeping_error"] = "Connection timed out"
        text = self.render(scan.write_header, report)
        self.assertIn("job-manager.stats-get RPC failed", text)
        self.assertIn("Connection timed out", text)
        self.assertIn("may simply be in housekeeping", text)

    def test_unexplained_allocations_suggest_a_larger_window(self):
        summary = self.report(
            allocated_unexplained_by_scanned_jobs={
                "n_vertices": 4,
                "n_leaf": 2,
                "leaf_by_type": {"core": 2},
            }
        )["summary"]
        text = self.render(scan.write_unexplained, summary)
        self.assertIn("rerun with a larger --count", text)
        self.assertNotIn("scan incomplete", text)

    def test_unexplained_allocations_blame_failed_scans_first(self):
        """Widening the window is the wrong advice while scans are failing."""
        summary = self.report(
            n_jobs_failed=1,
            allocated_unexplained_by_scanned_jobs={
                "n_vertices": 4,
                "n_leaf": 2,
                "leaf_by_type": {"core": 2},
            },
        )["summary"]
        text = self.render(scan.write_unexplained, summary)
        self.assertIn("may belong to jobs whose scans failed", text)
        self.assertNotIn("rerun with a larger --count", text)

    def test_no_unexplained_allocations_gives_no_advice(self):
        text = self.render(scan.write_unexplained, self.report()["summary"])
        self.assertNotIn("rerun", text)

    def test_residue_summary_explains_that_counts_can_overlap(self):
        summary = self.report(orphaned_residue_by_type={"cluster": 1})["summary"]
        text = self.render(scan.write_orphans, summary)
        self.assertIn("vertices returned by span/tag/reservation queries", text)
        self.assertIn("may overlap allocation totals", text)
        self.assertIn("do not add the counts", text)
        self.assertNotIn("not allocated", text)

    def test_housekeeping_failure_is_reported_as_unknown_not_as_empty(self):
        text = self.render(scan.write_housekeeping, {}, "Connection timed out")
        self.assertIn("unknown", text)
        self.assertNotIn("0 jobs still in housekeeping", text)

    def test_a_scan_error_row_shows_the_error(self):
        row = scan.format_job_row(
            {
                "class": "scan-error",
                "job": {"f58": "f1"},
                "error": "TimeoutError: timed out",
            }
        )
        self.assertIn("scan-error", row)
        self.assertIn("TimeoutError: timed out", row)

    def test_truncation_reports_how_much_was_left_out(self):
        out = io.StringIO()
        scan.write_truncated(out.write, list(range(10)), 3, lambda i: f"{i}\n")
        self.assertIn("... 7 more (see JSON)", out.getvalue())

    def test_nothing_is_truncated_at_the_limit(self):
        out = io.StringIO()
        scan.write_truncated(out.write, list(range(3)), 3, lambda i: f"{i}\n")
        self.assertNotIn("more", out.getvalue())

    def test_eventlog_flags_are_compact(self):
        self.assertEqual(scan.eventlog_flags(None), "-----")
        self.assertEqual(
            scan.eventlog_flags(
                {
                    "has_alloc": True,
                    "n_release": 2,
                    "has_free": True,
                    "has_clean": True,
                    "exception": False,
                }
            ),
            "AR2FC-",
        )


class TestScanErrorRecord(unittest.TestCase):
    """A job that cannot be scanned must cost us that job, not the scan."""

    def broken_job(self):
        """Only the id is readable; every other JobInfo field is missing."""
        return SimpleNamespace(id=JobID(1))

    def test_an_unusable_jobinfo_still_yields_a_record(self):
        record = scan.scan_error_record(self.broken_job(), RuntimeError("boom"))
        self.assertEqual(record["class"], "scan-error")
        self.assertEqual(record["error"], "RuntimeError: boom")
        self.assertEqual(record["job"]["f58"], JobID(1).f58)
        self.assertEqual(record["job"]["id"], 1)
        self.assertFalse(record["recent"])
        self.assertIsNone(record["graph_state"])

    def test_failed_scans_are_counted_and_hold_no_vertices(self):
        totals = scan.ScanTotals()
        record = scan.scan_error_record(self.broken_job(), RuntimeError("boom"))
        totals.add(self.broken_job(), record, None)
        self.assertEqual(totals.classes["scan-error"], 1)
        self.assertEqual(totals.orphaned_vertices, [])
        # nothing was explained, so its allocations stay unexplained
        self.assertEqual(totals.explained_alloc_paths, set())


class TestOrphanResidue(unittest.TestCase):
    """
    Residue queries return overlapping vertices and ancestor context.
    Keep each identifiable vertex once per job, retaining its predicates
    even when it also appears in the allocation query.
    """

    def graph_state(self, alloc=(), span=(), tag=(), reserved=()):
        def vertices(entries):
            return scan.mark_leaves(
                [
                    {"type": "core", "rank": 0, **entry}
                    if isinstance(entry, dict)
                    else {"path": entry, "type": "core", "rank": 0}
                    for entry in entries
                ]
            )

        return {
            "jobid-alloc": vertices(alloc),
            "jobid-reserved": vertices(reserved),
            "jobid-span": vertices(span),
            "jobid-tag": vertices(tag),
        }

    def totals_for(self, graph_state, classification="orphan-module-no-record"):
        totals = scan.ScanTotals()
        totals.add(
            SimpleNamespace(id=JobID(1)),
            {"class": classification},
            graph_state,
        )
        return totals

    def test_span_only_residue_is_tallied_outside_the_orphan_list(self):
        totals = self.totals_for(self.graph_state(span=["/c/r0/core0"]))
        self.assertEqual(totals.orphaned_vertices, [])
        self.assertEqual(len(totals.orphaned_residue), 1)
        self.assertEqual(totals.orphaned_residue[0]["predicates"], ["jobid-span"])
        self.assertEqual(totals.orphaned_residue[0]["class"], "orphan-module-no-record")

    def test_residue_overlapping_an_allocation_retains_its_predicates(self):
        path = "/c/r0/core0"
        totals = self.totals_for(
            self.graph_state(alloc=[path], span=[path], tag=[path])
        )
        self.assertEqual(len(totals.orphaned_vertices), 1)
        self.assertEqual(len(totals.orphaned_residue), 1)
        self.assertEqual(
            totals.orphaned_residue[0]["predicates"], ["jobid-span", "jobid-tag"]
        )

    def test_allocation_ancestors_do_not_suppress_residue(self):
        state = self.graph_state(
            alloc=["/cluster0", "/cluster0/ssd0"], span=["/cluster0"]
        )
        self.assertFalse(state["jobid-alloc"][0]["leaf"])
        totals = self.totals_for(state)
        self.assertEqual([v["path"] for v in totals.orphaned_residue], ["/cluster0"])
        self.assertEqual(totals.orphaned_residue[0]["predicates"], ["jobid-span"])

    def test_one_vertex_returned_by_three_queries_is_counted_once(self):
        vertex = {"uniq_id": "13", "path": "/c/r0/core0"}
        totals = self.totals_for(
            self.graph_state(span=[vertex], tag=[vertex], reserved=[vertex])
        )
        self.assertEqual(len(totals.orphaned_residue), 1)
        self.assertEqual(
            totals.orphaned_residue[0]["predicates"],
            ["jobid-reserved", "jobid-span", "jobid-tag"],
        )
        summary = scan.build_summary(
            totals,
            [],
            {"n_jobs_scanned": 1, "n_running": 0, "n_inactive": 1},
            scan.ResourceModule(None, 1.0),
            SimpleNamespace(full_vertices=False),
            0.0,
        )
        self.assertEqual(summary["orphaned_residue_by_type"], {"core": 1})

    def test_distinct_vertex_ids_with_the_same_name_remain_separate(self):
        vertices = [
            {"uniq_id": "13", "name": "core0", "path": "core0"},
            {"uniq_id": "14", "name": "core0", "path": "core0"},
        ]
        totals = self.totals_for(self.graph_state(span=vertices, tag=vertices))
        self.assertEqual(len(totals.orphaned_residue), 2)
        self.assertEqual({v["uniq_id"] for v in totals.orphaned_residue}, {"13", "14"})
        self.assertTrue(
            all(
                v["predicates"] == ["jobid-span", "jobid-tag"]
                for v in totals.orphaned_residue
            )
        )

    def test_containment_paths_identify_vertices_when_ids_are_missing(self):
        vertices = [
            {"name": "core0", "path": "/c/r0/core0"},
            {"name": "core0", "path": "/c/r1/core0"},
        ]
        totals = self.totals_for(self.graph_state(span=vertices, tag=vertices))
        self.assertEqual(len(totals.orphaned_residue), 2)
        self.assertTrue(
            all(
                v["predicates"] == ["jobid-span", "jobid-tag"]
                for v in totals.orphaned_residue
            )
        )

    def test_the_same_vertex_for_two_jobs_keeps_separate_records(self):
        state = self.graph_state(span=["/c/r0/core0"], tag=["/c/r0/core0"])
        totals = self.totals_for(state)
        totals.add(
            SimpleNamespace(id=JobID(2)), {"class": "orphan-module-no-record"}, state
        )
        self.assertEqual(len(totals.orphaned_residue), 2)
        self.assertEqual(
            {v["jobid"] for v in totals.orphaned_residue}, {JobID(1).f58, JobID(2).f58}
        )

    def test_ambiguous_simple_writer_vertices_are_not_merged(self):
        vertex = {
            "uniq_id": None,
            "name": "core0",
            "path": "core0",
            "type_guessed_from_name": True,
            "rank": None,
        }
        totals = self.totals_for(self.graph_state(span=[vertex, vertex], tag=[vertex]))
        self.assertEqual(len(totals.orphaned_residue), 3)
        self.assertEqual(
            [v["predicates"] for v in totals.orphaned_residue],
            [["jobid-span"], ["jobid-span"], ["jobid-tag"]],
        )

    def test_merged_leaf_flags_do_not_change_the_query_results(self):
        state = self.graph_state(span=["/cluster0"], tag=["/cluster0/ssd0"])
        original = copy.deepcopy(state)
        self.assertTrue(state["jobid-span"][0]["leaf"])
        totals = self.totals_for(state)
        self.assertEqual(
            {v["path"]: v["leaf"] for v in totals.orphaned_residue},
            {"/cluster0": False, "/cluster0/ssd0": True},
        )
        self.assertEqual(state, original)

    def test_a_held_job_contributes_no_residue(self):
        totals = self.totals_for(
            self.graph_state(span=["/c/r0/core0"]),
            classification="held-pending-final-free",
        )
        self.assertEqual(totals.orphaned_residue, [])

    def test_a_recent_orphan_contributes_no_residue(self):
        totals = self.totals_for(
            self.graph_state(span=["/c/r0/core0"]),
            classification="recent-orphan-module-no-record",
        )
        self.assertEqual(totals.orphaned_residue, [])


class TestMainExitStatus(unittest.TestCase):
    """
    The exit status is the contract a cron job or a wrapper script reads,
    so pin it here.  t2004 drives the exit-2 path against a live module;
    reaching exit 1 needs a job scan to fail mid-scan, which a live module
    will not do on demand, so scan() is stubbed instead.
    """

    def run_main(self, stub, extra_argv=()):
        """Run main() with scan() replaced by stub, in a scratch directory."""
        original_scan, original_argv = scan.scan, sys.argv
        cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as tmp:
            scan.scan = stub
            sys.argv = ["flux-rabbit-orphan-scan", "-q", "-o", "out", *extra_argv]
            try:
                os.chdir(tmp)
                status = scan.main()
                written = sorted(p.name for p in Path(tmp).iterdir())
                text = Path(tmp, "out.txt").read_text() if "out.txt" in written else ""
            finally:
                os.chdir(cwd)
                scan.scan, sys.argv = original_scan, original_argv
        return status, written, text

    def run_with_report(self, report, extra_argv=()):
        return self.run_main(lambda args: report, extra_argv)

    def report(self, n_jobs_failed, jobs=()):
        """A report shaped by the real helpers, not hand-written JSON."""
        totals = scan.ScanTotals()
        for record in jobs:
            totals.add(SimpleNamespace(id=JobID(1)), record, None)
        summary = scan.build_summary(
            totals,
            [],
            {"n_jobs_scanned": len(jobs), "n_running": 0, "n_inactive": len(jobs)},
            scan.ResourceModule(None, 1.0),
            SimpleNamespace(full_vertices=False),
            0.0,
        )
        # build_summary derives this from the scan-error tally; assert that
        # rather than overwriting it, so the two cannot drift apart
        self.assertEqual(summary["n_jobs_failed"], n_jobs_failed)
        return {
            "meta": {
                "started": "now",
                "hostname": "test",
                "flux_core_version": "0",
                "instance_size": 2,
                "housekeeping_error": None,
            },
            "module": {"params": {}},
            "graph": {
                key: scan.vertex_set_summary([], False)
                for key in ("allocated", "reserved", "down")
            },
            "agfilter": {"n_filter_vertices": 0, "nonzero": [], "all": None},
            "housekeeping": {},
            "jobs": list(jobs),
            "summary": summary,
        }

    def failed_job(self):
        return scan.scan_error_record(
            SimpleNamespace(id=JobID(1)), TimeoutError("timed out")
        )

    def test_a_clean_scan_exits_0(self):
        status, written, _ = self.run_with_report(self.report(0))
        self.assertEqual(status, 0)
        self.assertEqual(written, ["out.json", "out.txt"])

    def test_a_failed_job_scan_exits_1_but_still_writes_both_files(self):
        """Exit 1 means partial results, so they must survive on disk."""
        status, written, text = self.run_with_report(
            self.report(1, [self.failed_job()])
        )
        self.assertEqual(status, 1)
        self.assertEqual(written, ["out.json", "out.txt"])
        self.assertIn("scan incomplete: 1 job scans failed", text)
        self.assertIn("TimeoutError: timed out", text)

    def test_the_whole_report_is_still_written_when_a_job_failed(self):
        """A failed job must not cost the sections it had no part in."""
        _, _, text = self.run_with_report(self.report(1, [self.failed_job()]))
        for section in ("graph snapshot", "job classification", "orphaned vertices"):
            self.assertIn(section, text)

    def test_an_unreachable_module_exits_2_and_writes_nothing(self):
        def fail(args):
            raise OSError("Connection timed out")

        status, written, _ = self.run_main(fail)
        self.assertEqual(status, 2)
        self.assertEqual(written, [])

    def test_more_than_one_failed_scan_is_counted(self):
        jobs = [self.failed_job(), self.failed_job()]
        status, _, text = self.run_with_report(self.report(2, jobs))
        self.assertEqual(status, 1)
        self.assertIn("scan incomplete: 2 job scans failed", text)


if __name__ == "__main__":
    unittest.main(testRunner=TAPTestRunner())
