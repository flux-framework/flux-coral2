#!/usr/bin/env python3

import argparse

import flux
from flux.constants import FLUX_MSGTYPE_REQUEST
from flux.future import Future

parser = argparse.ArgumentParser()
parser.add_argument('--fail', action='store_true')
parser.add_argument('--setup-fail', action='store_true')
args = parser.parse_args()

def create_cb(fh, t, msg, arg):
    payload = {"success": not args.fail, "resources": msg.payload["resources"]}
    if args.fail:
        payload['errstr'] = "Failed for test purposes"
    fh.respond(msg, payload)
    print(f"Responded to create request with {payload}")
    if args.fail:
        fh.reactor_stop()

def setup_cb(fh, t, msg, arg):
    payload = {"success": not args.fail, "variables": {}}
    if args.fail:
        payload['errstr'] = "Failed for test purposes"
    fh.respond(msg, payload)
    fh.reactor_stop()

def post_run_cb(fh, t, msg, arg):
    pass

fh = flux.Flux()
service_reg_fut = Future(fh.service_register("dws"))
create_watcher = fh.msg_watcher_create(create_cb, FLUX_MSGTYPE_REQUEST, "dws.create")
create_watcher.start()
setup_watcher = fh.msg_watcher_create(setup_cb, FLUX_MSGTYPE_REQUEST, "dws.setup")
setup_watcher.start()
post_run_watcher = fh.msg_watcher_create(post_run_cb, FLUX_MSGTYPE_REQUEST, "dws.post_run")
post_run_watcher.start()
service_reg_fut.get()
print("DWS service registered")

fh.reactor_run()

create_watcher.stop()
create_watcher.destroy()
setup_watcher.stop()
setup_watcher.destroy()
post_run_watcher.stop()
post_run_watcher.destroy()
