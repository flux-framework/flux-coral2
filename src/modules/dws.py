#!/usr/bin/env python3

import os
import syslog
import json
import argparse

import kubernetes as k8s
from kubernetes.client.rest import ApiException
import flux
from flux.hostlist import Hostlist
from flux.job import JobspecV1
from flux.job.JobID import id_parse
from flux.constants import FLUX_MSGTYPE_REQUEST
from flux.future import Future
from flux_k8s.crd import WORKFLOW_CRD, RABBIT_CRD, COMPUTE_CRD
from flux_k8s.watch import Watchers, Watch
from flux_k8s.directivebreakdown import apply_breakdowns


_WORKFLOW_NAME = "dws-workflow-test-{jobid}"
_WORKFLOWINFO_CACHE = {}


class WorkflowInfo:
    def __init__(self, create_rpc):
        self.create_rpc = create_rpc
        self.setup_rpc = None
        self.post_run_rpc = None
        self.environment = None


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
                "name": _WORKFLOW_NAME.format(jobid=jobid),
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
            *WORKFLOW_CRD, body,
        )
    except ApiException as e:
        fh.log(
            syslog.LOG_ERR,
            "Exception when calling CustomObjectsApi->"
            f"create_namespaced_custom_object: {e}",
        )
        payload = {"success": False, "errstr": str(e)}
        fh.respond(msg, payload)
    else:
        _WORKFLOWINFO_CACHE[jobid] = WorkflowInfo(msg)


def setup_cb(fh, t, msg, k8s_api):
    try:
        jobid = msg.payload["jobid"]
        R_dict = msg.payload["R"]
    except KeyError as e:
        fh.respond(msg, {"success": False, "errstr": str(e)})
        fh.log(syslog.LOG_ERR, f"Exception when extracting job data from payload: {e}")
        return
    compute_nodes = [
        {"name": hostname}
        for hostname in Hostlist(R_dict["execution"]["nodelist"]).uniq()
    ]
    # TODO: update servers custom resource
    resource_name = _WORKFLOW_NAME.format(jobid=jobid)
    try:
        k8s_api.patch_namespaced_custom_object(
            *COMPUTE_CRD, resource_name, {"data": compute_nodes}
        )
    except ApiException as e:
        fh.log(
            syslog.LOG_ERR,
            f"Exception when calling CustomObjectsApi->"
            f"patch_namespaced_custom_object for Compute {resource_name!r}: {e}",
        )
        fh.respond(msg, {"success": False, "errstr": str(e)})
        return
    _WORKFLOWINFO_CACHE[jobid].setup_rpc = msg
    if move_workflow_desiredstate(fh, msg, jobid, "setup", k8s_api):
        fh.respond(msg, {"success": True, "variables": {}})


def post_run_cb(fh, t, msg, k8s_api):
    try:
        jobid = msg.payload["jobid"]
    except KeyError as e:
        fh.respond(msg, {"success": False, "errstr": str(e)})
        fh.log(syslog.LOG_ERR, f"Exception when extracting job data from payload: {e}")
    else:
        _WORKFLOWINFO_CACHE[jobid].post_run_rpc = msg
        move_workflow_desiredstate(fh, msg, jobid, "post_run", k8s_api)


def move_workflow_desiredstate(fh, msg, jobid, desiredstate, k8s_api):
    workflow_name = _WORKFLOW_NAME.format(jobid=jobid)
    try:
        k8s_api.patch_namespaced_custom_object(
            *WORKFLOW_CRD, workflow_name, {"spec": {"desiredState": desiredstate}}
        )
    except ApiException as e:
        fh.log(
            syslog.LOG_ERR,
            f"Exception when patching {workflow_name!r} to "
            f"desiredState {desiredstate!r}: {e}",
        )
        fh.respond(msg, {"success": False, "errstr": str(e)})
        del _WORKFLOWINFO_CACHE[jobid]
        return False
    else:
        return True


