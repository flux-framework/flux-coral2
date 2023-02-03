#!/usr/bin/env python3

"""
Script that acts as an intermediate between flux-core plugins and
Data Workflow Services.

Data Workflow Services is DWS for short.
"""

import os
import syslog
import json
import re
import functools
import argparse
import logging
import traceback
import pwd

import kubernetes as k8s
from kubernetes.client.rest import ApiException
import flux
from flux.hostlist import Hostlist
from flux.job import JobspecV1
from flux.job.JobID import id_parse
from flux.constants import FLUX_MSGTYPE_REQUEST
from flux.future import Future
from flux_k8s.crd import WORKFLOW_CRD, RABBIT_CRD, COMPUTE_CRD, SERVER_CRD
from flux_k8s.watch import Watchers, Watch
from flux_k8s.directivebreakdown import apply_breakdowns, build_allocation_sets


_WORKFLOWINFO_CACHE = {}  # maps jobids to WorkflowInfo objects
# Regex will match only rack-local allocations due to the rack\d+/ part
_XFS_REGEX = re.compile(r"rack\d+/(.*?)/ssd\d+")
_HOSTNAMES_TO_RABBITS = {}  # maps compute hostnames to rabbit names
LOGGER = logging.getLogger(__name__)


class WorkflowInfo:
    """Represents and holds information about a specific workflow object."""

    def __init__(self, name, create_rpc):
        self.name = name
        self.create_rpc = create_rpc
        self.setup_rpc = None
        self.post_run_rpc = None
        self.toredown = False
        self.deleted = False
        self.computes = None
        self.breakdowns = None


def message_callback_wrapper(func):
    """Decorator for msg_watcher callbacks.

    Catch exceptions and return failure messages.
    """

    @functools.wraps(func)
    def wrapper(fh, t, msg, k8s_api):
        try:
            func(fh, t, msg, k8s_api)
        except Exception as exc:
            fh.log(syslog.LOG_ERR, f"{os.path.basename(__file__)}: {exc}")
            fh.respond(msg, {"success": False, "errstr": str(exc)})
            LOGGER.exception("Error in responding to RPC: ")

    return wrapper


def move_workflow_desiredstate(workflow_name, desiredstate, k8s_api):
    """Helper function for moving workflow to a desiredState."""
    k8s_api.patch_namespaced_custom_object(
        *WORKFLOW_CRD, workflow_name, {"spec": {"desiredState": desiredstate}},
    )


@message_callback_wrapper
def create_cb(fh, t, msg, api_instance):
    """dws.create RPC callback. Creates a k8s Workflow object for a job.

    Triggered when a new job with a jobdw directive is submitted.

    Stashes the RPC for response when DWS gives us directivebreakdown objects.
    """
    dw_directives = msg.payload["dw_directives"]
    jobid = msg.payload["jobid"]
    userid = msg.payload["userid"]
    if isinstance(dw_directives, str):
        dw_directives = [dw_directives]
    if not isinstance(dw_directives, list):
        raise TypeError(
            f"Malformed dw_directives, not list or string: {dw_directives!r}"
        )
    workflow_name = f"fluxjob-{jobid}"
    spec = {
        "desiredState": "Proposal",
        "dwDirectives": dw_directives,
        "jobID": jobid,
        "userID": userid,
        "groupID": pwd.getpwuid(userid).pw_gid,
        "wlmID": str(jobid),
    }
    body = {
        "kind": "Workflow",
        "apiVersion": "/".join([WORKFLOW_CRD.group, WORKFLOW_CRD.version]),
        "spec": spec,
        "metadata": {"name": workflow_name, "namespace": WORKFLOW_CRD.namespace},
    }
    api_instance.create_namespaced_custom_object(
        *WORKFLOW_CRD, body,
    )
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


