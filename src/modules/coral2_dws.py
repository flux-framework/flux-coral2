#!/usr/bin/env python3

"""
Script that acts as an intermediate between flux-core plugins and
Data Workflow Services.

Data Workflow Services is DWS for short.
"""

import os
import sys
import syslog
import json
import functools
import argparse
import logging
import pwd
import time
import pathlib

import kubernetes as k8s
from kubernetes.client.rest import ApiException
from kubernetes.config.config_exception import ConfigException
import urllib3

import flux
from flux.hostlist import Hostlist
from flux.job.JobID import id_parse
from flux.constants import FLUX_MSGTYPE_REQUEST
from flux.future import Future
from flux_k8s.crd import (
    WORKFLOW_CRD,
    RABBIT_CRD,
    COMPUTE_CRD,
    SERVER_CRD,
)
from flux_k8s.watch import Watchers, Watch
from flux_k8s import directivebreakdown


_WORKFLOWINFO_CACHE = {}  # maps jobids to WorkflowInfo objects
_HOSTNAMES_TO_RABBITS = {}  # maps compute hostnames to rabbit names
_RABBITS_TO_HOSTLISTS = {}  # maps rabbits to hostlists
LOGGER = logging.getLogger(__name__)
WORKFLOWS_IN_TC = set()  # tc for TransientCondition
WORKFLOW_NAME_PREFIX = "fluxjob-"
WORKFLOW_NAME_FORMAT = WORKFLOW_NAME_PREFIX + "{jobid}"
_MIN_ALLOCATION_SIZE = 4  # minimum rabbit allocation size
_FINALIZER = "flux-framework.readthedocs.io/workflow"
_EXITCODE_NORESTART = 3  # exit code indicating to systemd not to restart


class WorkflowInfo:
    """Represents and holds information about a specific workflow object."""

    def __init__(self, jobid, name=None, resources=None):
        self.jobid = jobid
        if name is None:
            self.name = WORKFLOW_NAME_FORMAT.format(jobid=jobid)
        else:
            self.name = name  # name of the k8s workflow
        self.resources = resources  # jobspec 'resources' field
        self.transient_condition = None  # may be a TransientConditionInfo
        self.toredown = False  # True if workflows has been moved to teardown
        self.deleted = False  # True if delete request has been sent to k8s
        self.rabbits = None


class TransientConditionInfo:
    """Represents and holds information about a TransientCondition for a workflow."""

    def __init__(self, workflow):
        self.workflow = workflow  # workflow that hit the Transientcondition
        self.last_time = time.time()  # time in seconds of last TransientCondition
        # message associated with last TransientCondition
        self.last_message = None


def log_rpc_response(rpc):
    """RPC callback for logging response."""
    try:
        msg = rpc.get()
    except Exception as exc:
        LOGGER.warning("RPC error %s", str(exc))
    else:
        if msg is not None:
            LOGGER.debug("RPC response was %s", msg)


def fetch_rabbits(k8s_api, workflow_computes):
    """Fetch all the rabbits associated with this workflow"""
    response = k8s_api.get_namespaced_custom_object(
        COMPUTE_CRD.group,
        COMPUTE_CRD.version,
        workflow_computes["namespace"],
        COMPUTE_CRD.plural,
        workflow_computes["name"],
    )
    return list(set(_HOSTNAMES_TO_RABBITS[entry["name"]] for entry in response["data"]))


def message_callback_wrapper(func):
    """Decorator for msg_watcher callbacks.

    Catch exceptions and return failure messages.
    """

    @functools.wraps(func)
    def wrapper(handle, arg, msg, k8s_api):
        try:
            func(handle, arg, msg, k8s_api)
        except Exception as exc:
            try:
                jobid = msg.payload["jobid"]
                topic = msg.topic
            except Exception:
                topic = jobid = None
            try:
                # only k8s APIExceptions will have a JSON message body,
                # but try to extract it out of every exception for simplicity
                errstr = json.loads(exc.body)["message"]
            except (AttributeError, TypeError, KeyError):
                errstr = str(exc)
            handle.log(syslog.LOG_ERR, f"{os.path.basename(__file__)}: {errstr}")
            handle.respond(msg, {"success": False, "errstr": errstr})
            LOGGER.error(
                "Error in responding to %s RPC for %s: %s", topic, jobid, errstr
            )
        else:
            handle.respond(msg, {"success": True})

    return wrapper