def rabbit_state_change_cb(event, fh, rabbits):
    obj = event["object"]
    name = obj["metadata"]["name"]
    capacity = obj["data"]["capacity"]
    status = obj["data"]["status"]

    try:
        curr_rabbit = rabbits[name]
    except KeyError:
        fh.log(
            syslog.LOG_DEBUG,
            f"Just encountered an unknown Storage object ({name}) in the event stream",
        )
        # TODO: should never happen, but if it does,
        # insert the rabbit into the resource graph
        return

    if curr_rabbit["data"]["status"] != status:
        fh.log(syslog.LOG_DEBUG, f"Storage {name} status changed to {status}")
        # TODO: update status of vertex in resource graph
    if curr_rabbit["data"]["capacity"] != capacity:
        fh.log(
            syslog.LOG_DEBUG,
            f"Storage {name} capacity changed to {capacity}",
        )
        # TODO: update "percentDegraded" property of vertex in resource graph
        # TODO: update capacity of rabbit in resource graph (mark some slices down?)
    rabbits[name] = obj


def state_complete(workflow, state):
    return (
        workflow["spec"]["desiredState"] == workflow["status"]["state"] == state
        and workflow["status"]["ready"]
    )


def workflow_state_change_cb(event, fh, k8s_api):
    workflow = event["object"]
    jobid = workflow["spec"]["jobID"]
    try:
        winfo = _WORKFLOWINFO_CACHE[jobid]
    except KeyError:
        fh.log(syslog.LOG_DEBUG, f"Unrecognized workflow {jobid}, ignoring...")
        return
    if state_complete(workflow, "proposal"):
        try:
            resources = winfo.create_rpc.payload["resources"]
            apply_breakdowns(k8s_api, workflow, resources)
        except Exception as e:
            fh.log(
                syslog.LOG_ERR,
                f"Exception when applying breakdowns to jobspec resources: {e}",
            )
            fh.respond(winfo.create_rpc, {"success": False, "errstr": str(e)})
            del _WORKFLOWINFO_CACHE[jobid]
        else:
            fh.respond(winfo.create_rpc, {"success": True, "resources": resources})
        winfo.create_rpc = None
    elif state_complete(workflow, "setup") and False:  # TODO: put in servers resources
        # move workflow to next stage
        move_workflow_desiredstate(fh, winfo.setup_rpc, jobid, "data_in", k8s_api)
    elif state_complete(workflow, "data_in"):
        # move workflow to next stage
        move_workflow_desiredstate(fh, winfo.setup_rpc, jobid, "pre_run", k8s_api)
    elif state_complete(workflow, "pre_run"):
        # tell DWS jobtap plugin that the job can start
        fh.respond(winfo.setup_rpc, {"success": True})
        winfo.setup_rpc = None
    elif state_complete(workflow, "post_run"):
        # move workflow to next stage
        move_workflow_desiredstate(fh, winfo.post_run_rpc, jobid, "data_out", k8s_api)
    elif state_complete(workflow, "data_out"):
        # move workflow to next stage
        move_workflow_desiredstate(fh, winfo.post_run_rpc, jobid, "teardown", k8s_api)
    elif state_complete(workflow, "teardown"):
        # delete workflow object and tell DWS jobtap plugin that the job is done
        k8s_api.delete_namespaced_custom_object(
            *WORKFLOW_CRD, _WORKFLOW_NAME.format(jobid=jobid)
        )
        fh.respond(winfo.post_run_rpc, {"success": True})
        del _WORKFLOWINFO_CACHE[jobid]


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

    create_watcher = fh.msg_watcher_create(
        create_cb, FLUX_MSGTYPE_REQUEST, "dws.create", args=k8s_api
    )
    create_watcher.start()
    setup_watcher = fh.msg_watcher_create(
        setup_cb, FLUX_MSGTYPE_REQUEST, "dws.setup", args=k8s_api
    )
    setup_watcher.start()
    post_run_watcher = fh.msg_watcher_create(
        post_run_cb, FLUX_MSGTYPE_REQUEST, "dws.post_run", args=k8s_api
    )
    post_run_watcher.start()
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

        create_watcher.stop()
        create_watcher.destroy()
        setup_watcher.stop()
        setup_watcher.destroy()
        post_run_watcher.stop()
        post_run_watcher.destroy()


if __name__ == "__main__":
    main()
