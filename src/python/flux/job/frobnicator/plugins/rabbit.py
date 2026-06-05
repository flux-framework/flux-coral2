##############################################################
# Copyright 2026 Lawrence Livermore National Security, LLC
# (c.f. AUTHORS, NOTICE.LLNS, COPYING)
#
# This file is part of the Flux resource manager framework.
# For details, see https://github.com/flux-framework.
#
# SPDX-License-Identifier: LGPL-3.0
##############################################################

"""Add rabbit property constraint to jobspec with DW directives.

For jobs with both a 'dw' attribute and 'allow_rabbits' set to true,
this plugin adds a top-level OR constraint that combines any existing
constraints with the 'rabbit' property. This allows jobs to match
either their existing constraints or nodes with the 'rabbit' property.

This plugin is meant for systems where rabbit nodes have the `rabbit`
property and are not configured for any queue.
"""

from flux.job.frobnicator import FrobnicatorPlugin


class Frobnicator(FrobnicatorPlugin):
    """Frobnicator plugin to add rabbit property constraints for DW jobs"""

    def frob(self, jobspec, *_args, **_kwargs):
        """Add OR constraint with rabbit property if job uses DW and allows rabbits

        Args:
            jobspec: The jobspec to modify

        """
        # Check if job has DW directive and if allow_rabbits is set
        if "dw" not in jobspec.attributes.get(
            "system", {}
        ) or not jobspec.attributes.get("system", {}).get("allow_rabbits", False):
            return
        # both conditions are met, add OR constraint to existing constraints (if any)
        try:
            existing_constraint = jobspec.attributes["system"]["constraints"]
        except KeyError as key_err:
            # No existing constraints - this shouldn't happen because the constraints
            # frobnicator should have added the queue property
            raise RuntimeError(
                "Misconfiguration: job must have constraints set. "
                "Is the constraints frobnicator plugin loaded?"
            ) from key_err
        # create a new OR combining existing and rabbit constraints
        jobspec.setattr(
            "system.constraints",
            {"or": [existing_constraint, {"properties": ["rabbit"]}]},
        )