def remove_finalizer(workflow_name, k8s_api, workflow):
    """Remove the finalizer from the workflow so it can be deleted."""
    try:
        workflow["metadata"]["finalizers"].remove(_FINALIZER)
    except ValueError:
        # finalizer is not present, nothing to do
        pass
    else:
        k8s_api.patch_namespaced_custom_object(
            *WORKFLOW_CRD,
            workflow_name,
            {"metadata": {"finalizers": workflow["metadata"]["finalizers"]}},
        )


def move_workflow_to_teardown(handle, winfo, k8s_api, workflow=None):
    """Helper function for moving a workflow to Teardown."""
    if workflow is None:
        workflow = k8s_api.get_namespaced_custom_object(*WORKFLOW_CRD, winfo.name)
    try:
        kvsdir = flux.job.job_kvs(handle, winfo.jobid)
        kvsdir["rabbit_workflow"] = workflow
        kvsdir.commit()
    except Exception:
        LOGGER.exception(
            "Failed to update KVS for job %s: workflow is", winfo.jobid, workflow
        )
    if LOGGER.isEnabledFor(logging.INFO):
        try:
            api_response = k8s_api.list_cluster_custom_object(
                group="nnf.cray.hpe.com",
                version="v1alpha1",
                plural="nnfdatamovements",
                label_selector=(
                    f"dataworkflowservices.github.io/workflow.name={winfo.name},"
                    "dataworkflowservices.github.io/workflow.namespace=default"
                ),
            )
        except Exception as exc:
            LOGGER.info(
                "Failed to fetch nnfdatamovement crds for workflow '%s': %s",
                winfo.name,
                exc,
            )
        else:
            for crd in api_response["items"]:
                LOGGER.info(
                    "Found nnfdatamovement crd for workflow '%s': %s",
                    winfo.name,
                    json.dumps(crd),
                )
    try:
        workflow["metadata"]["finalizers"].remove(_FINALIZER)
    except ValueError:
        pass
    k8s_api.patch_namespaced_custom_object(
        *WORKFLOW_CRD,
        winfo.name,
        {
            "spec": {"desiredState": "Teardown"},
            "metadata": {"finalizers": workflow["metadata"]["finalizers"]},
        },
    )
    winfo.toredown = True


def move_workflow_desiredstate(workflow_name, desiredstate, k8s_api):
    """Helper function for moving workflow to a desiredState."""
    k8s_api.patch_namespaced_custom_object(
        *WORKFLOW_CRD,
        workflow_name,
        {"spec": {"desiredState": desiredstate}},
    )


@message_callback_wrapper
def create_cb(handle, _t, msg, api_instance):
    """dws.create RPC callback. Creates a k8s Workflow object for a job.

    Triggered when a new job with a jobdw directive is submitted.
    """
    dw_directives = msg.payload["dw_directives"]
    jobid = msg.payload["jobid"]
    userid = msg.payload["userid"]
    if isinstance(dw_directives, str):
        # the string may contain multiple #DW directives
        dw_directives = dw_directives.split("#DW ")
        # remove any blank entries that resulted and add back "#DW "
        dw_directives = ["#DW " + dw.strip() for dw in dw_directives if dw.strip()]
    if not isinstance(dw_directives, list):
        raise TypeError(
            f"Malformed dw_directives, not list or string: {dw_directives!r}"
        )
    workflow_name = WORKFLOW_NAME_FORMAT.format(jobid=jobid)
    spec = {
        "desiredState": "Proposal",
        "dwDirectives": dw_directives,
        "jobID": flux.job.JobID(jobid).f58.replace("ƒ", "f"),
        "userID": userid,
        "groupID": pwd.getpwuid(userid).pw_gid,
        "wlmID": "flux",
    }
    body = {
        "kind": "Workflow",
        "apiVersion": "/".join([WORKFLOW_CRD.group, WORKFLOW_CRD.version]),
        "spec": spec,
        "metadata": {
            "name": workflow_name,
            "namespace": WORKFLOW_CRD.namespace,
            "finalizers": [_FINALIZER],
        },
    }
    api_instance.create_namespaced_custom_object(
        *WORKFLOW_CRD,
        body,
    )
    # add workflow to the cache
    _WORKFLOWINFO_CACHE[jobid] = WorkflowInfo(
        jobid, workflow_name, msg.payload["resources"]
    )
    # submit a memo providing the name of the workflow
    handle.rpc(
        "job-manager.memo",
        payload={"id": jobid, "memo": {"rabbit_workflow": workflow_name}},
    ).then(log_rpc_response)


