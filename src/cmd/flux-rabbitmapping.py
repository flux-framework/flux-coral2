#!/usr/bin/env python3

import argparse
import sys
import json
import subprocess

import flux
from flux.hostlist import Hostlist

import kubernetes as k8s
from kubernetes.client.rest import ApiException


def get_storage(config_file):
    k8s_client = k8s.config.new_client_from_config(config_file=config_file)
    try:
        api_instance = k8s.client.CustomObjectsApi(k8s_client)
    except ApiException as rest_exception:
        if rest_exception.status == 403:
            raise Exception(
                "You must be logged in to the K8s or OpenShift cluster to continue"
            )
        raise

    group = "dataworkflowservices.github.io"
    version = "v1alpha2"
    plural = "storages"
    return api_instance.list_cluster_custom_object(group, version, plural)


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
    for nnf in get_storage(args.kubeconfig)["items"]:
        hlist = Hostlist()
        nnf_name = nnf["metadata"]["name"]
        for compute in nnf["status"]["access"].get("computes", []):
            hlist.append(compute["name"])
            rabbit_mapping["computes"][compute["name"]] = nnf_name
        rabbit_mapping["rabbits"][nnf_name] = {}
        rabbit_mapping["rabbits"][nnf_name]["hostlist"] = hlist.uniq().encode()
        rabbit_mapping["rabbits"][nnf_name]["capacity"] = nnf["status"]["capacity"]
    json.dump(rabbit_mapping, sys.stdout, indent=args.indent, sort_keys=args.nosort)


if __name__ == "__main__":
    main()
