#!/usr/bin/env python3

"""Script to create a JSON file mapping compute nodes <-> rabbits."""

import argparse
import sys
import json

import flux
from flux.hostlist import Hostlist
from flux_k8s import crd, cleanup, workflow


def initialize_from_systemconfig(sysconfig):
    """Initialize the rabbitmapping dict with locality information.

    Populate as much data as possible using the SystemConfiguration, since
    it is complete and static, while the Storage resources can come and go.
    """
    rabbit_mapping = {"computes": {}, "rabbits": {}}
    for nnf in sysconfig["spec"]["storageNodes"]:
        hlist = Hostlist()
        nnf_name = nnf["name"]
        for compute in nnf.get("computesAccess", []):
            hlist.append(compute["name"])
            rabbit_mapping["computes"][compute["name"]] = nnf_name
        rabbit_mapping["rabbits"][nnf_name] = {}
        rabbit_mapping["rabbits"][nnf_name]["hostlist"] = hlist.uniq().encode()
    return rabbit_mapping


def populate_from_storages(storages, rabbit_mapping):
    """Populate the rabbit_mapping dict using data from Storage resources."""
    max_capacity = 0
    for nnf in storages["items"]:
        nnf_name = nnf["metadata"]["name"]
        for compute in nnf["status"]["access"].get("computes", []):
            compute_name = compute["name"]
            if rabbit_mapping["computes"].get(compute_name) != nnf_name:
                raise RuntimeError(
                    f"Mismatch: rabbit {nnf_name} claims to be "
                    f"connected to {compute_name} but systemconfiguration gives "
                    f"{rabbit_mapping['computes'].get(compute_name)}"
                )
            capacity = nnf.get("status", {}).get("capacity", 0)
            max_capacity = max(capacity, max_capacity)
            if capacity == 0:
                capacity = max_capacity
            rabbit_mapping["rabbits"][nnf_name]["capacity"] = capacity
    return max_capacity


def reduce_capacity_by_servers(k8s_api, rabbit_mapping):
    """Reduce rabbit capacity by allocations in Servers custom objects.

    Fetches all Servers objects across all namespaces and sums up the
    allocated capacity per rabbit, then reduces each rabbit's capacity
    accordingly. Skips Servers resources managed by Flux.
    """
    servers = k8s_api.list_cluster_custom_object(
        crd.SERVER_CRD.group, crd.SERVER_CRD.version, crd.SERVER_CRD.plural
    )

    # Track allocated capacity per rabbit
    allocated = {}
    for server in servers["items"]:
        server_name = server["metadata"]["name"]
        # Skip Servers resources managed by Flux
        if workflow.WorkflowInfo.is_recognized(server_name):
            continue
        for alloc_set in server.get("spec", {}).get("allocationSets", []):
            allocation_size = alloc_set.get("allocationSize", 0)
            for storage in alloc_set.get("storage", []):
                rabbit_name = storage["name"]
                alloc_count = storage.get("allocationCount", 1)
                total_alloc = allocation_size * alloc_count
                allocated[rabbit_name] = allocated.get(rabbit_name, 0) + total_alloc

    # Reduce each rabbit's capacity by its allocated amount
    for rabbit_name, alloc_amount in allocated.items():
        if rabbit_name in rabbit_mapping["rabbits"]:
            current_capacity = rabbit_mapping["rabbits"][rabbit_name].get("capacity", 0)
            rabbit_mapping["rabbits"][rabbit_name]["capacity"] = max(
                0, current_capacity - alloc_amount
            )


def main():
    """Create a JSON file mapping compute nodes <-> rabbits.

    Fetch the SystemConfiguration from kubernetes and use that for the mapping.
    Also fetch Storage resources from kubernetes to populate the JSON file with
    capacity data.
    """
    parser = argparse.ArgumentParser(
        formatter_class=flux.util.help_formatter(),
        description=("Create a mapping between compute nodes and rabbit nodes"),
    )
    parser.add_argument(
        "-k",
        "--kubeconfig",
        default=None,
        metavar="FILE",
        help="Path to kubeconfig file to use",
    )
    parser.add_argument(
        "-i",
        "--indent",
        default=None,
        type=int,
        metavar="N",
        help="Number of spaces to indent output JSON document",
    )
    parser.add_argument(
        "--nosort",
        action="store_false",
        help="Do not sort keys in output JSON document",
    )
    parser.add_argument(
        "--ignore-external-allocations",
        action="store_true",
        help="Ignore external (non-Flux) allocations from Servers objects",
    )
    args = parser.parse_args()
    k8s_api = cleanup.get_k8s_api(args.kubeconfig)
    crd.determine_api_versions(flux.Flux(), k8s_api)
    sysconfig = k8s_api.get_namespaced_custom_object(
        *crd.SYSTEMCONFIGURATION_CRD, "default"
    )
    rabbit_mapping = initialize_from_systemconfig(sysconfig)
    # fetch storages to fill in capacity field
    storages = k8s_api.list_cluster_custom_object(
        crd.RABBIT_CRD.group, crd.RABBIT_CRD.version, crd.RABBIT_CRD.plural
    )
    max_capacity = populate_from_storages(storages, rabbit_mapping)
    # go back through sysconfig, make sure capacity is there for all resources
    for nnf in sysconfig["spec"]["storageNodes"]:
        nnf_name = nnf["name"]
        if rabbit_mapping["rabbits"][nnf_name].get("capacity") is None:
            rabbit_mapping["rabbits"][nnf_name]["capacity"] = max_capacity
    # reduce capacity by external allocations from Servers objects
    if not args.ignore_external_allocations:
        reduce_capacity_by_servers(k8s_api, rabbit_mapping)
    json.dump(rabbit_mapping, sys.stdout, indent=args.indent, sort_keys=args.nosort)


if __name__ == "__main__":
    main()