@message_callback_wrapper
def setup_cb(handle, _t, msg, k8s_api):
    """dws.setup RPC callback.

    The dws.setup RPC is sent when the job has reached the RUN state
    (i.e. it has had resources assigned to it).

    Pass the resource information on to DWS, and move the job to the `setup`
    desiredState.
    """
    jobid = msg.payload["jobid"]
    hlist = Hostlist(msg.payload["R"]["execution"]["nodelist"]).uniq()
    workflow_name = WORKFLOW_NAME_FORMAT.format(jobid=jobid)
    workflow = k8s_api.get_namespaced_custom_object(*WORKFLOW_CRD, workflow_name)
    compute_nodes = [{"name": hostname} for hostname in hlist]
    nodes_per_nnf = {}
    for hostname in hlist:
        nnf_name = _HOSTNAMES_TO_RABBITS[hostname]
        nodes_per_nnf[nnf_name] = nodes_per_nnf.get(nnf_name, 0) + 1
    handle.rpc(
        "job-manager.memo",
        payload={
            "id": jobid,
            "memo": {"rabbits": Hostlist(nodes_per_nnf.keys()).encode()},
        },
    ).then(log_rpc_response)
    k8s_api.patch_namespaced_custom_object(
        COMPUTE_CRD.group,
        COMPUTE_CRD.version,
        workflow["status"]["computes"]["namespace"],
        COMPUTE_CRD.plural,
        workflow["status"]["computes"]["name"],
        {"data": compute_nodes},
    )
    for breakdown in directivebreakdown.fetch_breakdowns(k8s_api, workflow):
        # if a breakdown doesn't have a storage field (e.g. persistentdw) directives
        # ignore it and proceed
        if "storage" in breakdown["status"]:
            allocation_sets = directivebreakdown.build_allocation_sets(
                breakdown["status"]["storage"]["allocationSets"],
                nodes_per_nnf,
                hlist,
                _MIN_ALLOCATION_SIZE,
            )
            k8s_api.patch_namespaced_custom_object(
                SERVER_CRD.group,
                SERVER_CRD.version,
                breakdown["status"]["storage"]["reference"]["namespace"],
                SERVER_CRD.plural,
                breakdown["status"]["storage"]["reference"]["name"],
                {"spec": {"allocationSets": allocation_sets}},
            )
    winfo = _WORKFLOWINFO_CACHE.setdefault(jobid, WorkflowInfo(jobid))
    winfo.rabbits = list(nodes_per_nnf.keys())
    move_workflow_desiredstate(workflow_name, "Setup", k8s_api)


@message_callback_wrapper
def post_run_cb(handle, _t, msg, k8s_api):
    """dws.post_run RPC callback.

    The dws.post_run RPC is sent when the job has reached the CLEANUP state.

    If the job reached the RUN state, move the workflow to `post_run`.
    If the job did not reach the RUN state (exception path), move
    the workflow directly to `teardown`.
    """
    jobid = msg.payload["jobid"]
    winfo = _WORKFLOWINFO_CACHE.setdefault(jobid, WorkflowInfo(jobid))
    run_started = msg.payload["run_started"]
    if winfo.toredown:
        # workflow has already been transitioned to 'teardown', do nothing
        return
    if not run_started:
        # the job hit an exception before beginning to run; transition
        # the workflow immediately to 'teardown'
        move_workflow_to_teardown(handle, winfo, k8s_api)
    else:
        move_workflow_desiredstate(winfo.name, "PostRun", k8s_api)


