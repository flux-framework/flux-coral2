#!/usr/bin/env python3

import struct
import os
import json
import sys


def get_comm_profiles(apinfo, size, offset, count):
    comms = []
    for comm in _get_structs(apinfo, size, offset, count, "40siii"):
        tokenid, vni, vlan, traffic_classes = comm
        comms.append(
            {
                "tokenid": tokenid,
                "vni": vni,
                "vlan": vlan,
                "traffic_classes": traffic_classes,
            }
        )
    return comms


def get_cmds(apinfo, size, offset, count):
    cmds = []
    for cmd in _get_structs(apinfo, size, offset, count, "iii"):
        npes, pes_per_node, cpus_per_pe = cmd
        cmds.append(
            {"npes": npes, "pes_per_node": pes_per_node, "cpus_per_pe": cpus_per_pe}
        )
    return cmds


def get_pes(apinfo, size, offset, count):
    pes = []
    for pe in _get_structs(apinfo, size, offset, count, "iii"):
        localidx, cmdidx, nodeidx = pe
        pes.append({"localidx": localidx, "cmdidx": cmdidx, "nodeidx": nodeidx})
    return pes


def get_nodes(apinfo, size, offset, count):
    nodes = []
    for node in _get_structs(apinfo, size, offset, count, "i64s"):
        node_id, hostname = node
        nodes.append(
            {"id": node_id, "hostname": hostname.split(b"\x00")[0].decode("ascii")}
        )
    return nodes


def get_nics(apinfo, size, offset, count):
    nics = []
    for pe in _get_structs(apinfo, size, offset, count, "ii40s"):
        nodeidx, address_type, address = pe
        nics.append(
            {
                "nodeidx": nodeidx,
                "address_type": address_type,
                "address": address.split(b"\x00")[0].decode("ascii"),
            }
        )
    return nics


def _get_structs(apinfo, size, offset, count, format):
    for i in range(count):
        yield struct.unpack(format, apinfo[offset : offset + size])
        offset += size


def main():
    with open(os.environ["PALS_APINFO"], "rb") as fd:
        apinfo = fd.read()
    header_format = "iNNNiNNiNNiNNiNNi"
    header = struct.unpack(header_format, apinfo[: struct.calcsize(header_format)])
    apinfo_dict = {
        "version": header[0],
        "comm_profiles": get_comm_profiles(apinfo, header[2], header[3], header[4]),
        "cmds": get_cmds(apinfo, header[5], header[6], header[7]),
        "pes": get_pes(apinfo, header[8], header[9], header[10]),
        "nodes": get_nodes(apinfo, header[11], header[12], header[13]),
        "nics": get_nics(apinfo, header[14], header[15], header[16]),
    }
    json.dump(apinfo_dict, sys.stdout)
    print()


if __name__ == "__main__":
    main()
