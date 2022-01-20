import argparse
import sys
import json
import re
import logging
import itertools

import flux
from flux.idset import IDset
from flux.hostlist import Hostlist
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
        return resType in ["rack", "nnf", "ssd", "globalnnf"] or super(
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

    def __init__(self, rv1, nnfs):
        """Constructor
        rv1 -- RV1 Dictorary that conforms to Flux RFC 20:
                   Resource Set Specification Version 1
        """
        assert len(rv1["execution"]["R_lite"]) == 1
        self._nnfs = nnfs
        self._rackids = 0
        self._rankids = itertools.count()
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
            [],
            hPath,
        )
        edg = ElCapResourceRelationshipV1(parent.get_id(), vtx.get_id())
        self._add_and_tick_uniq_id(vtx, edg)
        for key, val in children.items():
            for i in IDset(val):
                self._encode_child(vtx.get_id(), hPath, rank, str(key), i, {})

    def _encode_ssds(self, parent, nnf):
        ssds_per_nnf = 16
        res_type = "ssd"
        for i in range(ssds_per_nnf):
            res_name = f"{res_type}{i}"
            vtx = ElCapResourcePoolV1(
                self._uniqId,
                res_type,
                res_type,
                res_name,
                self._rackids,
                self._uniqId,
                -1,
                True,
                "GiB",
                to_gibibytes(nnf["capacity"] // ssds_per_nnf),
                f"{parent.path}/{res_name}",
            )
            edg = ElCapResourceRelationshipV1(parent.get_id(), vtx.get_id())
            self._add_and_tick_uniq_id(vtx, edg)

    def _encode_nnf(self, parent, global_nnf, nnf):
        res_type = "nnf"
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
            [],
            f"{parent.path}/{res_name}",
        )
        edg = ElCapResourceRelationshipV1(parent.get_id(), vtx.get_id())
        self._add_and_tick_uniq_id(vtx, edg)
        edg2 = ElCapResourceRelationshipV1(global_nnf.get_id(), vtx.get_id())
        self.add_edge(edg2)
        self._encode_ssds(vtx, nnf)
        children = self._rv1NoSched["execution"]["R_lite"][0]["children"]
        for node in nnf["access"]["computes"]:
            self._encode_rank(parent, next(self._rankids), children, node["name"])

    def _encode_rack(self, parent, global_nnf, nnf):
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
            [],
            f"{parent.path}/{res_name}",
        )
        edg = ElCapResourceRelationshipV1(parent.get_id(), vtx.get_id())
        self._add_and_tick_uniq_id(vtx, edg)
        self._encode_nnf(vtx, global_nnf, nnf)
        self._rackids += 1

    def _encode(self):
        vtx = ElCapResourcePoolV1(
            self._uniqId,
            "cluster",
            "ElCapitan",
            "ElCapitan0",
            0,
            self._uniqId,
            -1,
            True,
            "",
            1,
            [],
            "/ElCapitan0",
        )
        self._add_and_tick_uniq_id(vtx)
        global_nnf = ElCapResourcePoolV1(
            self._uniqId,
            "globalnnf",
            "globalnnf",
            "globalnnf0",
            0,
            self._uniqId,
            -1,
            True,
            "",
            1,
            [],
            "/ElCapitan0/globalnnf0",
        )
        edg = ElCapResourceRelationshipV1(vtx.get_id(), global_nnf.get_id())
        self._add_and_tick_uniq_id(global_nnf, edg)
        for nnf in self._nnfs:
            self._encode_rack(vtx, global_nnf, nnf)


def to_gibibytes(byt):
    """Technically gigabytes are (1000^3)"""
    return byt // (1024 ** 3)


def encode(rv1, nnfs):
    graph = Coral2Graph(rv1, nnfs)
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

    group = "dws.cray.hpe.com"
    version = "v1alpha1"
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
        "--test-pattern",
        help="For testing purposes. A regex pattern to apply to Rabbits",
        default="",
    )
    args = parser.parse_args()

    input_r = json.load(sys.stdin)
    nnfs = [
        x["data"]
        for x in get_storage()["items"]
        if re.search(args.test_pattern, x["metadata"]["name"])
    ]
    dws_computes = set(
        compute["name"] for nnf in nnfs for compute in nnf["access"]["computes"]
    )
    for host in Hostlist(input_r["execution"]["nodelist"]):
        try:
            dws_computes.remove(host)
        except KeyError as keyerr:
            raise ValueError(f"Host {host} not found in DWS") from keyerr
    if dws_computes:
        raise ValueError(
            f"Host(s) {dws_computes} found in DWS but not in R passed through stdin"
        )
    print(json.dumps(encode(input_r, nnfs)))


if __name__ == "__main__":
    main()