def state_complete(workflow, state):
    """Helper function for checking whether a workflow has completed a given state."""
    return (
        workflow["spec"]["desiredState"] == workflow["status"]["state"] == state
        and workflow["status"]["ready"]
    )


def state_active(workflow, state):
    """Helper function for checking whether a workflow is working on a given state."""
    return workflow["spec"]["desiredState"] == workflow["status"]["state"] == state


def workflow_state_change_cb(event, handle, k8s_api, disable_fluxion):
    """Exception-catching wrapper around _workflow_state_change_cb_inner."""
    try:
        workflow = event["object"]
        jobid = int(flux.job.JobID(workflow["spec"]["jobID"]))
        workflow_name = workflow["metadata"]["name"]
    except KeyError:
        LOGGER.exception("Invalid event %s in workflow stream: ", event)
        return
    if not workflow_name.startswith(WORKFLOW_NAME_PREFIX):
        LOGGER.warning("unrecognized workflow '%s' in event stream", workflow_name)
        return
    winfo = _WORKFLOWINFO_CACHE.setdefault(jobid, WorkflowInfo(jobid))
    if event.get("TYPE") == "DELETED":
        # the workflow has been deleted, we can forget about it
        del _WORKFLOWINFO_CACHE[jobid]
        return
    try:
        _workflow_state_change_cb_inner(
            workflow, jobid, winfo, handle, k8s_api, disable_fluxion
        )
    except Exception:
        LOGGER.exception(
            "Failed to process event update for workflow '%s' with jobid %s:",
            workflow_name,
            jobid,
        )
        try:
            move_workflow_to_teardown(handle, winfo, k8s_api, workflow)
        except ApiException:
            LOGGER.exception(
                "Failed to move workflow '%s' with jobid %s to 'teardown' "
                "state after error: ",
                workflow_name,
                jobid,
            )
        else:
            winfo.toredown = True
        handle.job_raise(jobid, "exception", 0, "DWS/Rabbit interactions failed")


