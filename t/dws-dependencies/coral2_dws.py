#!/usr/bin/env python3

import argparse
import contextlib

import flux
from flux.constants import FLUX_MSGTYPE_REQUEST

parser = argparse.ArgumentParser()
parser.add_argument("--create-fail", action="store_true")
parser.add_argument("--setup-fail", action="store_true")
parser.add_argument("--setup-hang", action="store_true")
parser.add_argument("--post-run-fail", action="store_true")
parser.add_argument("--teardown-hang", action="store_true")
parser.add_argument("--exclude", default="")

args = parser.parse_args()


def create_cb(fh, t, msg, arg):
    payload = {
        "success": not args.create_fail,
    }
    if args.create_fail:
        payload["errstr"] = "create RPC failed for test purposes"
    fh.respond(msg, payload)
    print(f"Responded to create request with {payload}")
    if args.create_fail:
        return
    fh.rpc(
        "job-manager.dws.resource-update",
        payload={
            "id": msg.payload["jobid"],
            "resources": msg.payload["resources"],
            "copy-offload": False,
            "exclude": args.exclude,
        },
    )


def setup_cb(fh, t, msg, arg):
    if args.setup_hang:
        return
    payload = {"success": not args.setup_fail}
    if args.setup_fail:
        payload["errstr"] = "setup RPC failed for test purposes"
    print(f"Responded to setup request with {payload}")
    fh.respond(msg, payload)
    fh.rpc(
        "job-manager.dws.prolog-remove",
        payload={"id": msg.payload["jobid"], "variables": {}, "rabbits": {}},
    )


def post_run_cb(fh, t, msg, arg):
    if args.teardown_hang:
        # a separate teardown rpc is coming; do nothing
        return
    payload = {"success": not args.post_run_fail}
    if args.post_run_fail:
        payload["errstr"] = "post_run RPC failed for test purposes"
    fh.respond(msg, payload)
    print(f"Responded to post_run request with {payload}")
    if not args.post_run_fail:
        fh.rpc(
            "job-manager.dws.epilog-remove",
            payload={"id": msg.payload["jobid"]},
        )
    fh.reactor_stop()


def teardown_cb(fh, t, msg, arg):
    fh.rpc(
        "job-manager.dws.epilog-remove",
        payload={"id": msg.payload["jobid"]},
    )
    fh.reactor_stop()


def register_services(handle):
    """register dws.* services."""
    serv_reg_fut = handle.service_register("dws")
    for service_name, cb in (
        ("create", create_cb),
        ("setup", setup_cb),
        ("post_run", post_run_cb),
        ("teardown", teardown_cb),
    ):
        yield handle.msg_watcher_create(
            cb,
            FLUX_MSGTYPE_REQUEST,
            f"dws.{service_name}",
        )
    serv_reg_fut.get()


def main():
    fh = flux.Flux()
    with contextlib.ExitStack() as stack:
        for service in register_services(fh):
            stack.enter_context(service)
        print("DWS service registered")
        fh.reactor_run()


if __name__ == "__main__":
    main()
