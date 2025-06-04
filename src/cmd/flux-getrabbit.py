#!/usr/bin/env python3

"""Script to create a JSON file mapping compute nodes <-> rabbits."""

import argparse
import sys
import json

import flux
from flux.job import JobID
from flux.hostlist import Hostlist


def read_args():
    """Read in command-line args."""
    parser = argparse.ArgumentParser(
        formatter_class=flux.util.help_formatter(),
        description=("Map compute nodes to rabbits and vice versa."),
    )
    parser.add_argument(
        "-c",
        "--computes",
        nargs="+",
        metavar="HOSTS",
        type=Hostlist,
        help="hostlists of compute nodes, to map to rabbits",
    )
    parser.add_argument(
        "-j",
        "--jobids",
        nargs="+",
        metavar="JOBID",
        help="jobids, to map to rabbits",
    )
    parser.add_argument(
        "rabbits",
        nargs="*",
        metavar="RABBITS",
        type=Hostlist,
        help="hostlists of rabbits, to map to compute nodes",
    )
    return parser.parse_args()


def map_to_rabbits(args, handle, mapping):
    """Map compute nodes to rabbit nodes, and print.

    If job IDs are provided, turn them into a hostlist of compute nodes and
    then proceed.
    """
    hlist = Hostlist()
    if not args.computes:
        args.computes = []
    if args.jobids:
        for jobid in args.jobids:
            try:
                nodelist = (
                    flux.job.job_list_id(handle, JobID(jobid), ["annotations"])
                    .get_jobinfo()
                    .user.rabbits
                )
            except FileNotFoundError:
                sys.exit(f"Could not find job {jobid}")
            except Exception as exc:
                sys.exit(f"Lookup of job {jobid} failed: {exc}")
            # if there was no `user.rabbits` annotation, a custom class is returned
            # that converts to an empty string
            if not str(nodelist):
                sys.exit(f"No rabbits found for job {jobid}")
            hlist.append(nodelist)
    aggregated_computes = Hostlist()
    for computes in args.computes:
        aggregated_computes.append(computes)
    aggregated_computes.uniq()
    for hostname in aggregated_computes:
        try:
            rabbit = mapping["computes"][hostname]
        except KeyError:
            sys.exit(f"Could not find compute {hostname}")
        hlist.append(rabbit)
    print(hlist.uniq().encode())


def main():
    """Construct a hostlist of rabbits or compute nodes, depending on arguments."""
    args = read_args()
    if args.rabbits and (args.computes or args.jobids):
        sys.exit(
            "Both rabbits and computes or jobids cannot be looked up at the same time"
        )
    # load the mapping file
    handle = flux.Flux()
    path = handle.conf_get("rabbit.mapping")
    if path is None:
        try:
            path = flux.Flux("/").conf_get("rabbit.mapping")
        except Exception:
            pass
        if path is None:
            sys.exit(
                "Flux is misconfigured, 'rabbit.mapping' key not set in "
                "current instance or root/system instance"
            )
    try:
        with open(path, "r", encoding="utf8") as json_fd:
            mapping = json.load(json_fd)
    except FileNotFoundError:
        sys.exit(
            f"Could not find file {path!r} specified under "
            "'rabbit.mapping' config key, Flux may be misconfigured"
        )
    except json.JSONDecodeError as jexc:
        sys.exit(f"File {path!r} could not be parsed as JSON: {jexc}")
    # construct and print the hostlist of rabbits or compute nodes,
    # depending on arguments
    hlist = Hostlist()
    if not args.computes and not args.rabbits and not args.jobids:
        # no arguments: print out all rabbits
        hlist.append(mapping["rabbits"].keys())
        print(hlist.uniq().encode())
        return
    if args.jobids or args.computes:
        # construct and print the hostlist of rabbits
        map_to_rabbits(args, handle, mapping)
        return
    # construct and print the hostlist of compute nodes
    aggregated_rabbits = Hostlist()
    for computes in args.rabbits:
        aggregated_rabbits.append(computes)
    aggregated_rabbits.uniq()
    for rabbit in aggregated_rabbits:
        try:
            computes = mapping["rabbits"][rabbit]["hostlist"]
        except KeyError:
            sys.exit(f"Could not find rabbit {rabbit}")
        hlist.append(computes)
    print(hlist.uniq().encode())


if __name__ == "__main__":
    main()