def _workflow_state_change_cb_inner(
    workflow, jobid, winfo, handle, k8s_api, disable_fluxion
):
    if "state" not in workflow["status"]:
        # workflow was just submitted, DWS still needs to give workflow
        # a state of 'Proposal'
        return
    if winfo.deleted:
        # deletion request has been submitted, nothing to do
        return
    if state_active(workflow, "Teardown") and not state_complete(workflow, "Teardown"):
        # Remove the finalizer as soon as the workflow begins working on its
        # teardown state.
        remove_finalizer(winfo.name, k8s_api, workflow)
    elif state_complete(workflow, "Teardown"):
        # Delete workflow object and tell DWS jobtap plugin that the job is done.
        # Attempt to remove the finalizer again in case the state transitioned
        # too quickly for it to be noticed earlier.
        remove_finalizer(winfo.name, k8s_api, workflow)
        k8s_api.delete_namespaced_custom_object(*WORKFLOW_CRD, winfo.name)
        winfo.deleted = True
        handle.rpc("job-manager.dws.epilog-remove", payload={"id": jobid}).then(
            log_rpc_response
        )
    elif winfo.toredown:
        # in the event of an exception, the workflow will skip to 'teardown'.
        # Without this early 'return', this function may try to
        # move a 'teardown' workflow to an earlier state because the
        # 'teardown' update is still in the k8s update queue.
        return
    elif state_complete(workflow, "Proposal"):
        resources = winfo.resources
        if resources is None:
            resources = flux.job.kvslookup.job_kvs_lookup(handle, jobid)["jobspec"][
                "resources"
            ]
        if not disable_fluxion:
            resources, copy_offload = directivebreakdown.apply_breakdowns(
                k8s_api, workflow, resources, _MIN_ALLOCATION_SIZE
            )
        else:
            _, copy_offload = directivebreakdown.apply_breakdowns(
                k8s_api, workflow, resources, _MIN_ALLOCATION_SIZE
            )
        handle.rpc(
            "job-manager.dws.resource-update",
            payload={
                "id": jobid,
                "resources": resources,
                "copy-offload": copy_offload,
            },
        ).then(log_rpc_response)
    elif state_complete(workflow, "Setup"):
        # move workflow to next stage, DataIn
        move_workflow_desiredstate(winfo.name, "DataIn", k8s_api)
    elif state_complete(workflow, "DataIn"):
        # move workflow to next stage, PreRun
        move_workflow_desiredstate(winfo.name, "PreRun", k8s_api)
    elif state_complete(workflow, "PreRun"):
        # tell DWS jobtap plugin that the job can start
        if winfo.rabbits is not None:
            rabbits = winfo.rabbits
        else:
            rabbits = fetch_rabbits(k8s_api, workflow["status"]["computes"])
        handle.rpc(
            "job-manager.dws.prolog-remove",
            payload={
                "id": jobid,
                "variables": workflow["status"].get("env", {}),
                "rabbits": {
                    rabbit: _RABBITS_TO_HOSTLISTS[rabbit] for rabbit in rabbits
                },
            },
        ).then(log_rpc_response)
    elif state_complete(workflow, "PostRun"):
        # move workflow to next stage, DataOut
        move_workflow_desiredstate(winfo.name, "DataOut", k8s_api)
    elif state_complete(workflow, "DataOut"):
        # move workflow to next stage, teardown
        move_workflow_to_teardown(handle, winfo, k8s_api, workflow)
    if workflow["status"].get("status") == "Error":
        # a fatal error has occurred in the workflows, raise a job exception
        handle.job_raise(
            jobid,
            "exception",
            0,
            "DWS/Rabbit interactions failed: workflow hit an error: "
            f"{workflow['status'].get('message', '')}",
        )
        # for most states, raising an exception should be enough to trigger other logic
        # that eventually moves the workflow to Teardown. However, if the
        # workflow is in PostRun or DataOut, the exception won't affect the dws-epilog
        # action holding the job, so the workflow should be moved to Teardown now.
        if workflow["spec"]["desiredState"] in ("PostRun", "DataOut"):
            move_workflow_to_teardown(handle, winfo, k8s_api, workflow)
    elif workflow["status"].get("status") == "TransientCondition":
        # a potentially fatal error has occurred, but may resolve itself
        LOGGER.info(
            "Workflow '%s' has TransientCondition set, message is '%s', workflow is %s",
            winfo.name,
            workflow["status"].get("message", ""),
            workflow,
        )
        if winfo.transient_condition is None:
            winfo.transient_condition = TransientConditionInfo(workflow)
        winfo.transient_condition.last_tc_message = workflow["status"].get(
            "message", ""
        )
        WORKFLOWS_IN_TC.add(winfo)
    else:
        winfo.transient_condition = None
        WORKFLOWS_IN_TC.discard(winfo)


def drain_offline_nodes(handle, rabbit_name, nodelist, disable_draining, allowlist):
    if disable_draining:
        return
    offline_nodes = Hostlist()
    for compute_node in nodelist:
        if compute_node["status"] != "Ready" and (
            allowlist is None or compute_node["name"] in allowlist
        ):
            offline_nodes.append(compute_node["name"])
    if offline_nodes:
        encoded_hostlist = offline_nodes.encode()
        LOGGER.debug("Draining nodes %s", encoded_hostlist)
        handle.rpc(
            "resource.drain",
            payload={
                "targets": encoded_hostlist,
                "mode": "update",
                "reason": f"rabbit {rabbit_name} lost connection",
            },
            nodeid=0,
        ).then(log_rpc_response)


