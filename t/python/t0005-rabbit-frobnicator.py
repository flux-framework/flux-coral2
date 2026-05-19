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

import importlib.util
import sys
import unittest
from pathlib import Path

from flux.job import JobspecV1
from pycotap import TAPTestRunner

# Dynamically load rabbit.py and inject it into flux.job.frobnicator.plugins
rabbit_path = (
    Path(__file__).parent.parent.parent
    / "src"
    / "python"
    / "flux"
    / "job"
    / "frobnicator"
    / "plugins"
    / "rabbit.py"
)
spec = importlib.util.spec_from_file_location(
    "flux.job.frobnicator.plugins.rabbit", rabbit_path
)
rabbit_module = importlib.util.module_from_spec(spec)
sys.modules["flux.job.frobnicator.plugins.rabbit"] = rabbit_module
spec.loader.exec_module(rabbit_module)

from flux.job.frobnicator.plugins.rabbit import Frobnicator  # noqa: E402


class TestRabbitsFrobnicator(unittest.TestCase):
    """Test the rabbits frobnicator plugin"""

    def setUp(self):
        """Create a frobnicator instance for each test"""
        self.frob = Frobnicator(parser=None)
        self.frob.configure(None, {})

    def test_no_dw_no_change(self):
        """Test that jobspec without DW is not modified"""
        jobspec = JobspecV1.from_command(["hostname"])
        jobspec.setattr("system.allow_rabbits", True)
        original_constraints = jobspec.attributes.get("system", {}).get("constraints")

        self.frob.frob(jobspec, user=1000, urgency=16, flags=0)

        # Should not have added constraints
        new_constraints = jobspec.attributes.get("system", {}).get("constraints")
        self.assertEqual(original_constraints, new_constraints)

    def test_no_allow_rabbits_no_change(self):
        """Test that jobspec with DW but no allow_rabbits is not modified"""
        jobspec = JobspecV1.from_command(["hostname"])
        jobspec.setattr("system.dw", "jobdw capacity=1GiB type=scratch")

        self.frob.frob(jobspec, user=1000, urgency=16, flags=0)

        # Should not have added constraints
        constraints = jobspec.attributes.get("system", {}).get("constraints")
        self.assertIsNone(constraints)

    def test_allow_rabbits_false_no_change(self):
        """Test that jobspec with DW but allow_rabbits=False is not modified"""
        jobspec = JobspecV1.from_command(["hostname"])
        jobspec.setattr("system.dw", "jobdw capacity=1GiB type=scratch")
        jobspec.setattr("system.allow_rabbits", False)

        self.frob.frob(jobspec, user=1000, urgency=16, flags=0)

        # Should not have added constraints
        constraints = jobspec.attributes.get("system", {}).get("constraints")
        self.assertIsNone(constraints)

    def test_dw_and_allow_rabbits_no_change(self):
        """Test that DW + allow_rabbits adds rabbit property constraint"""
        jobspec = JobspecV1.from_command(["hostname"])
        jobspec.setattr("system.dw", "jobdw capacity=1GiB type=scratch")
        jobspec.setattr("system.allow_rabbits", True)

        with self.assertRaisesRegex(
            RuntimeError, r"Misconfiguration:.*constraints frobnicator"
        ):
            self.frob.frob(jobspec, user=1000, urgency=16, flags=0)

    def test_adds_or_constraint_with_existing_constraints(self):
        """Test that existing constraints are combined with OR"""
        jobspec = JobspecV1.from_command(["hostname"])
        jobspec.setattr("system.dw", "jobdw capacity=1GiB type=scratch")
        jobspec.setattr("system.allow_rabbits", True)
        jobspec.setattr("system.constraints", {"properties": ["foo"]})

        self.frob.frob(jobspec, user=1000, urgency=16, flags=0)

        # Should have created OR of existing and rabbit constraints
        constraints = jobspec.attributes["system"]["constraints"]
        self.assertIn("or", constraints)
        self.assertEqual(len(constraints["or"]), 2)
        self.assertIn({"properties": ["foo"]}, constraints["or"])
        self.assertIn({"properties": ["rabbit"]}, constraints["or"])

    def test_wraps_existing_or_constraint(self):
        """Test that rabbit constraint wraps existing OR in another OR"""
        jobspec = JobspecV1.from_command(["hostname"])
        jobspec.setattr("system.dw", "jobdw capacity=1GiB type=scratch")
        jobspec.setattr("system.allow_rabbits", True)
        jobspec.setattr(
            "system.constraints",
            {"or": [{"properties": ["foo"]}, {"properties": ["bar"]}]},
        )

        self.frob.frob(jobspec, user=1000, urgency=16, flags=0)

        # Should have wrapped existing OR with rabbit in a new OR
        constraints = jobspec.attributes["system"]["constraints"]
        self.assertIn("or", constraints)
        self.assertEqual(len(constraints["or"]), 2)
        self.assertIn(
            {"or": [{"properties": ["foo"]}, {"properties": ["bar"]}]},
            constraints["or"],
        )
        self.assertIn({"properties": ["rabbit"]}, constraints["or"])

    def test_works_with_and_constraint(self):
        """Test that AND constraints are properly wrapped in OR"""
        jobspec = JobspecV1.from_command(["hostname"])
        jobspec.setattr("system.dw", "jobdw capacity=1GiB type=scratch")
        jobspec.setattr("system.allow_rabbits", True)
        jobspec.setattr(
            "system.constraints",
            {"and": [{"properties": ["foo"]}, {"properties": ["bar"]}]},
        )

        self.frob.frob(jobspec, user=1000, urgency=16, flags=0)

        # Should have created OR with existing AND and rabbit
        constraints = jobspec.attributes["system"]["constraints"]
        self.assertIn("or", constraints)
        self.assertEqual(len(constraints["or"]), 2)
        self.assertIn(
            {"and": [{"properties": ["foo"]}, {"properties": ["bar"]}]},
            constraints["or"],
        )
        self.assertIn({"properties": ["rabbit"]}, constraints["or"])


if __name__ == "__main__":
    unittest.main(testRunner=TAPTestRunner())
