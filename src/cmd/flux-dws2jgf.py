#!/usr/bin/env python3

import argparse
import sys
import json
import re
import logging
import itertools

import flux
from flux.idset import IDset
from flux.hostlist import Hostlist
from flux.idset import IDset
from fluxion.resourcegraph.V1 import (
    FluxionResourceGraphV1,
    FluxionResourcePoolV1,
    FluxionResourceRelationshipV1,
)
import kubernetes as k8s
from kubernetes.client.rest import ApiException


class ElCapResourcePoolV1(FluxionResourcePoolV1):

    """
    ElCap Resource Pool Vertex Class: extend jsongraph's Node class
    """

    @staticmethod
    def constraints(resType):
        return resType in [
            "rack",
            "rabbit",
            "ssd",
        ] or super(ElCapResourcePoolV1, ElCapResourcePoolV1).constraints(resType)

    @property
    def path(self):
        return self.get_metadata()["paths"]["containment"]


class ElCapResourceRelationshipV1(FluxionResourceRelationshipV1):
    """
    ElCap Resource Relationship V1 Class: extend jsongraph's Edge class
    """


class Coral2Graph(FluxionResourceGraphV1):
    """
    CORAL2 Graph:  extend jsongraph's Graph class
    """

    def __init__(self, rv1, nnfs, r_hostlist, chunks_per_nnf, cluster_name):
        """Constructor
        rv1 -- RV1 Dictorary that conforms to Flux RFC 20:
                   Resource Set Specification Version 1
        """
        self._nnfs = nnfs
        self._r_hostlist = r_hostlist
        self._chunks_per_nnf = chunks_per_nnf
        self._rackids = 0
        self._cluster_name = cluster_name
        self._rank_to_children = get_node_children(rv1["execution"]["R_lite"])
        self._rank_to_properties = get_node_properties(rv1["execution"].get("properties", {}))
        # Call super().__init__() last since it calls __encode
        super().__init__(rv1)

    def _encode_rank(self, parent, rank, children, hName):
        hPath = f"{parent.path}/{hName}"
        iden = self._extract_id_from_hn(hName)
        vtx = ElCapResourcePoolV1(
            self._uniqId,
            "node",
            "node",
            hName,
            iden,
            self._uniqId,
            rank,
            True,
            "",
            1,
            self._rank_to_properties.get(rank, {}),
            hPath,
        )
        edg = ElCapResourceRelationshipV1(parent.get_id(), vtx.get_id())
        self._add_and_tick_uniq_id(vtx, edg)
        for key, val in children.items():
            for i in IDset(val):
                self._encode_child(vtx.get_id(), hPath, rank, str(key), i, {})

    def _encode_ssds(self, parent, nnf):
        res_type = "ssd"
        for i in range(self._chunks_per_nnf):
            res_name = f"{res_type}{i}"
            vtx = ElCapResourcePoolV1(
                self._uniqId,
                res_type,
                res_type,
                res_name,
                i,
                self._uniqId,
                -1,
                True,
                "GiB",
                to_gibibytes(nnf["capacity"] // self._chunks_per_nnf),
                {},
                f"{parent.path}/{res_name}",
                1,  # status=1 marks the ssds as 'down' initially
            )
            edg = ElCapResourceRelationshipV1(parent.get_id(), vtx.get_id())
            self._add_and_tick_uniq_id(vtx, edg)

    def _encode_rack(self, parent, nnf):
        res_type = "rack"
        res_name = f"{res_type}{self._rackids}"
        vtx = ElCapResourcePoolV1(
            self._uniqId,
            res_type,
            res_type,
            res_name,
            self._rackids,
            self._uniqId,
            -1,
            True,
            "",
            1,
            {"rabbit": nnf["metadata"]["name"], "ssdcount": str(self._chunks_per_nnf)},
            f"{parent.path}/{res_name}",
        )
        edg = ElCapResourceRelationshipV1(parent.get_id(), vtx.get_id())
        self._add_and_tick_uniq_id(vtx, edg)
        self._encode_ssds(vtx, nnf["status"])
        for node in nnf["status"]["access"].get("computes", []):
            try:
                index = self._r_hostlist.index(node["name"])[0]
            except FileNotFoundError:
                pass
            else:
                self._encode_rank(
                    vtx, index, self._rank_to_children[index], node["name"]
                )
        # if the rabbit itself is in R, add it to the rack as a compute node as well
        try:
            index = self._r_hostlist.index(nnf["metadata"]["name"])[0]
        except FileNotFoundError:
            pass
        else:
            self._encode_rank(
                vtx, index, self._rank_to_children[index], nnf["metadata"]["name"]
            )
        self._rackids += 1

    def _encode(self):
        vtx = ElCapResourcePoolV1(
            self._uniqId,
            "cluster",
            self._cluster_name,
            self._cluster_name + "0",
            0,
            self._uniqId,
            -1,
            True,
            "",
            1,
            {},
            f"/{self._cluster_name}0",
        )
        self._add_and_tick_uniq_id(vtx)
        for nnf in self._nnfs:
            self._encode_rack(vtx, nnf)
        # add nodes not in rabbit racks, making the nodes contained by 'cluster'
        dws_computes = set(
            compute["name"]
            for nnf in self._nnfs
            for compute in nnf["status"]["access"].get("computes", [])
        )
        dws_computes |= set(nnf["metadata"]["name"] for nnf in self._nnfs)
        for rank, node in enumerate(self._r_hostlist):
            if node not in dws_computes:
                self._encode_rank(
                    vtx,
                    rank,
                    self._rank_to_children[rank],
                    node,
                )


def get_node_children(r_lite):
    """Return a mapping from rank to children (cores, gpus, etc.)"""
    rank_to_children = {}
    for entry in r_lite:
        try:
            rank = int(entry["rank"])
        except ValueError:
            low, high = entry["rank"].split("-")
            for i in range(int(low), int(high) + 1):
                rank_to_children[i] = entry["children"]
        else:
            rank_to_children[rank] = entry["children"]
    return rank_to_children


def get_node_properties(properties):
    """Return a mapping from rank to properties."""
    rank_to_property = {}
    for prop_name, idset_str in properties.items():
        for rank in IDset(idset_str):
            properties = rank_to_property.setdefault(rank, {})
            properties[prop_name] = ""
    return rank_to_property


def to_gibibytes(byt):
    """Technically gigabytes are (1000^3)"""
    return byt // (1024 ** 3)


def encode(rv1, nnfs, r_hostlist, chunks_per_nnf, cluster_name):
    graph = Coral2Graph(rv1, nnfs, r_hostlist, chunks_per_nnf, cluster_name)
    rv1["scheduling"] = graph.to_JSON()
    return rv1


def get_storage():
    k8s_client = k8s.config.new_client_from_config()
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
    try:
        api_response = api_instance.list_cluster_custom_object(group, version, plural)
    except ApiException as e:
        print("Exception: %s\n" % e, file=sys.stderr)
    return api_response


LOGGER = logging.getLogger("flux-dws2jgf")


@flux.util.CLIMain(LOGGER)
def main():
    parser = argparse.ArgumentParser(
        prog="flux-dws2jgf",
        formatter_class=flux.util.help_formatter(),
        description="Print JGF representation of Rabbit nodes",
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Do not throw an error if nodes are found in DWS but not in R",
    )
    parser.add_argument(
        "--chunks-per-nnf",
        "-c",
        help=(
            "The number of ways to split a rabbit/nnf for Flux scheduling. "
            "Higher numbers allow finer-grained scheduling at the possible cost "
            "of scheduler performance."
        ),
        default=36,
        metavar="N",
        type=int,
    )
    parser.add_argument(
        "--cluster-name",
        help="The name of the cluster to build the resource graph for",
        default="ElCapitan",
    )
    args = parser.parse_args()

    input_r = json.load(sys.stdin)
    nnfs = [x for x in get_storage()["items"]]
    r_hostlist = Hostlist(input_r["execution"]["nodelist"])
    dws_computes = set(
        compute["name"]
        for nnf in nnfs
        for compute in nnf["status"]["access"].get("computes", [])
    )
    if not args.no_validate and not dws_computes <= set(r_hostlist):
        raise RuntimeError(
            f"Node(s) {dws_computes - set(r_hostlist)} found in DWS but not R from stdin"
        )
    json.dump(
        encode(input_r, nnfs, r_hostlist, args.chunks_per_nnf, args.cluster_name),
        sys.stdout,
    )


if __name__ == "__main__":
    main()
