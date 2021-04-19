#!/usr/bin/env python3

import argparse

import flux
from flux.constants import FLUX_MSGTYPE_REQUEST
from flux.future import Future

parser = argparse.ArgumentParser()
parser.add_argument('--fail', action='store_true')
args = parser.parse_args()

def validate_cb(fh, t, msg, arg):
    payload = {"success": not args.fail}
    if args.fail:
        payload['errstr'] = "Failed for test purposes"
    fh.respond(msg, payload)
    print(f"Responded to vlidation request with {payload}")
    fh.reactor_stop()

fh = flux.Flux()
service_reg_fut = Future(fh.service_register("dws"))
watcher = fh.msg_watcher_create(validate_cb, FLUX_MSGTYPE_REQUEST, "dws.validate")
watcher.start()
service_reg_fut.get()
print("DWS service registered")

fh.reactor_run()

watcher.stop()
watcher.destroy()