@message_callback_wrapper
def setup_cb(fh, t, msg, k8s_api):
    """dws.setup RPC callback.

    The dws.setup RPC is sent when the job has reached the RUN state
    (i.e. it has had resources assigned to it).

    Pass the resource information on to DWS, and move the job to the `setup`
    desiredState.
    """
    jobid = msg.payload["jobid"]
    hlist = Hostlist(msg.payload["R"]["execution"]["nodelist"]).uniq()
    sched_vertices = msg.payload["R"]["scheduling"]["graph"]["nodes"]
    workflow = _WORKFLOWINFO_CACHE[jobid]
    compute_nodes = [{"name": hostname} for hostname in hlist]
    local_allocations = aggregate_local_allocations(sched_vertices)
    nodes_per_nnf = {}
    for hostname in hlist:
        nnf_name = _HOSTNAMES_TO_RABBITS[hostname]
        nodes_per_nnf[nnf_name] = nodes_per_nnf.get(nnf_name, 0) + 1
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
            breakdown["status"]["storage"]["allocationSets"],
            local_allocations,
            nodes_per_nnf,
        )
        k8s_api.patch_namespaced_custom_object(
            SERVER_CRD.group,
            SERVER_CRD.version,
            breakdown["status"]["storage"]["reference"]["namespace"],
            SERVER_CRD.plural,
            breakdown["status"]["storage"]["reference"]["name"],
            {"spec": {"allocationSets": allocation_sets}},
        )
    workflow.setup_rpc = msg
    move_workflow_desiredstate(workflow.name, "Setup", k8s_api)


@message_callback_wrapper
def post_run_cb(fh, t, msg, k8s_api):
    """dws.post_run RPC callback.

    The dws.setup RPC is sent when the job has reached the CLEANUP state.

    If the job reached the RUN state, move the workflow to `post_run`.
    If the job did not reach the RUN state (exception path), move
    the workflow directly to `teardown`.
    """
    jobid = msg.payload["jobid"]
    if jobid not in _WORKFLOWINFO_CACHE:
        LOGGER.info(
            "Missing workflow cache entry for %i, which is only "
            "expected if a workflow object could not be created for the job",
            jobid,
        )
        return
    winfo = _WORKFLOWINFO_CACHE[jobid]
    run_started = msg.payload["run_started"]
    winfo.post_run_rpc = msg
    if winfo.toredown:
        # workflow has already been transitioned to 'teardown', do nothing
        return
    if not run_started:
        # the job hit an exception before beginning to run; transition
        # the workflow immediately to 'teardown'
        move_workflow_desiredstate(winfo.name, "Teardown", k8s_api)
        winfo.toredown = True
    else:
        move_workflow_desiredstate(winfo.name, "PostRun", k8s_api)


def state_complete(workflow, state):
    """Helper function for checking whether a workflow has completed a given state."""
    return (
        workflow["spec"]["desiredState"] == workflow["status"]["state"] == state
        and workflow["status"]["ready"]
    )


def workflow_state_change_cb(event, fh, k8s_api):
    """Exception-catching wrapper around _workflow_state_change_cb_inner."""
    try:
        workflow = event["object"]
        jobid = workflow["spec"]["jobID"]
        workflow_name = workflow["metadata"]["name"]
    except KeyError:
        LOGGER.exception("Invalid workflow in event stream: ")
        return
    try:
        winfo = _WORKFLOWINFO_CACHE[jobid]
    except KeyError:
        LOGGER.info("unrecognized workflow '%s' in event stream", workflow_name)
        return
    if event.get("TYPE") == "DELETED":
        # the workflow has been deleted, we can forget about it
        del _WORKFLOWINFO_CACHE[jobid]
        return
    try:
        _workflow_state_change_cb_inner(workflow, jobid, winfo, fh, k8s_api)
    except Exception as exc:
        LOGGER.exception(
            "Failed to process event update for workflow with jobid %s:", jobid
        )
        try:
            move_workflow_desiredstate(winfo.name, "Teardown", k8s_api)
        except Exception:
            LOGGER.exception(
                "Failed to move workflow with jobid %s to 'teardown' "
                "state after error: ",
                jobid,
            )
        else:
            winfo.toredown = True
        fh.job_raise(jobid, "exception", 0, "DWS/Rabbit interactions failed")


