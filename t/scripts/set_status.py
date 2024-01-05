#!/usr/bin/env python3

import argparse

import flux


parser = argparse.ArgumentParser(description="set status of a vertex")
parser.add_argument("vertex", help="vertex to set")
parser.add_argument("status", choices=("up", "down"))
args = parser.parse_args()


handle = flux.Flux()
payload = {"resource_path": args.vertex, "status": args.status}
handle.rpc("sched-fluxion-resource.set_status", payload).get()
