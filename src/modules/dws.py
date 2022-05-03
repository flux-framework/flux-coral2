#!/usr/bin/env python3

import os
import syslog
import json
import re
import argparse

import kubernetes as k8s
from kubernetes.client.rest import ApiException
import flux
from flux.hostlist import Hostlist
from flux.job import JobspecV1
from flux.job.JobID import id_parse
from flux.constants import FLUX_MSGTYPE_REQUEST
from flux.future import Future
from flux_k8s.crd import WORKFLOW_CRD, RABBIT_CRD, COMPUTE_CRD, SERVER_CRD, STORAGE_CRD
from flux_k8s.watch import Watchers, Watch
from flux_k8s.directivebreakdown import apply_breakdowns, build_allocation_sets


_WORKFLOWINFO_CACHE = {}
# Regex will match only rack-local allocations due to the rack\d+/ part
_XFS_REGEX = re.compile(r"rack\d+/(.*?)/ssd\d+")
_HOSTNAMES_TO_RABBITS = {}


class WorkflowInfo:
    def __init__(self, name, create_rpc):
        self.name = name
        self.create_rpc = create_rpc
        self.setup_rpc = None
        self.post_run_rpc = None
        self.environment = None
        self.toredown = False
        self.computes = None
        self.breakdowns = None


def create_cb(fh, t, msg, arg):
    api_instance = arg
    try:
        dw_directives = msg.payload["dw_directives"]
        jobid = msg.payload["jobid"]
        userid = msg.payload["userid"]
    except Exception as e:
        fh.log(
            syslog.LOG_ERR, f"Exception when extracting job data from payload: {e}",
        )
        fh.respond(msg, {"success": False, "errstr": str(e)})
        return
    if isinstance(dw_directives, str):
        dw_directives = [dw_directives]
    if not isinstance(dw_directives, list):
        err = f"Malformed dw_directives, not list or string: {dw_directives}"
        fh.log(
            syslog.LOG_ERR, err,
        )
        fh.respond(msg, {"success": False, "errstr": err})
        return
    workflow_name = f"dws-workflow-test-{jobid}"
    spec = {
        "desiredState": "proposal",
        "dwDirectives": dw_directives,
        "jobID": jobid,
        "userID": userid,
        "wlmID": str(jobid),
    }
    body = {
        "kind": "Workflow",
        "apiVersion": "/".join([WORKFLOW_CRD.group, WORKFLOW_CRD.version]),
        "spec": spec,
        "metadata": {"name": workflow_name, "namespace": WORKFLOW_CRD.namespace},
    }
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
        _WORKFLOWINFO_CACHE[jobid] = WorkflowInfo(workflow_name, msg)


def aggregate_local_allocations(sched_vertices):
    """Find all node-local allocations associated with each NNF and aggregate them.

    Return a mapping from NNF name to allocation size in bytes.
    """
    allocations = {}
    for vtx in sched_vertices:
        if vtx["metadata"]["type"] == "ssd":
            nnf_name = re.search(
                _XFS_REGEX, vtx["metadata"]["paths"]["containment"]
            ).group(1)
            allocations[nnf_name] = (
                vtx["metadata"]["size"] * (1024 ** 3)
            ) + allocations.get(nnf_name, 0)
    return allocations


def setup_cb(fh, t, msg, k8s_api):
    try:
        jobid = msg.payload["jobid"]
        hlist = Hostlist(msg.payload["R"]["execution"]["nodelist"]).uniq()
        sched_vertices = msg.payload["R"]["scheduling"]["graph"]["nodes"]
        workflow = _WORKFLOWINFO_CACHE[jobid]
    except KeyError as e:
        fh.respond(msg, {"success": False, "errstr": str(e)})
        fh.log(syslog.LOG_ERR, f"Exception when extracting job data from payload: {e}")
        return
    compute_nodes = [{"name": hostname} for hostname in hlist]
    local_allocations = aggregate_local_allocations(sched_vertices)
    nodes_per_nnf = {}
    for hostname in hlist:
        nnf_name = _HOSTNAMES_TO_RABBITS[hostname]
        nodes_per_nnf[nnf_name] = nodes_per_nnf.get(nnf_name, 0) + 1
    try:
        k8s_api.patch_namespaced_custom_object(
            COMPUTE_CRD.group,
            COMPUTE_CRD.version,
            workflow.computes["namespace"],
            COMPUTE_CRD.plural,
            workflow.computes["name"],
            {"data": compute_nodes},
        )
        for breakdown in workflow.breakdowns:
            allocation_sets = build_allocation_sets(
                breakdown["status"]["allocationSet"], local_allocations, nodes_per_nnf
            )
            k8s_api.patch_namespaced_custom_object(
                SERVER_CRD.group,
                SERVER_CRD.version,
                breakdown["status"]["servers"]["namespace"],
                SERVER_CRD.plural,
                breakdown["status"]["servers"]["name"],
                {"spec": {"allocationSets": allocation_sets}},
            )
    except ApiException as e:
        fh.log(
            syslog.LOG_ERR,
            f"Exception when calling CustomObjectsApi->"
            f"patch_namespaced_custom_object for Compute/Server {workflow.name!r}: {e}",
        )
        fh.respond(msg, {"success": False, "errstr": str(e)})
        return
    workflow.setup_rpc = msg
    move_workflow_desiredstate(fh, msg, jobid, "setup", k8s_api)