def _workflow_state_change_cb_inner(workflow, jobid, winfo, fh, k8s_api):
    if "state" not in workflow["status"]:
        # workflow was just submitted, DWS still needs to give workflow
        # a state of 'Proposal'
        return
    elif winfo.deleted:
        # deletion request has been submitted, nothing to do
        return
    elif state_complete(workflow, "Teardown"):
        # delete workflow object and tell DWS jobtap plugin that the job is done
        k8s_api.delete_namespaced_custom_object(*WORKFLOW_CRD, winfo.name)
        winfo.deleted = True
        if winfo.post_run_rpc is not None:
            fh.respond(winfo.post_run_rpc, {"success": True})  # ATM, does nothing
    elif winfo.toredown:
        # in the event of an exception, the workflow will skip to 'teardown'.
        # Without this early 'return', this function may try to
        # move a 'teardown' workflow to an earlier state because the
        # 'teardown' update is still in the k8s update queue.
        return
    elif state_complete(workflow, "Proposal"):
        winfo.computes = workflow["status"]["computes"]
        resources = winfo.create_rpc.payload["resources"]
        winfo.breakdowns = apply_breakdowns(k8s_api, workflow, resources)
        fh.respond(winfo.create_rpc, {"success": True, "resources": resources})
        winfo.create_rpc = None
    elif state_complete(workflow, "Setup"):
        # move workflow to next stage, DataIn
        move_workflow_desiredstate(winfo.name, "DataIn", k8s_api)
    elif state_complete(workflow, "DataIn"):
        # move workflow to next stage, PreRun
        move_workflow_desiredstate(winfo.name, "PreRun", k8s_api)
    elif state_complete(workflow, "PreRun"):
        # tell DWS jobtap plugin that the job can start
        fh.respond(
            winfo.setup_rpc,
            {"success": True, "variables": workflow["status"].get("env", {})},
        )
        winfo.setup_rpc = None
    elif state_complete(workflow, "PostRun"):
        # move workflow to next stage, DataOut
        move_workflow_desiredstate(winfo.name, "DataOut", k8s_api)
    elif state_complete(workflow, "DataOut"):
        # move workflow to next stage, teardown
        move_workflow_desiredstate(winfo.name, "Teardown", k8s_api)
        winfo.toredown = True
    elif workflow["status"].get("status") == "Error":
        # some errors are fatal, others are recoverable
        # HPE says to dump the whole workflow
        LOGGER.warning(
            "Workflow %s has error set, message is '%s', workflow is %s",
            winfo.name,
            workflow["status"].get("message", ""),
            workflow,
        )
        raise RuntimeError(
            "DWS has error set: "
            f"{workflow['status'].get('message', 'no error message provided')}"
        )


def rabbit_state_change_cb(event, fh, rabbits):
    obj = event["object"]
    name = obj["metadata"]["name"]
    capacity = obj["status"]["capacity"]
    status = obj["status"]["status"]

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

    if curr_rabbit["status"]["status"] != status:
        fh.log(syslog.LOG_DEBUG, f"Storage {name} status changed to {status}")
        # TODO: update status of vertex in resource graph
    if curr_rabbit["status"]["capacity"] != capacity:
        fh.log(
            syslog.LOG_DEBUG, f"Storage {name} capacity changed to {capacity}",
        )
        # TODO: update "percentDegraded" property of vertex in resource graph
        # TODO: update capacity of rabbit in resource graph (mark some slices down?)
    rabbits[name] = obj


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
    parser.add_argument("--verbose", "-v", action="count", default=0)
    args = parser.parse_args()
    try:
        jobid = id_parse(os.environ["FLUX_JOB_ID"])
    except KeyError as keyerr:
        raise RuntimeError("this script is meant to be run as a Flux job") from keyerr
    log_level = logging.WARNING
    if args.verbose > 1:
        log_level = logging.INFO
    if args.verbose > 2:
        log_level = logging.DEBUG
    logging.basicConfig(
        format="%(asctime)s - %(levelname)s - %(message)s", level=log_level,
    )
    k8s_client = k8s.config.new_client_from_config()
    try:
        k8s_api = k8s.client.CustomObjectsApi(k8s_client)
    except ApiException as rest_exception:
        if rest_exception.status == 403:
            raise Exception(
                "You must be logged in to the K8s or OpenShift cluster to continue"
            )
        raise
    api_response = k8s_api.list_cluster_custom_object(
        RABBIT_CRD.group, RABBIT_CRD.version, RABBIT_CRD.plural
    )
    for nnf in api_response["items"]:
        for compute in nnf["status"]["access"].get("computes", []):
            hostname = compute["name"]
            if hostname in _HOSTNAMES_TO_RABBITS:
                raise KeyError(
                    f"Same hostname ({hostname}) cannot be associated with "
                    f"both {nnf['metadata']['name']} and "
                    f"{_HOSTNAMES_TO_RABBITS[hostname]}"
                )
            _HOSTNAMES_TO_RABBITS[hostname] = nnf["metadata"]["name"]
    fh = flux.Flux()

    # register dws.create, dws.setup, and dws.post_run services.
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
