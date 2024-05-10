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
        for nodecount in (4, 6, 8):
            resources = [{"type": "node", "count": nodecount}]
            new_resources = directivebreakdown.apply_breakdowns(None, None, resources, 1)
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
            new_resources = directivebreakdown.apply_breakdowns(None, None, resources, 1)
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
            new_resources = directivebreakdown.apply_breakdowns(None, None, resources, 1)
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
            directivebreakdown.apply_breakdowns(None, None, [{"type": "node", "count": 1}], 1)

    @unittest.mock.patch("flux_k8s.directivebreakdown.fetch_breakdowns")
    def test_allocation_minimum_size(self, patched_fetch):
        patched_fetch.return_value = read_yaml_breakdown(YAMLDIR / "xfs10gb.yaml")
        for nodecount in (4, 6, 8):
            for min_size in (11, 15, 170):
                resources = [{"type": "node", "count": nodecount}]
                new_resources = directivebreakdown.apply_breakdowns(None, None, resources, min_size)
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


unittest.main(testRunner=TAPTestRunner())
