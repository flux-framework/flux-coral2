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

import sys
import unittest
import unittest.mock
from pathlib import Path


from pycotap import TAPTestRunner

# append path to coral2_dws.py
sys.path.append(str(Path(__file__).resolve().parent.parent.parent / "src" / "modules"))

import coral2_dws


class Coral2DwsTests(unittest.TestCase):
    """Tests for functions in the coral2_dws script."""

    def test_dw_directive_logic(self):
        pairs = [
            ("#DW foo", ["#DW foo"]),
            ("#DW foo #DW bar", ["#DW foo", "#DW bar"]),
            (["#DW foo", "#DW bar"], ["#DW foo", "#DW bar"]),
            (["#DW foo", "#DW bar #DW baz"], ["#DW foo", "#DW bar", "#DW baz"]),
        ]  # pairs of (input, expected output)
        for arg, exp in pairs:
            ret = coral2_dws.parse_dw_directives(arg, {})
            self.assertSequenceEqual(ret, exp)

    def test_dw_directive_logic_presets(self):
        presets = {
            "foo": "#DW foo",
            "bar": "#DW foo #DW bar",
            "baz": ["#DW foo", "#DW baz"],
        }
        pairs = [
            ("foo", ["#DW foo"]),
            ("bar", ["#DW foo", "#DW bar"]),
            ("baz", ["#DW foo", "#DW baz"]),
            (["foo", "bar"], ["#DW foo", "#DW foo", "#DW bar"]),
        ]  # pairs of (input, expected output)
        for arg, exp in pairs:
            ret = coral2_dws.parse_dw_directives(arg, presets)
            self.assertSequenceEqual(ret, exp)


unittest.main(testRunner=TAPTestRunner())
