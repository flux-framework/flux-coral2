#!/usr/bin/env python3

###############################################################
# Copyright 2025 Lawrence Livermore National Security, LLC
# (c.f. AUTHORS, NOTICE.LLNS, COPYING)
#
# This file is part of the Flux resource manager framework.
# For details, see https://github.com/flux-framework.
#
# SPDX-License-Identifier: LGPL-3.0
###############################################################

import unittest
import unittest.mock
from pathlib import Path
import math

import yaml

from pycotap import TAPTestRunner
from flux_k8s import directivebreakdown
from flux_k8s.directivebreakdown import ResourceLimits

YAMLDIR = Path(__file__).resolve().parent.parent / "data" / "breakdown"


def read_yaml_breakdown(*paths):
    breakdowns = []
    for path in paths:
        with open(path) as fd:
            breakdowns.append(yaml.safe_load(fd))
    return breakdowns


class TestResourceLimits(unittest.TestCase):
    def setUp(self):
        ResourceLimits.lustre = None
        ResourceLimits.xfs = None
        ResourceLimits.xfs2 = None
        ResourceLimits.raw = None

    def test_lustre(self):
        limits = ResourceLimits()
        ResourceLimits.lustre = 100
        limits.increment("mdt", 200)
        limits.increment("xfs", 200)
        limits.validate(1)
        limits.increment("ost", 200)
        with self.assertRaisesRegex(ValueError, "max is 100 GiB per node"):
            limits.validate(1)
        limits.validate(3)
        limits.increment("ost", 200)
        with self.assertRaisesRegex(ValueError, "max is 100 GiB per node"):
            limits.validate(3)

    def test_xfs(self):
        limits = ResourceLimits()
        ResourceLimits.xfs = 50
        limits.increment("ost", 200)
        limits.increment("gfs2", 200)
        limits.validate(1)
        limits.increment("xfs", 51)
        with self.assertRaisesRegex(ValueError, "max is 50 GiB per node"):
            limits.validate(1)
        with self.assertRaisesRegex(ValueError, "max is 50 GiB per node"):
            limits.validate(500)

    def test_unrecognized_type(self):
        limits = ResourceLimits()
        with self.assertRaises(AttributeError):
            limits.increment("foo", 5)

    def test_combined(self):
        limits = ResourceLimits()
        ResourceLimits.lustre = 300
        ResourceLimits.xfs = 400
        limits.increment("mdt", 200)
        limits.increment("xfs", 200)
        limits.validate(1)
        limits.increment("ost", 200)
        limits.validate(1)
        limits.increment("ost", 200)
        with self.assertRaisesRegex(ValueError, "max is 300 GiB per node"):
            limits.validate(1)
        limits.validate(3)
        limits.increment("ost", 600)
        with self.assertRaisesRegex(ValueError, "max is 300 GiB per node"):
            limits.validate(3)
        limits.increment("xfs", 600)
        with self.assertRaisesRegex(ValueError, "max is 400 GiB per node"):
            limits.validate(500)


