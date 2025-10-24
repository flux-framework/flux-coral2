"""Defines the --coral2-chassis ``run/submit/alloc/batch`` option."""

import flux
from flux.cli.plugin import CLIPlugin


def positive_integer(val):
    if int(val) > 0:
        return int(val)
    else:
        raise ValueError(f"{val} <= 0")


class Coral2ChassisPlugin(CLIPlugin):
    """Adds a flag `--coral2-chassis` to set the chassis count on CORAL2 systems.

    The flag takes a positive integer, representing the number of chassis desired;
    the number of nodes specified via ``-N, --nodes`` will then be split evenly
    across that number of chassis.

    Use of the ``--coral2-chassis`` flag requires that ``-N, --nodes`` be specified.
    Also, current limitations require that the number of chassis evenly divide the
    number of nodes. For example, five total nodes across three chassis *is not*
    supported, but fifteen total nodes across three chassis is supported.

    When not specified, the number of chassis chosen is up to the scheduler.

    Note that the plugin does not validate that the jobspec is satisfiable. It will
    allow you, for instance, to request 500 nodes on a single chassis, even if there
    are only five nodes per chassis. In such cases, the job will not be rejected until
    it has reached the SCHED state.

    On El Cap systems, there are sixteen nodes per chassis. For other systems,
    consult local documentation.

    Use of the ``--coral2-chassis`` flag also requires that the Fluxion scheduler
    be initialized with information about chassis layout. Otherwise an exception
    will be raised with a message about "chassis" not being a known resource type.

    EXAMPLES
    --------

    Request 15 nodes, all on a single chassis:

    ``flux alloc -N15 --coral2-chassis=1 -q myqueue /bin/true``

    Request 200 nodes split evenly across 20 chassis:

    ``flux alloc -N200 --coral2-chassis=20 -q myqueue /bin/true``
    """

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