def mark_rabbit(handle, status, resource_path, ssdcount, name):
    """Send an RPC to mark a rabbit as up or down."""
    if status == "Ready":
        LOGGER.debug("Marking rabbit %s as up", name)
        status = "up"
    else:
        LOGGER.debug("Marking rabbit %s as down, status is %s", name, status)
        status = "down"
    for ssdnum in range(ssdcount):
        payload = {"resource_path": resource_path + f"/ssd{ssdnum}", "status": status}
        handle.rpc("sched-fluxion-resource.set_status", payload).then(log_rpc_response)


def rabbit_state_change_cb(
    event, handle, rabbit_rpaths, disable_draining, disable_fluxion, allowlist
):
    """Callback firing when a Storage object changes.

    Marks a rabbit as up or down.
    """
    rabbit = event["object"]
    name = rabbit["metadata"]["name"]
    status = rabbit["status"]["status"]
    if name not in rabbit_rpaths:
        LOGGER.error(
            "Encountered an unknown Storage object '%s' in the event stream", name
        )
        return
    if not disable_fluxion:
        mark_rabbit(handle, status, *rabbit_rpaths[name], name)
    drain_offline_nodes(
        handle,
        name,
        rabbit["status"]["access"].get("computes", []),
        disable_draining,
        allowlist,
    )
    # TODO: add some check for whether rabbit capacity has changed
    # TODO: update capacity of rabbit in resource graph (mark some slices down?)


def map_rabbits_to_fluxion_paths(graph_path):
    """Read the fluxion resource graph and map rabbit hostnames to resource paths."""
    rabbit_rpaths = {}
    try:
        with open(graph_path) as fd:
            nodes = json.load(fd)["scheduling"]["graph"]["nodes"]
    except Exception as exc:
        raise ValueError(
            f"Could not load rabbit resource graph data from {graph_path} "
            "expected a Flux R file augmented with JGF from 'flux-dws2jgf'"
        ) from exc
    for vertex in nodes:
        metadata = vertex["metadata"]
        if metadata["type"] == "rack" and "rabbit" in metadata["properties"]:
            rabbit_rpaths[metadata["properties"]["rabbit"]] = (
                metadata["paths"]["containment"],
                int(metadata["properties"].get("ssdcount", 36)),
            )
    return rabbit_rpaths


def init_rabbits(k8s_api, handle, watchers, args):
    """Watch every rabbit ('Storage' resources in k8s) known to k8s.

    Whenever a Storage resource changes, mark it as 'up' or 'down' in Fluxion.

    Also, to initialize, check the status of all rabbits and mark each one as up or
    down, because status may have changed while this service was inactive.
    """
    api_response = k8s_api.list_namespaced_custom_object(*RABBIT_CRD)
    if not args.disable_fluxion:
        rabbit_rpaths = map_rabbits_to_fluxion_paths(args.resourcegraph)
    else:
        rabbit_rpaths = {}
    resource_version = 0
    if args.drain_queues is not None:
        rset = flux.resource.resource_list(handle).get().all
        allowlist = set(
            rset.copy_constraint({"properties": args.drain_queues}).nodelist
        )
        if not allowlist:
            raise ValueError(
                f"No resources found associated with queues {args.drain_queues}"
            )
    else:
        allowlist = None
    for rabbit in api_response["items"]:
        name = rabbit["metadata"]["name"]
        resource_version = max(
            resource_version, int(rabbit["metadata"]["resourceVersion"])
        )
        if args.disable_fluxion:
            # don't mark the rabbit up or down but add the rabbit to the mapping
            rabbit_rpaths[name] = None
        elif name not in rabbit_rpaths:
            LOGGER.error(
                "Encountered an unknown Storage object '%s' in the event stream", name
            )
        else:
            mark_rabbit(handle, rabbit["status"]["status"], *rabbit_rpaths[name], name)
        drain_offline_nodes(
            handle,
            name,
            rabbit["status"]["access"].get("computes", []),
            args.disable_compute_node_draining,
            allowlist,
        )
    watchers.add_watch(
        Watch(
            k8s_api,
            RABBIT_CRD,
            resource_version,
            rabbit_state_change_cb,
            handle,
            rabbit_rpaths,
            args.disable_compute_node_draining,
            args.disable_fluxion,
            allowlist,
        )
    )


