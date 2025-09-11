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
    def constraints(resource_type):
        return resource_type in [
            "chassis",
            "rabbit",
            "ssd",
        ] or super(ElCapResourcePoolV1, ElCapResourcePoolV1).constraints(resource_type)

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
        self._chassis_ids = 0
        self._cluster_name = cluster_name
        self._rank_to_children = get_node_children(rv1["execution"]["R_lite"])
        self._rank_to_properties = get_node_properties(
            rv1["execution"].get("properties", {})
        )
        # Call super().__init__() last since it calls __encode
        super().__init__(rv1)

    def _encode_ssds(self, parent_id, parent_path, capacity):
        res_type = "ssd"
        for i in range(self._chunks_per_nnf):
            vtx = ElCapResourcePoolV1(
                self._uniqId,
                res_type,
                unit="GiB",
                size=to_gibibytes(capacity // self._chunks_per_nnf),
                status=1,  # status=1 marks the ssds as 'down' initially
                path=f"{parent_path}/{res_type}{i}",
            )
            edg = ElCapResourceRelationshipV1(parent_id, vtx.get_id())
            self._add_and_tick_uniq_id(vtx, edg)

    def _encode_chassis(self, parent_id, parent_path, rabbit_name, entry):
        path = f"{parent_path}/chassis{self._chassis_ids}"
        vtx = ElCapResourcePoolV1(
            self._uniqId,
            "chassis",
            iden=self._chassis_ids,
            properties={"rabbit": rabbit_name, "ssdcount": str(self._chunks_per_nnf)},
            path=path,
        )
        edg = ElCapResourceRelationshipV1(parent_id, vtx.get_id())
        self._add_and_tick_uniq_id(vtx, edg)
        self._encode_ssds(vtx.get_id(), path, entry["capacity"])
        for node in Hostlist(entry["hostlist"]):
            try:
                index = self._r_hostlist.index(node)[0]
            except FileNotFoundError:
                pass
            else:
                self._encode_rank(
                    vtx.get_id(),
                    path,
                    index,
                    self._rank_to_children[index],
                    node,
                    self._rank_to_properties.get(index, {}),
                )
        # if the rabbit itself is in R, add it to the chassis as a compute node as well
        try:
            index = self._r_hostlist.index(rabbit_name)[0]
        except FileNotFoundError:
            pass
        else:
            self._encode_rank(
                vtx.get_id(),
                path,
                index,
                self._rank_to_children[index],
                rabbit_name,
                self._rank_to_properties.get(index, {}),
            )
        self._chassis_ids += 1

    def _encode(self):
        path = "/" + self._cluster_name
        vtx = ElCapResourcePoolV1(
            self._uniqId,
            "cluster",
            name=self._cluster_name,
            path=path,
        )
        self._add_and_tick_uniq_id(vtx)
        for rabbit_name, entry in self._rabbit_mapping["rabbits"].items():
            self._encode_chassis(vtx.get_id(), path, rabbit_name, entry)
        # add nodes not in rabbit chassis, making the nodes contained by 'cluster'
        dws_computes = set(self._rabbit_mapping["computes"].keys())
        dws_computes |= set(self._rabbit_mapping["rabbits"].keys())
        for rank, node in enumerate(self._r_hostlist):
            if node not in dws_computes:
                self._encode_rank(
                    vtx.get_id(),
                    path,
                    rank,
                    self._rank_to_children[rank],
                    node,
                    self._rank_to_properties.get(rank, {}),
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


def to_gibibytes(bytecount):
    """Technically gigabytes are (1000^3)"""
    return bytecount // (1024**3)


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
            " or a config file passed with the --from-config option."
        ),
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Do not throw an error if nodes are found in DWS but not in R",
    )
    parser.add_argument(
        "-c",
        "--chunks-per-nnf",
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
        nargs="?",
        help=(
            "Path to JSON object giving rabbit layout and capacity, as generated "
            "e.g. by the 'flux rabbitmapping' script"
        ),
    )
    parser.add_argument(
        "--only-sched",
        action="store_true",
        help="Only output the 'scheduling' key",
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
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if proc.returncode != 0:
            raise ValueError(
                f"Could not parse config file {args.from_config!r}, "
                f"error message was {proc.stderr}"
            )
        input_r = json.loads(proc.stdout)
    if args.rabbitmapping is None:
        args.rabbitmapping = flux.Flux().conf_get("rabbit.mapping")
    if args.rabbitmapping is None:
        sys.exit(
            "Could not fetch rabbit.mapping from config, Flux may be misconfigured"
        )
    with open(args.rabbitmapping, "r", encoding="utf8") as rabbitmap_fd:
        rabbit_mapping = json.load(rabbitmap_fd)
    r_hostlist = Hostlist(input_r["execution"]["nodelist"])
    dws_computes = set(rabbit_mapping["computes"].keys())
    if not args.no_validate and not dws_computes <= set(r_hostlist):
        raise RuntimeError(
            f"Node(s) {dws_computes - set(r_hostlist)} found in rabbit_mapping "
            "but not R from stdin"
        )
    output = encode(
        input_r, rabbit_mapping, r_hostlist, args.chunks_per_nnf, args.cluster_name
    )
    if args.only_sched:
        output = output["scheduling"]
    json.dump(output, sys.stdout)


if __name__ == "__main__":
    main()
