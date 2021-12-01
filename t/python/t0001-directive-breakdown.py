#!/usr/bin/env python3

###############################################################
# Copyright 2021 Lawrence Livermore National Security, LLC
# (c.f. AUTHORS, NOTICE.LLNS, COPYING)
#
# This file is part of the Flux resource manager framework.
# For details, see https://github.com/flux-framework.
#
# SPDX-License-Identifier: LGPL-3.0

import unittest
import unittest.mock
from pathlib import Path

import yaml

from pycotap import TAPTestRunner
from flux_k8s import directivebreakdown

YAMLDIR = Path(__file__).resolve().parent.parent / "data" / "breakdown"


def read_yaml_breakdown(*paths):
    breakdowns = []
    for path in paths:
        with open(path) as fd:
            breakdowns.append(yaml.safe_load(fd))
    return breakdowns


class TestDirectiveBreakdowns(unittest.TestCase):
    @unittest.mock.patch("flux_k8s.directivebreakdown.fetch_breakdowns")
    def test_lustre10tb(self, patched_fetch):
        patched_fetch.return_value = read_yaml_breakdown(YAMLDIR / "lustre10tb.yaml")
        resources = []
        directivebreakdown.apply_breakdowns(None, None, resources)
        patched_fetch.assert_called_with(None, None)
        self.assertEqual(len(resources), 3)
        for resource in resources:
            self.assertTrue(resource["type"].startswith("rabbit-"))
            self.assertEqual(resource["count"], 1)
            self.assertEqual(len(resource["with"]), 1)
            self.assertEqual(resource["with"][0]["unit"], "B")
            self.assertGreater(resource["with"][0]["count"], 10e8)

    @unittest.mock.patch("flux_k8s.directivebreakdown.fetch_breakdowns")
    def test_xfs10mb(self, patched_fetch):
        patched_fetch.return_value = read_yaml_breakdown(YAMLDIR / "xfs10mb.yaml")
        for resources in (
            [{"type": "node", "count": 1, "with": [{"type": "slot"}]}],
            [{"type": "slot", "count": 1, "with": []}],
        ):
            with self.subTest(resources=resources):
                # note that if subtests fail, their output doesn't show in TAP
                resources = resources
                directivebreakdown.apply_breakdowns(None, None, resources)
                patched_fetch.assert_called_with(None, None)
                self.assertEqual(len(resources), 1)
                self.assertEqual(resources[0]["type"], "node")
                rabbit = resources[0]["with"][1]
                self.assertEqual(rabbit["type"], "rabbit-xfs")
                self.assertEqual(rabbit["count"], 1)
                self.assertEqual(len(rabbit["with"]), 1)
                self.assertEqual(rabbit["with"][0]["type"], "storage")
                self.assertEqual(rabbit["with"][0]["unit"], "B")
                self.assertEqual(rabbit["with"][0]["count"], int(10e5))

    @unittest.mock.patch("flux_k8s.directivebreakdown.fetch_breakdowns")
    def test_xfs10mb_aggregation(self, patched_fetch):
        patched_fetch.return_value = read_yaml_breakdown(
            YAMLDIR / "xfs10mb.yaml", YAMLDIR / "xfs10mb.yaml"
        )
        resources = [
            {
                "type": "node",
                "count": 1,
                "with": [
                    {"type": "slot"},
                    {
                        "type": "rabbit-xfs",
                        "with": [{"type": "storage", "count": 5e5, "unit": "B"}],
                    },
                ],
            }
        ]
        rabbit = resources[0]["with"][1]
        self.assertEqual(rabbit["with"][0]["count"], int(5e5))
        # each xfs10mb.yaml should add 10e5 to ``rabbit["with"][0]["count"]``
        directivebreakdown.apply_breakdowns(None, None, resources)
        patched_fetch.assert_called_with(None, None)
        self.assertEqual(rabbit["with"][0]["type"], "storage")
        self.assertEqual(rabbit["with"][0]["unit"], "B")
        self.assertEqual(rabbit["with"][0]["count"], int(25e5))

    @unittest.mock.patch("flux_k8s.directivebreakdown.fetch_breakdowns")
    def test_combination_xfs_lustre(self, patched_fetch):
        patched_fetch.return_value = read_yaml_breakdown(
            YAMLDIR / "xfs10mb.yaml", YAMLDIR / "lustre10tb.yaml"
        )
        resources = [{"type": "node", "count": 1, "with": [{"type": "slot"}]}]
        directivebreakdown.apply_breakdowns(None, None, resources)
        patched_fetch.assert_called_with(None, None)
        self.assertEqual(len(resources), 4)
        self.assertEqual(resources[0]["type"], "node")
        rabbit_xfs = resources[0]["with"][1]
        self.assertEqual(rabbit_xfs["type"], "rabbit-xfs")
        self.assertEqual(rabbit_xfs["count"], 1)
        for resource in resources[1:]:
            self.assertTrue(resource["type"].startswith("rabbit-"))
            self.assertEqual(resource["count"], 1)
            self.assertEqual(len(resource["with"]), 1)
            self.assertEqual(resource["with"][0]["unit"], "B")
            self.assertGreater(resource["with"][0]["count"], 10e8)

    @unittest.mock.patch("flux_k8s.directivebreakdown.fetch_breakdowns")
    def test_xfs10mb_no_node_or_slot(self, patched_fetch):
        patched_fetch.return_value = read_yaml_breakdown(YAMLDIR / "xfs10mb.yaml")
        resources = []
        with self.assertRaisesRegex(ValueError, "Neither 'node' nor 'slot'.*"):
            directivebreakdown.apply_breakdowns(None, None, resources)

    @unittest.mock.patch("flux_k8s.directivebreakdown.fetch_breakdowns")
    def test_allocation_bad_label(self, patched_fetch):
        patched_fetch.return_value = read_yaml_breakdown(YAMLDIR / "bad_label.yaml")
        resources = []
        with self.assertRaisesRegex(ValueError, "Unknown label.*"):
            directivebreakdown.apply_breakdowns(None, None, resources)

    @unittest.mock.patch("flux_k8s.directivebreakdown.fetch_breakdowns")
    def test_allocation_bad_kind(self, patched_fetch):
        patched_fetch.return_value = read_yaml_breakdown(YAMLDIR / "bad_kind.yaml")
        with self.assertRaisesRegex(ValueError, "unsupported breakdown kind"):
            directivebreakdown.apply_breakdowns(None, None, None)

    @unittest.mock.patch("flux_k8s.directivebreakdown.fetch_breakdowns")
    def test_bad_existing_units(self, patched_fetch):
        patched_fetch.return_value = read_yaml_breakdown(YAMLDIR / "xfs10mb.yaml")
        resources = [
            {
                "type": "node",
                "count": 1,
                "with": [
                    {"type": "slot"},
                    {
                        "type": "rabbit-xfs",
                        "with": [{"type": "storage", "count": 10e5, "unit": "foobar"}],
                    },
                ],
            }
        ]
        with self.assertRaisesRegex(ValueError, "Unit mismatch"):
            directivebreakdown.apply_breakdowns(None, None, resources)


unittest.main(testRunner=TAPTestRunner())