def kill_workflows_in_tc(_reactor, watcher, _r, arg):
    """Callback firing every (tc_timeout / 2) seconds.

    Raise exceptions on jobs stuck in TransientCondition for more than
    tc_timeout seconds.
    """
    tc_timeout, k8s_api = arg
    curr_time = time.time()
    # iterate over a copy of the set
    # otherwise an exception occurs because we modify the set as we
    # iterate over it.
    for winfo in WORKFLOWS_IN_TC.copy():
        if curr_time - winfo.transient_condition.last_time > tc_timeout:
            watcher.flux_handle.job_raise(
                winfo.jobid,
                "exception",
                0,
                "DWS/Rabbit interactions failed: workflow in 'TransientCondition' "
                f"state too long: {winfo.transient_condition.last_message}",
            )
            # for most states, raising an exception should be enough to trigger other
            # logic that eventually moves the workflow to Teardown. However, if the
            # workflow is in PostRun or DataOut, the exception won't affect the
            # dws-epilog action holding the job, so the workflow should be moved
            # to Teardown now.
            if winfo.transient_condition.workflow["spec"]["desiredState"] in (
                "PostRun",
                "DataOut",
            ):
                move_workflow_to_teardown(
                    watcher.flux_handle,
                    winfo,
                    k8s_api,
                    winfo.transient_condition.workflow,
                )
            WORKFLOWS_IN_TC.discard(winfo)


