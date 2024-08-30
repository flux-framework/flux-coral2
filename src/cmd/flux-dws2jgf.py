#!/usr/bin/env python3

import argparse
import sys
import json
import logging
import subprocess
import socket

import flux
from flux.idset import IDset
from flux.hostlist import Hostlist
from fluxion.resourcegraph.V1 import (
    FluxionResourceGraphV1,
    FluxionResourcePoolV1,
    FluxionResourceRelationshipV1,
)


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
        ] or super(
            ElCapResourcePoolV1, ElCapResourcePoolV1
        ).constraints(resType)

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

    def __init__(self, rv1, rabbit_mapping, r_hostlist, chunks_per_nnf, cluster_name):
        """Constructor
        rv1 -- RV1 Dictorary that conforms to Flux RFC 20:
                   Resource Set Specification Version 1
        """
        self._rabbit_mapping = rabbit_mapping
        self._r_hostlist = r_hostlist
        self._chunks_per_nnf = chunks_per_nnf
        self._rackids = 0
        self._cluster_name = cluster_name
        self._rank_to_children = get_node_children(rv1["execution"]["R_lite"])
        self._rank_to_properties = get_node_properties(
            rv1["execution"].get("properties", {})
        )
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

    def _encode_ssds(self, parent, capacity):
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
                to_gibibytes(capacity // self._chunks_per_nnf),
                {},
                f"{parent.path}/{res_name}",
                1,  # status=1 marks the ssds as 'down' initially
            )
            edg = ElCapResourceRelationshipV1(parent.get_id(), vtx.get_id())
            self._add_and_tick_uniq_id(vtx, edg)

    def _encode_rack(self, parent, rabbit_name, entry):
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
            {"rabbit": rabbit_name, "ssdcount": str(self._chunks_per_nnf)},
            f"{parent.path}/{res_name}",
        )
        edg = ElCapResourceRelationshipV1(parent.get_id(), vtx.get_id())
        self._add_and_tick_uniq_id(vtx, edg)
        self._encode_ssds(vtx, entry["capacity"])
        for node in Hostlist(entry["hostlist"]):
            try:
                index = self._r_hostlist.index(node)[0]
            except FileNotFoundError:
                pass
            else:
                self._encode_rank(vtx, index, self._rank_to_children[index], node)
        # if the rabbit itself is in R, add it to the rack as a compute node as well
        try:
            index = self._r_hostlist.index(rabbit_name)[0]
        except FileNotFoundError:
            pass
        else:
            self._encode_rank(vtx, index, self._rank_to_children[index], rabbit_name)
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
        for rabbit_name, entry in self._rabbit_mapping["rabbits"].items():
            self._encode_rack(vtx, rabbit_name, entry)
        # add nodes not in rabbit racks, making the nodes contained by 'cluster'
        dws_computes = set(self._rabbit_mapping["computes"].keys())
        dws_computes |= set(self._rabbit_mapping["rabbits"].keys())
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
    return byt // (1024**3)


def encode(rv1, rabbit_mapping, r_hostlist, chunks_per_nnf, cluster_name):
    graph = Coral2Graph(rv1, rabbit_mapping, r_hostlist, chunks_per_nnf, cluster_name)
    rv1["scheduling"] = graph.to_JSON()
    return rv1


LOGGER = logging.getLogger("flux-dws2jgf")


@flux.util.CLIMain(LOGGER)
def main():
    parser = argparse.ArgumentParser(
        prog="flux-dws2jgf",
        formatter_class=flux.util.help_formatter(),
        description=(
            "Print JGF representation of Rabbit nodes. Reads R from stdin"
            "or a config file passed with the --from-config option."
        ),
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
        help=(
            "The name of the cluster to build the resource graph for. "
            "If unspecified, use the hostname stripped of numerics."
        ),
    )
    parser.add_argument(
        "--from-config",
        metavar="FILE",
        help=(
            "Generate JGF based on a Flux config TOML file containing "
            "a resource.config table"
        ),
    )
    parser.add_argument(
        "rabbitmapping",
        metavar="FILE",
        help=(
            "Path to JSON object giving rabbit layout and capacity, as generated "
            "e.g. by the 'flux rabbitmapping' script"
        ),
    )
    args = parser.parse_args()
    if not args.cluster_name:
        args.cluster_name = "".join(
            i for i in socket.gethostname() if not i.isdigit()
        ).rstrip("-")

    if args.from_config is None:
        input_r = json.load(sys.stdin)
    else:
        proc = subprocess.run(
            f"flux R parse-config {args.from_config}".split(),
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            raise ValueError(
                f"Could not parse config file {args.from_config!r}, "
                "error message was {proc.stderr}"
            )
        input_r = json.load(proc.stdout)
    with open(args.rabbitmapping, "r", encoding="utf8") as rabbitmap_fd:
        rabbit_mapping = json.load(rabbitmap_fd)
    r_hostlist = Hostlist(input_r["execution"]["nodelist"])
    dws_computes = set(rabbit_mapping["computes"].keys())
    if not args.no_validate and not dws_computes <= set(r_hostlist):
        raise RuntimeError(
            f"Node(s) {dws_computes - set(r_hostlist)} found in rabbit_mapping "
            "but not R from stdin"
        )
    json.dump(
        encode(
            input_r, rabbit_mapping, r_hostlist, args.chunks_per_nnf, args.cluster_name
        ),
        sys.stdout,
    )


if __name__ == "__main__":
    main()