class TestDirectiveBreakdowns(unittest.TestCase):
    @unittest.mock.patch("flux_k8s.directivebreakdown.fetch_breakdowns")
    def test_lustre10tb(self, patched_fetch):
        patched_fetch.return_value = read_yaml_breakdown(YAMLDIR / "lustre10tb.yaml")
        for nodecount in (4, 6, 8):
            resources = [{"type": "node", "count": nodecount}]
            new_resources = directivebreakdown.apply_breakdowns(
                None, None, resources, 1
            )
            patched_fetch.assert_called_with(None, None)
            self.assertEqual(len(new_resources), 1)
            slot = new_resources[0]
            self.assertEqual(slot["type"], "slot")
            self.assertEqual(slot["count"], nodecount)
            self.assertEqual(len(slot["with"]), 2)
            self.assertEqual(slot["with"][0]["type"], "node")
            self.assertEqual(slot["with"][0]["count"], 1)
            ssds = slot["with"][1]
            self.assertEqual(ssds["type"], "ssd")
            self.assertEqual(ssds["count"], 10241 // nodecount)

    @unittest.mock.patch("flux_k8s.directivebreakdown.fetch_breakdowns")
    def test_xfs10gb(self, patched_fetch):
        patched_fetch.return_value = read_yaml_breakdown(YAMLDIR / "xfs10gb.yaml")
        for nodecount in (4, 6, 8):
            resources = [{"type": "node", "count": nodecount}]
            new_resources = directivebreakdown.apply_breakdowns(
                None, None, resources, 1
            )
            patched_fetch.assert_called_with(None, None)
            self.assertEqual(len(new_resources), 1)
            slot = new_resources[0]
            self.assertEqual(slot["type"], "slot")
            self.assertEqual(slot["count"], nodecount)
            self.assertEqual(len(slot["with"]), 2)
            self.assertEqual(slot["with"][0]["type"], "node")
            self.assertEqual(slot["with"][0]["count"], 1)
            ssds = slot["with"][1]
            self.assertEqual(ssds["type"], "ssd")
            self.assertEqual(ssds["count"], 10)

    @unittest.mock.patch("flux_k8s.directivebreakdown.fetch_breakdowns")
    def test_xfs10gb_aggregation(self, patched_fetch):
        patched_fetch.return_value = read_yaml_breakdown(
            YAMLDIR / "xfs10gb.yaml", YAMLDIR / "xfs10gb.yaml"
        )
        for nodecount in (4, 6, 8):
            resources = [{"type": "node", "count": nodecount}]
            new_resources = directivebreakdown.apply_breakdowns(
                None, None, resources, 1
            )
            patched_fetch.assert_called_with(None, None)
            self.assertEqual(len(new_resources), 1)
            slot = new_resources[0]
            self.assertEqual(slot["type"], "slot")
            self.assertEqual(slot["count"], nodecount)
            self.assertEqual(len(slot["with"]), 2)
            self.assertEqual(slot["with"][0]["type"], "node")
            self.assertEqual(slot["with"][0]["count"], 1)
            ssds = slot["with"][1]
            self.assertEqual(ssds["type"], "ssd")
            self.assertEqual(ssds["count"], 20)

    @unittest.mock.patch("flux_k8s.directivebreakdown.fetch_breakdowns")
    def test_combination_xfs_lustre(self, patched_fetch):
        patched_fetch.return_value = read_yaml_breakdown(
            YAMLDIR / "xfs10gb.yaml", YAMLDIR / "lustre10tb.yaml"
        )
        resources = [{"type": "node", "count": 1, "with": [{"type": "slot"}]}]
        new_resources = directivebreakdown.apply_breakdowns(None, None, resources, 1)
        patched_fetch.assert_called_with(None, None)
        self.assertEqual(len(new_resources), 1)
        slot = new_resources[0]
        self.assertEqual(slot["type"], "slot")
        self.assertEqual(slot["count"], 1)
        self.assertEqual(len(slot["with"]), 2)
        self.assertEqual(slot["with"][0]["type"], "node")
        self.assertEqual(slot["with"][0]["count"], 1)
        ssds = slot["with"][1]
        self.assertEqual(ssds["type"], "ssd")
        self.assertEqual(ssds["count"], 10241 + 10)

    @unittest.mock.patch("flux_k8s.directivebreakdown.fetch_breakdowns")
    def test_bad_resources(self, patched_fetch):
        patched_fetch.return_value = read_yaml_breakdown(YAMLDIR / "xfs10gb.yaml")
        resources = []
        with self.assertRaisesRegex(ValueError, ".*jobspec resources empty.*"):
            directivebreakdown.apply_breakdowns(None, None, resources, 1)
        resources = [{"type": "slot", "count": 1, "with": []}]
        with self.assertRaisesRegex(ValueError, ".*single top-level 'node' entry.*"):
            directivebreakdown.apply_breakdowns(None, None, resources, 1)

    @unittest.mock.patch("flux_k8s.directivebreakdown.fetch_breakdowns")
    def test_allocation_bad_label(self, patched_fetch):
        patched_fetch.return_value = read_yaml_breakdown(YAMLDIR / "bad_label.yaml")
        resources = [{"type": "node", "count": 1}]
        with self.assertRaisesRegex(KeyError, "foo"):
            directivebreakdown.apply_breakdowns(None, None, resources, 1)

    @unittest.mock.patch("flux_k8s.directivebreakdown.fetch_breakdowns")
    def test_allocation_bad_kind(self, patched_fetch):
        patched_fetch.return_value = read_yaml_breakdown(YAMLDIR / "bad_kind.yaml")
        with self.assertRaisesRegex(ValueError, "unsupported breakdown kind"):
            directivebreakdown.apply_breakdowns(
                None, None, [{"type": "node", "count": 1}], 1
            )

    @unittest.mock.patch("flux_k8s.directivebreakdown.fetch_breakdowns")
    def test_allocation_minimum_size(self, patched_fetch):
        patched_fetch.return_value = read_yaml_breakdown(YAMLDIR / "xfs10gb.yaml")
        for nodecount in (4, 6, 8):
            for min_size in (11, 15, 170):
                resources = [{"type": "node", "count": nodecount}]
                new_resources = directivebreakdown.apply_breakdowns(
                    None, None, resources, min_size
                )
                patched_fetch.assert_called_with(None, None)
                self.assertEqual(len(new_resources), 1)
                slot = new_resources[0]
                self.assertEqual(slot["type"], "slot")
                self.assertEqual(slot["count"], nodecount)
                self.assertEqual(len(slot["with"]), 2)
                self.assertEqual(slot["with"][0]["type"], "node")
                self.assertEqual(slot["with"][0]["count"], 1)
                ssds = slot["with"][1]
                self.assertEqual(ssds["type"], "ssd")
                self.assertEqual(ssds["count"], min_size)


class TestBuildAllocSets(unittest.TestCase):
    nodes_per_nnf_1 = {"rabbit1": 1}
    nodes_per_nnf_2 = {"rabbit1": 1, "rabbit2": 1}
    nodes_per_nnf_3 = {"rabbit1": 6, "rabbit2": 3}
    nodes_per_nnf_4 = {"rabbit1": 4, "rabbit2": 3}

    def test_xfs_10gb(self):
        breakdown = read_yaml_breakdown(YAMLDIR / "xfs10gb.yaml")[0]["status"][
            "storage"
        ]["allocationSets"]
        alloc_sets = directivebreakdown.build_allocation_sets(
            breakdown, self.nodes_per_nnf_1, range(1), 0
        )
        self.assertEqual(
            alloc_sets[0],
            {
                "allocationSize": 10737418240,
                "label": "xfs",
                "storage": [{"allocationCount": 1, "name": "rabbit1"}],
            },
        )
        alloc_sets = directivebreakdown.build_allocation_sets(
            breakdown, self.nodes_per_nnf_4, range(7), 0
        )
        self.assertEqual(
            alloc_sets[0],
            {
                "allocationSize": 10737418240,
                "label": "xfs",
                "storage": [
                    {"allocationCount": 4, "name": "rabbit1"},
                    {"allocationCount": 3, "name": "rabbit2"},
                ],
            },
        )

    def test_lustre_10gb_count2(self):
        breakdown = read_yaml_breakdown(YAMLDIR / "lustre10gb_count2.yaml")[0][
            "status"
        ]["storage"]["allocationSets"]
        alloc_sets = directivebreakdown.build_allocation_sets(
            breakdown, self.nodes_per_nnf_1, range(1), 0
        )
        self.assertEqual(
            alloc_sets[0],
            {
                "allocationSize": 5368709120,
                "label": "ost",
                "storage": [{"allocationCount": 2, "name": "rabbit1"}],
            },
        )
        alloc_sets = directivebreakdown.build_allocation_sets(
            breakdown, self.nodes_per_nnf_2, range(2), 0
        )
        self.assertEqual(
            alloc_sets[0],
            {
                "allocationSize": 5368709120,
                "label": "ost",
                "storage": [
                    {"allocationCount": 1, "name": "rabbit1"},
                    {"allocationCount": 1, "name": "rabbit2"},
                ],
            },
        )
        alloc_sets = directivebreakdown.build_allocation_sets(
            breakdown, self.nodes_per_nnf_3, range(9), 0
        )
        self.assertEqual(
            alloc_sets[0],
            {
                "allocationSize": 5368709120,
                "label": "ost",
                "storage": [
                    {"allocationCount": 1, "name": "rabbit1"},
                    {"allocationCount": 1, "name": "rabbit2"},
                ],
            },
        )

    def test_lustre_10tb(self):
        breakdown = read_yaml_breakdown(YAMLDIR / "lustre10tb.yaml")[0]["status"][
            "storage"
        ]["allocationSets"]
        capacity = breakdown[1]["minimumCapacity"]
        alloc_sets = directivebreakdown.build_allocation_sets(
            breakdown, self.nodes_per_nnf_2, range(2), 0
        )
        self.assertEqual(alloc_sets[0]["label"], "mgtmdt")
        self.assertEqual(
            alloc_sets[1],
            {
                "allocationSize": math.ceil(capacity / 2),
                "label": "ost",
                "storage": [
                    {"allocationCount": 1, "name": "rabbit1"},
                    {"allocationCount": 1, "name": "rabbit2"},
                ],
            },
        )
        alloc_sets = directivebreakdown.build_allocation_sets(
            breakdown, self.nodes_per_nnf_3, range(9), 0
        )
        self.assertEqual(alloc_sets[0]["label"], "mgtmdt")
        self.assertEqual(
            alloc_sets[1],
            {
                "allocationSize": math.ceil(capacity / 3),
                "label": "ost",
                "storage": [
                    {"allocationCount": 2, "name": "rabbit1"},
                    {"allocationCount": 1, "name": "rabbit2"},
                ],
            },
        )
        alloc_sets = directivebreakdown.build_allocation_sets(
            breakdown, self.nodes_per_nnf_4, range(7), 0
        )
        self.assertEqual(
            alloc_sets[1],
            {
                "allocationSize": math.ceil(capacity / 7),
                "label": "ost",
                "storage": [
                    {"allocationCount": 4, "name": "rabbit1"},
                    {"allocationCount": 3, "name": "rabbit2"},
                ],
            },
        )


unittest.main(testRunner=TAPTestRunner())
