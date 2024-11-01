#!/usr/bin/env python3

import argparse
import sys
import json
import subprocess

import flux
from flux.hostlist import Hostlist
from flux_k8s import crd

import kubernetes as k8s
from kubernetes.client.rest import ApiException


def get_k8s_api(config_file):
    k8s_client = k8s.config.new_client_from_config(config_file=config_file)
    try:
        return k8s.client.CustomObjectsApi(k8s_client)
    except ApiException as rest_exception:
        if rest_exception.status == 403:
            raise Exception(
                "You must be logged in to the K8s or OpenShift cluster to continue"
            )
        raise


def main():
    parser = argparse.ArgumentParser(
        formatter_class=flux.util.help_formatter(),
        description=("Create a mapping between compute nodes and rabbit nodes"),
    )
    parser.add_argument(
        "--kubeconfig",
        "-k",
        default=None,
        metavar="FILE",
        help="Path to kubeconfig file to use",
    )
    parser.add_argument(
        "--indent",
        "-i",
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
    args = parser.parse_args()
    rabbit_mapping = {"computes": {}, "rabbits": {}}
    k8s_api = get_k8s_api(args.kubeconfig)
    # populate as much data as possible using the SystemConfiguration, since
    # it is complete and static, while the Storage resources can come and go
    sysconfig = k8s_api.get_namespaced_custom_object(
        *crd.SYSTEMCONFIGURATION_CRD, "default"
    )
    for nnf in sysconfig["spec"]["storageNodes"]:
        hlist = Hostlist()
        nnf_name = nnf["name"]
        for compute in nnf.get("computesAccess", []):
            hlist.append(compute["name"])
            rabbit_mapping["computes"][compute["name"]] = nnf_name
        rabbit_mapping["rabbits"][nnf_name] = {}
        rabbit_mapping["rabbits"][nnf_name]["hostlist"] = hlist.uniq().encode()
    # fetch storages to fill in capacity field
    storages = k8s_api.list_cluster_custom_object(
        crd.RABBIT_CRD.group, crd.RABBIT_CRD.version, crd.RABBIT_CRD.plural
    )
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
    # go back through sysconfig, make sure capacity is there for all resources
    for nnf in sysconfig["spec"]["storageNodes"]:
        nnf_name = nnf["name"]
        if rabbit_mapping["rabbits"][nnf_name].get("capacity") is None:
            rabbit_mapping["rabbits"][nnf_name]["capacity"] = max_capacity
    json.dump(rabbit_mapping, sys.stdout, indent=args.indent, sort_keys=args.nosort)


if __name__ == "__main__":
    main()
