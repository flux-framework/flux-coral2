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
    payload = {"success": not args.fail, "resources": {"foo": "bar"}}
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

fh = flux.Flux()
service_reg_fut = Future(fh.service_register("dws"))
watcher = fh.msg_watcher_create(create_cb, FLUX_MSGTYPE_REQUEST, "dws.create")
watcher.start()
setup_watcher = fh.msg_watcher_create(setup_cb, FLUX_MSGTYPE_REQUEST, "dws.setup")
setup_watcher.start()
service_reg_fut.get()
print("DWS service registered")

fh.reactor_run()

watcher.stop()
watcher.destroy()
