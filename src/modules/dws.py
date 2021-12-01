#!/usr/bin/env python3

import os
import syslog
import json
import argparse

import kubernetes as k8s
from kubernetes.client.rest import ApiException
import flux
from flux.job import JobspecV1
from flux.job.JobID import id_parse
from flux.constants import FLUX_MSGTYPE_REQUEST
from flux.future import Future
from flux_k8s.crd import WORKFLOW_CRD, RABBIT_CRD
from flux_k8s.watch import Watchers, Watch
from flux_k8s.directivebreakdown import apply_breakdowns


_SAVED_MESSAGES = {}


def create_cb(fh, t, msg, arg):
    api_instance = arg

    try:
        dw_string = msg.payload["dw_string"]
        if not dw_string.startswith("#DW "):
            dw_string = "#DW " + dw_string
        jobid = msg.payload["jobid"]
        spec = {
            "desiredState": "proposal",
            "dwDirectives": [dw_string],
            "jobID": jobid,
            "userID": 1001,
            "wlmID": "5f239bd8-30db-450b-8c2c-a1a7c8631a1a",
        }
        body = {
            "kind": "Workflow",
            "apiVersion": "/".join([WORKFLOW_CRD.group, WORKFLOW_CRD.version]),
            "spec": spec,
            "metadata": {
                "name": "dws-workflow-test-{}".format(jobid),
                "namespace": WORKFLOW_CRD.namespace,
            },
        }
    except Exception as e:
        fh.log(
            syslog.LOG_ERR,
            "Exception when extracting job data from payload: {}".format(e),
        )
        payload = {"success": False, "errstr": str(e)}
        fh.respond(msg, payload)
        return

    try:
        api_response = api_instance.create_namespaced_custom_object(
            *WORKFLOW_CRD,
            body,
        )
    except ApiException as e:
        fh.log(
            syslog.LOG_ERR,
            "Exception when calling CustomObjectsApi->create_namespaced_custom_object: {}".format(
                e
            ),
        )
        payload = {"success": False, "errstr": str(e)}
        fh.respond(msg, payload)
    else:
        _SAVED_MESSAGES[jobid] = (msg, msg.payload["resources"])
        fh.msg_incref(msg)


def rabbit_state_change_cb(event, fh, rabbits):
    obj = event["object"]
    name = obj["metadata"]["name"]
    percentDegraded = obj["spec"]["percentDegraded"]
    status = obj["spec"]["status"]

    try:
        curr_rabbit = rabbits[name]
    except KeyError:
        fh.log(
            syslog.LOG_DEBUG,
            f"Just encountered an unknown Rabbit ({name}) in the event stream",
        )
        # TODO: should never happen, but if it does, insert the rabbit into the resource graph
        return

    if curr_rabbit["spec"]["status"] != status:
        fh.log(syslog.LOG_DEBUG, f"Rabbit {name} status changed to {status}")
        # TODO: update status of vertex in resource graph
    if curr_rabbit["spec"]["percentDegraded"] != percentDegraded:
        fh.log(
            syslog.LOG_DEBUG,
            f"Rabbit {name} percentDegraded changed to {percentDegraded}",
        )
        # TODO: update "percentDegraded" property of vertex in resource graph
        # TODO: update capacity of rabbit in resource graph (mark some slices down?)
    rabbits[name] = obj


def workflow_state_change_cb(event, fh, k8s_api):
    workflow = event["object"]
    name = workflow["metadata"]["name"]
    if workflow["status"]["state"] == "proposal" and workflow["status"]["ready"]:
        # ensure jobspec update is only done once by removing _SAVED_MESSAGES entry
        msg, resources = _SAVED_MESSAGES.pop(workflow["spec"]["jobID"], (None, None))
        if msg is not None:
            apply_breakdowns(k8s_api, workflow, resources)
            fh.respond(msg, {"success": True, "resources": resources})
            fh.msg_decref(msg)


def init_rabbits(k8s_api, fh, watchers):
    try:
        api_response = k8s_api.list_namespaced_custom_object(*RABBIT_CRD)
    except ApiException as e:
        fh.log(syslog.LOG_ERR, "Exception: %s\n" % e)
        raise

    rabbits = {}

    latest_version = api_response["metadata"]["resourceVersion"]
    for rabbit in api_response["items"]:
        name = rabbit["metadata"]["name"]
        rabbits[name] = rabbit

    watchers.add_watch(
        Watch(k8s_api, RABBIT_CRD, latest_version, rabbit_state_change_cb, fh, rabbits)
    )
    return rabbits


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--watch-interval", type=int, default=5)
    args = parser.parse_args()

    k8s_client = k8s.config.new_client_from_config()
    try:
        k8s_api = k8s.client.CustomObjectsApi(k8s_client)
    except ApiException as rest_exception:
        if rest_exception.status == 403:
            raise Exception(
                "You must be logged in to the K8s or OpenShift cluster to continue"
            )
        raise

    fh = flux.Flux()
    serv_reg_fut = fh.service_register("dws")

    w = fh.msg_watcher_create(
        create_cb, FLUX_MSGTYPE_REQUEST, "dws.create", args=k8s_api
    )
    w.start()
    serv_reg_fut.get()

    with Watchers(fh, watch_interval=args.watch_interval) as watchers:
        init_rabbits(k8s_api, fh, watchers)
        watchers.add_watch(
            Watch(k8s_api, WORKFLOW_CRD, 0, workflow_state_change_cb, fh, k8s_api)
        )

        # This job event is used to close the race condition between the python
        # process starting and the `dws` service being registered. Once
        # https://github.com/flux-framework/flux-core/issues/3821 is
        # implemented/closed, this can be replaced with that solution.
        jobid = id_parse(os.environ["FLUX_JOB_ID"])
        Future(fh.job_raise(jobid, "exception", 7, "dws watchers setup")).get()

        fh.reactor_run()

        w.stop().destroy()


if __name__ == "__main__":
    main()
