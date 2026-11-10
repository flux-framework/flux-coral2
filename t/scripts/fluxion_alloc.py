#!/usr/bin/env python3

"""
Allocate or reserve resources directly from sched-fluxion-resource.

The match RPC is the scheduler's own entry point, so it creates graph
state that no Flux job owns: running it with the ID of a job that has
already completed leaves exactly the orphaned state that
flux-rabbit-orphan-scan(1) is meant to find, and running it with an ID
that is not a Flux job at all leaves an allocation that no job explains.
"""

import argparse

import yaml

import flux
from flux.job import JobID

parser = argparse.ArgumentParser(description="allocate resources out of band")
parser.add_argument("jobid", help="jobid to allocate under, in F58 or integer form")
parser.add_argument("--nodes", type=int, default=1, help="nodes to request")
parser.add_argument("--cores", type=int, default=1, help="cores per node to request")
parser.add_argument(
    "--exclusive", action="store_true", help="allocate entire nodes exclusively"
)
parser.add_argument(
    "--cmd",
    default="allocate",
    choices=("allocate", "allocate_orelse_reserve"),
    help="match command to send (default allocate)",
)
args = parser.parse_args()

jobspec = {
    "version": 1,
    "resources": [
        {
            "type": "node",
            "count": args.nodes,
            "with": [
                {
                    "type": "slot",
                    "count": args.cores,
                    "label": "task",
                    "with": [{"type": "core", "count": 1}],
                }
            ],
        }
    ],
    "tasks": [{"command": ["hostname"], "slot": "task", "count": {"per_slot": 1}}],
    # long enough that the allocation cannot expire during the test
    "attributes": {"system": {"duration": 3600}},
}
if args.exclusive:
    jobspec["resources"][0]["exclusive"] = True

payload = {
    "cmd": args.cmd,
    "jobid": int(JobID(args.jobid)),
    "jobspec": yaml.dump(jobspec),
}
print(flux.Flux().rpc("sched-fluxion-resource.match", payload).get()["status"])