def setup_parsing():
    """Set up argument parsing."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--watch-interval",
        "-w",
        type=int,
        default=5,
        help="Interval in seconds to issue k8s watch requests",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="count",
        default=0,
        help="Increase verbosity of output",
    )
    parser.add_argument(
        "--transient-condition-timeout",
        "-e",
        type=float,
        default=10,
        metavar="N",
        help="Kill workflows in TransientCondition state for more than 'N' seconds",
    )
    parser.add_argument(
        "--kubeconfig",
        "-k",
        default=None,
        metavar="FILE",
        help="Path to kubeconfig file to use",
    )
    parser.add_argument(
        "--resourcegraph",
        "-r",
        default=str(pathlib.Path("/etc/flux/system/R").absolute()),
        metavar="FILE",
        help="Path to file containing Fluxion JGF resource graph",
    )
    parser.add_argument(
        "--min-allocation-size",
        "-m",
        default=_MIN_ALLOCATION_SIZE,
        metavar="N",
        help="Minimum allocation size of rabbit allocations, in bytes",
    )
    parser.add_argument(
        "--disable-compute-node-draining",
        action="store_true",
        help="Disable the draining of compute nodes based on k8s status",
    )
    parser.add_argument(
        "--drain-queues",
        nargs="+",
        help="Target only the nodes in the given queues for draining",
    )
    parser.add_argument(
        "--disable-fluxion",
        action="store_true",
        help="Disable Fluxion scheduling of rabbits",
    )
    return parser


def config_logging(args):
    """Configure logging for the script."""
    log_level = logging.WARNING
    if args.verbose > 0:
        log_level = logging.INFO
    if args.verbose > 1:
        log_level = logging.DEBUG
    logging.basicConfig(
        format="%(asctime)s - %(levelname)s - %(message)s",
        level=log_level,
    )


def populate_rabbits_dict(k8s_api):
    """Populate the _HOSTNAMES_TO_RABBITS dictionary."""
    api_response = k8s_api.list_cluster_custom_object(
        RABBIT_CRD.group, RABBIT_CRD.version, RABBIT_CRD.plural
    )
    for nnf in api_response["items"]:
        hlist = Hostlist()
        for compute in nnf["status"]["access"].get("computes", []):
            hostname = compute["name"]
            hlist.append(hostname)
            if hostname in _HOSTNAMES_TO_RABBITS:
                raise KeyError(
                    f"Same hostname ({hostname}) cannot be associated with "
                    f"both {nnf['metadata']['name']} and "
                    f"{_HOSTNAMES_TO_RABBITS[hostname]}"
                )
            _HOSTNAMES_TO_RABBITS[hostname] = nnf["metadata"]["name"]
        _RABBITS_TO_HOSTLISTS[nnf["metadata"]["name"]] = hlist.encode()


def register_services(handle, k8s_api):
    """register dws.create, dws.setup, and dws.post_run services."""
    serv_reg_fut = handle.service_register("dws")
    create_watcher = handle.msg_watcher_create(
        create_cb, FLUX_MSGTYPE_REQUEST, "dws.create", args=k8s_api
    )
    create_watcher.start()
    setup_watcher = handle.msg_watcher_create(
        setup_cb, FLUX_MSGTYPE_REQUEST, "dws.setup", args=k8s_api
    )
    setup_watcher.start()
    post_run_watcher = handle.msg_watcher_create(
        post_run_cb, FLUX_MSGTYPE_REQUEST, "dws.post_run", args=k8s_api
    )
    post_run_watcher.start()
    serv_reg_fut.get()
    return (create_watcher, setup_watcher, post_run_watcher)


def raise_self_exception(handle):
    """If this script is being run as a job, raise a low-severity job exception

    This job event is used to close the race condition between the python
    process starting and the `dws` service being registered, for
    testing purposes.
    Once https://github.com/flux-framework/flux-core/issues/3821 is
    implemented/closed, this can be replaced with that solution.

    Also, remove FLUX_KVS_NAMESPACE from the environment, because otherwise
    KVS lookups will look relative to that namespace, changing the behavior
    relative to when the script runs as a service.
    """
    try:
        jobid = id_parse(os.environ["FLUX_JOB_ID"])
    except KeyError:
        return
    del os.environ["FLUX_KVS_NAMESPACE"]
    Future(handle.job_raise(jobid, "exception", 7, "dws watchers setup")).get()


def main():
    """Init script, begin processing of services."""
    args = setup_parsing().parse_args()
    _MIN_ALLOCATION_SIZE = args.min_allocation_size
    config_logging(args)
    try:
        k8s_client = k8s.config.new_client_from_config(config_file=args.kubeconfig)
    except ConfigException:
        LOGGER.exception("Kubernetes misconfigured, service will shut down")
        sys.exit(_EXITCODE_NORESTART)
    try:
        k8s_api = k8s.client.CustomObjectsApi(k8s_client)
    except ApiException as rest_exception:
        if rest_exception.status == 403:
            LOGGER.exception(
                "You must be logged in to the K8s or OpenShift cluster to continue"
            )
            sys.exit(_EXITCODE_NORESTART)
        LOGGER.exception("Cannot access kubernetes, service will shut down")
        sys.exit(_EXITCODE_NORESTART)
    populate_rabbits_dict(k8s_api)
    handle = flux.Flux()
    # create a timer watcher for killing workflows that have been stuck in
    # the "Error" state for too long
    handle.timer_watcher_create(
        args.transient_condition_timeout / 2,
        kill_workflows_in_tc,
        repeat=args.transient_condition_timeout / 2,
        args=(args.transient_condition_timeout, k8s_api),
    ).start()
    # start watching k8s workflow resources and operate on them when updates occur
    # or new RPCs are received
    with Watchers(handle, watch_interval=args.watch_interval) as watchers:
        init_rabbits(
            k8s_api,
            handle,
            watchers,
            args,
        )
        services = register_services(handle, k8s_api)
        watchers.add_watch(
            Watch(
                k8s_api,
                WORKFLOW_CRD,
                0,
                workflow_state_change_cb,
                handle,
                k8s_api,
                args.disable_fluxion,
            )
        )
        raise_self_exception(handle)

        handle.reactor_run()

        for service in services:
            service.stop()
            service.destroy()


if __name__ == "__main__":
    try:
        main()
    except urllib3.exceptions.MaxRetryError:
        LOGGER.exception("K8s not responding, service will shut down")
        sys.exit(_EXITCODE_NORESTART)
