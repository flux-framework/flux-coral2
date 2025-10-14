"""Defines the --coral2-chassis ``run/submit/alloc/batch`` option."""

import flux
from flux.cli.plugin import CLIPlugin


def positive_integer(val):
    if int(val) > 0:
        return int(val)
    else:
        raise ValueError(f"{val} <= 0")


class Coral2ChassisPlugin(CLIPlugin):
    """Set the chassis count on CORAL2 systems."""

    def __init__(self, prog, prefix="coral2"):
        super().__init__(prog, prefix=prefix)
        self.add_option(
            "--chassis",
            help=(
                "Number of chassis to allocate. Requires -N,--nodes. "
                "Nodes will be split evenly across chassis. Chassis are "
                "allocated non-exclusively."
            ),
            type=positive_integer,
            default=0,
        )

    def preinit(self, args):
        """Verify that chassis count is reasonable if provided."""
        if getattr(args, "chassis", 0) <= 0:
            return
        if flux.Flux("/").conf_get("resource.scheduling") is None:
            raise RuntimeError(
                "Flux scheduler not configured to support chassis count"
            )
        try:
            nodecount = int(args.nodes)
        except (TypeError, ValueError):
            raise ValueError("--coral2-chassis option requires -N,--nodes")
        if nodecount % args.chassis != 0:
            raise ValueError(
                f"Nodecount ({nodecount}) must be evenly divisible "
                f"by chassis count ({args.chassis})"
            )

    def modify_jobspec(self, args, jobspec):
        """Construct a new jobspec resources with top-level 'chassis' resources."""
        if getattr(args, "chassis", 0) <= 0:
            return
        resources = jobspec.resources
        if len(resources) > 1 or resources[0]["type"] != "node":
            raise ValueError(
                "jobspec resources must have a single top-level 'node' entry, "
                f"got {len(resources)} entries, first entry {resources[0]['type']!r}"
            )
        resources[0]["count"] = resources[0]["count"] // args.chassis
        jobspec.jobspec["resources"] = [
            {
                "type": "chassis",
                "count": args.chassis,
                "with": [
                    resources[0],
                ],
            }
        ]