def post_run_cb(fh, t, msg, k8s_api):
    try:
        jobid = msg.payload["jobid"]
        run_started = msg.payload["run_started"]
    except KeyError as e:
        fh.respond(msg, {"success": False, "errstr": str(e)})
        fh.log(syslog.LOG_ERR, f"Exception when extracting job data from payload: {e}")
    else:
        if jobid not in _WORKFLOWINFO_CACHE:
            # the job is done but we don't recognize it
            fh.log(syslog.LOG_ERR, f"Unrecognized job {jobid} in dws.post_run")
            fh.respond(msg, {"success": False, "errstr": ""})
            return
        _WORKFLOWINFO_CACHE[jobid].post_run_rpc = msg
        if not run_started:
            # the job hit an exception before beginning to run; transition
            # the workflow immediately to 'teardown'
            _WORKFLOWINFO_CACHE[jobid].toredown = True
            move_workflow_desiredstate(fh, msg, jobid, "teardown", k8s_api)
        else:
            move_workflow_desiredstate(fh, msg, jobid, "post_run", k8s_api)


def move_workflow_desiredstate(fh, msg, jobid, desiredstate, k8s_api):
    try:
        k8s_api.patch_namespaced_custom_object(
            *WORKFLOW_CRD,
            _WORKFLOWINFO_CACHE[jobid].name,
            {"spec": {"desiredState": desiredstate}},
        )
    except (ApiException, KeyError) as e:
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
            syslog.LOG_DEBUG, f"Storage {name} capacity changed to {capacity}",
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
    if state_complete(workflow, "teardown"):
        # delete workflow object and tell DWS jobtap plugin that the job is done
        k8s_api.delete_namespaced_custom_object(*WORKFLOW_CRD, winfo.name)
        fh.respond(winfo.post_run_rpc, {"success": True})
        del _WORKFLOWINFO_CACHE[jobid]
    elif winfo.toredown:
        # in the event of an exception, the workflow will skip to 'teardown'.
        # Without this early 'return', this function may try to
        # move a 'teardown' workflow to an earlier state because the
        # 'teardown' update is still in the k8s update queue.
        return
    elif state_complete(workflow, "proposal"):
        try:
            winfo.computes = workflow["status"]["computes"]
            resources = winfo.create_rpc.payload["resources"]
            winfo.breakdowns = apply_breakdowns(k8s_api, workflow, resources)
        except Exception as e:
            fh.log(
                syslog.LOG_ERR,
                f"Exception when applying breakdowns to jobspec resources: {e}",
            )
            fh.respond(winfo.create_rpc, {"success": False, "errstr": str(e)})
            del _WORKFLOWINFO_CACHE[jobid]
        else:
            import json

            with open("resources.json", "w") as fd:
                json.dump(resources, fd)
            print(f"RESOURCES:\n{json.dumps(resources)}\n")
            fh.respond(winfo.create_rpc, {"success": True, "resources": resources})
        winfo.create_rpc = None
    elif state_complete(workflow, "setup"):  # TODO: put in servers resources
        # move workflow to next stage
        move_workflow_desiredstate(fh, winfo.setup_rpc, jobid, "data_in", k8s_api)
    elif state_complete(workflow, "data_in"):
        # move workflow to next stage
        move_workflow_desiredstate(fh, winfo.setup_rpc, jobid, "pre_run", k8s_api)
    elif state_complete(workflow, "pre_run"):
        # tell DWS jobtap plugin that the job can start
        fh.respond(
            winfo.setup_rpc,
            {"success": True, "variables": workflow["status"].get("env", {})},
        )
        winfo.setup_rpc = None
    elif state_complete(workflow, "post_run"):
        # move workflow to next stage
        move_workflow_desiredstate(fh, winfo.post_run_rpc, jobid, "data_out", k8s_api)
    elif state_complete(workflow, "data_out"):
        # move workflow to next stage
        move_workflow_desiredstate(fh, winfo.post_run_rpc, jobid, "teardown", k8s_api)
    elif state_complete(workflow, "teardown"):
        # delete workflow object and tell DWS jobtap plugin that the job is done
        k8s_api.delete_namespaced_custom_object(*WORKFLOW_CRD, winfo.name)
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
    api_response = k8s_api.list_cluster_custom_object(STORAGE_CRD.group, STORAGE_CRD.version, STORAGE_CRD.plural)
    for nnf in api_response["items"]:
        for compute in nnf["data"]["access"]["computes"]:
            hostname = compute["name"]
            if hostname in _HOSTNAMES_TO_RABBITS:
                raise KeyError(f"Same hostname ({hostname}) cannot be associated with "
                    f"both {nnf['metadata']['name']} and "
                    f"{_HOSTNAMES_TO_RABBITS[hostname]}")
            _HOSTNAMES_TO_RABBITS[hostname] = nnf["metadata"]["name"]
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
