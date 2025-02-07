#!/usr/bin/env python3

"""Script to create a JSON file mapping compute nodes <-> rabbits."""

import argparse
import sys
import json

import flux
from flux.hostlist import Hostlist


def main():
    """Create a JSON file mapping compute nodes <-> rabbits.

    Fetch the SystemConfiguration from kubernetes and use that for the mapping.
    Also fetch Storage resources from kubernetes to populate the JSON file with
    capacity data.
    """
    parser = argparse.ArgumentParser(
        formatter_class=flux.util.help_formatter(),
        description=("Map compute nodes to rabbits and vice versa."),
    )
    parser.add_argument(
        "--computes",
        "-c",
        nargs="+",
        metavar="HOSTS",
        type=Hostlist,
        help="One or more hostlists of compute nodes",
    )
    parser.add_argument(
        "rabbits",
        nargs="*",
        metavar="RABBITS",
        type=Hostlist,
        help="One or more hostlists of rabbit nodes",
    )
    # validate args
    args = parser.parse_args()
    if args.computes and args.rabbits:
        sys.exit(
            "Both rabbits and computes (with '--computes') cannot be "
            "looked up at the same time"
        )
    # load the mapping file
    handle = flux.Flux()
    path = handle.conf_get("rabbit.mapping")
    if path is None:
        sys.exit("Flux is misconfigured, 'rabbit.mapping' key not set")
    try:
        with open(path, "r", encoding="utf8") as fd:
            mapping = json.load(fd)
    except FileNotFoundError:
        sys.exit(
            f"Could not find file {path!r} specified under "
            "'rabbit.mapping' config key, Flux may be misconfigured"
        )
    except json.JSONDecodeError as jexc:
        sys.exit(f"File {path!r} could not be parsed as JSON: {jexc}")
    # construct and print the hostlist of rabbits
    hlist = Hostlist()
    if not args.computes and not args.rabbits:
        # print out all rabbits
        hlist.append(mapping["rabbits"].keys())
        print(hlist.uniq().encode())
        return
    if args.computes:
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
