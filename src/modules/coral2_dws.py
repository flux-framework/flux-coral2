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
import re

from kubernetes.client.rest import ApiException
import urllib3

import flux
from flux.hostlist import Hostlist
from flux.job.JobID import id_parse
from flux.constants import FLUX_MSGTYPE_REQUEST
from flux.future import Future
import flux_k8s
from flux_k8s import crd
from flux_k8s.watch import Watchers, Watch
from flux_k8s import directivebreakdown
from flux_k8s import cleanup
from flux_k8s import storage
from flux_k8s.workflow import (
    TransientConditionInfo,
    WorkflowInfo,
    save_workflow_to_kvs,
)


LOGGER = logging.getLogger(__name__)
WORKFLOWS_IN_TC = {}  # tc for TransientCondition
_MIN_ALLOCATION_SIZE = 4  # minimum rabbit allocation size
_EXITCODE_NORESTART = 3  # exit code indicating to systemd not to restart
CLIENTMOUNT_NAME = re.compile(r"-computes$")


class UserError(Exception):
    """Represents user errors."""


def log_rpc_response(rpc, jobid):
    """RPC callback for logging response."""
    jobid = flux.job.JobID(jobid).f58plain
    try:
        msg = rpc.get()
    except Exception as exc:
        LOGGER.warning("RPC error for job %s: %s", jobid, repr(exc))
    else:
        if msg:
            LOGGER.debug("RPC response for job %s was %s", jobid, msg)


def message_callback_wrapper(func):
    """Decorator for msg_watcher callbacks.

    Catch exceptions and return failure messages.
    """

    @functools.wraps(func)
    def wrapper(handle, arg, msg, k8s_api):
        try:
            func(handle, arg, msg, k8s_api)
        except UserError as exc:
            handle.respond(msg, {"success": False, "errstr": str(exc)})
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
                errstr = repr(exc)
            handle.log(syslog.LOG_ERR, f"{os.path.basename(__file__)}: {errstr}")
            handle.respond(msg, {"success": False, "errstr": errstr})
            LOGGER.exception("Error in responding to %s RPC for %s:", topic, jobid)
        else:
            handle.respond(msg, {"success": True})

    return wrapper


def save_elapsed_time_to_kvs(handle, jobid, workflow):
    """Save the elapsedTime field to a job's KVS, ignoring errors."""
    try:
        timing = workflow["status"]["elapsedTimeLastState"]
        state = workflow["status"]["state"].lower()
    except KeyError:
        return
    try:
        kvsdir = flux.job.job_kvs(handle, jobid)
        kvsdir[f"rabbit_{state}_timing"] = timing
        kvsdir.commit()
    except Exception:
        LOGGER.exception(
            "Failed to update KVS for job %s: workflow is %s", jobid, workflow
        )


def owner_uid(handle):
    """Get instance owner UID"""
    try:
        return int(handle.attr_get("security.owner"))
    except Exception:
        return os.getuid()


@message_callback_wrapper
def create_cb(handle, _t, msg, arg):
    """dws.create RPC callback. Creates a k8s Workflow object for a job.

    Triggered when a new job with a jobdw directive is submitted.
    """
    api_instance, restrict_persistent = arg
    dw_directives = msg.payload["dw_directives"]
    jobid = msg.payload["jobid"]
    userid = msg.payload["userid"]
    presets = handle.conf_get("rabbit.presets", {})
    if isinstance(dw_directives, str):
        # check if the string is one of the presets, and if so replace it
        if dw_directives.strip() in presets:
            dw_directives = [presets[dw_directives.strip()]]
        else:
            # the string may contain multiple #DW directives
            dw_directives = dw_directives.split("#DW ")
            # remove any blank entries that resulted and add back "#DW "
            dw_directives = ["#DW " + dw.strip() for dw in dw_directives if dw.strip()]
    if not isinstance(dw_directives, list):
        raise UserError(
            f"Malformed #DW directives, not list or string: {dw_directives!r}"
        )
    for i, directive in enumerate(dw_directives):
        if directive.strip() in presets:
            dw_directives[i] = presets[directive.strip()]
        if restrict_persistent and "create_persistent" in directive:
            if userid != owner_uid(handle):
                raise UserError(
                    "only the instance owner can create persistent file systems"
                )
    workflow_name = WorkflowInfo.get_name(jobid)
    spec = {
        "desiredState": "Proposal",
        "dwDirectives": dw_directives,
        "jobID": flux.job.JobID(jobid).f58plain,
        "userID": userid,
        "groupID": pwd.getpwuid(userid).pw_gid,
        "wlmID": "flux",
    }
    body = {
        "kind": "Workflow",
        "apiVersion": "/".join([crd.WORKFLOW_CRD.group, crd.WORKFLOW_CRD.version]),
        "spec": spec,
        "metadata": {
            "name": workflow_name,
            "namespace": crd.WORKFLOW_CRD.namespace,
            "finalizers": [cleanup.FINALIZER],
        },
    }
    try:
        api_instance.create_namespaced_custom_object(
            *crd.WORKFLOW_CRD,
            body,
        )
    except ApiException as api_err:
        if api_err.status == 403:
            # 403 Forbidden when the DW directive is invalid
            raise UserError(json.loads(api_err.body)["message"]) from api_err
        raise
    WorkflowInfo.add(jobid, workflow_name, msg.payload["resources"])
    # submit a memo providing the name of the workflow
    handle.rpc(
        "job-manager.memo",
        payload={"id": jobid, "memo": {"rabbit_workflow": workflow_name}},
    ).then(log_rpc_response, jobid)


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
    workflow_name = WorkflowInfo.get_name(jobid)
    workflow = k8s_api.get_namespaced_custom_object(*crd.WORKFLOW_CRD, workflow_name)
    compute_nodes = [{"name": hostname} for hostname in hlist]
    nodes_per_nnf = {}
    for hostname in hlist:
        nnf_name = storage.HOSTNAMES_TO_RABBITS[hostname]
        nodes_per_nnf[nnf_name] = nodes_per_nnf.get(nnf_name, 0) + 1
    handle.rpc(
        "job-manager.memo",
        payload={
            "id": jobid,
            "memo": {"rabbits": Hostlist(nodes_per_nnf.keys()).encode()},
        },
    ).then(log_rpc_response, jobid)
    k8s_api.patch_namespaced_custom_object(
        crd.COMPUTE_CRD.group,
        crd.COMPUTE_CRD.version,
        workflow["status"]["computes"]["namespace"],
        crd.COMPUTE_CRD.plural,
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
                crd.SERVER_CRD.group,
                crd.SERVER_CRD.version,
                breakdown["status"]["storage"]["reference"]["namespace"],
                crd.SERVER_CRD.plural,
                breakdown["status"]["storage"]["reference"]["name"],
                {"spec": {"allocationSets": allocation_sets}},
            )
    WorkflowInfo.get(jobid).move_desiredstate("Setup", k8s_api)


def check_existence_and_move_to_teardown(handle, k8s_api, winfo):
    """Check that a workflow exists and move it to Teardown if so."""
    jobid = winfo.jobid
    try:
        workflow = k8s_api.get_namespaced_custom_object(*crd.WORKFLOW_CRD, winfo.name)
    except ApiException as api_err:
        if api_err.status != 404:
            raise
        # workflow doesn't exist, presumably it was never created
        WorkflowInfo.remove(jobid)
        handle.rpc("job-manager.dws.epilog-remove", payload={"id": jobid}).then(
            log_rpc_response, jobid
        )
    else:
        # workflow does exist
        winfo.move_to_teardown(handle, k8s_api, workflow)


@message_callback_wrapper
def post_run_cb(handle, _t, msg, k8s_api):
    """dws.post_run RPC callback.

    The dws.post_run RPC is sent when the job has reached the CLEANUP state.

    If the job reached the RUN state, move the workflow to `post_run`.
    If the job did not reach the RUN state (exception path), move
    the workflow directly to `teardown`.
    """
    jobid = msg.payload["jobid"]
    winfo = WorkflowInfo.get(jobid)
    run_started = msg.payload["run_started"]
    if winfo.toredown:
        # workflow has already been transitioned to 'teardown', do nothing
        return
    if not run_started:
        # the job hit an exception before beginning to run; transition
        # the workflow immediately to 'teardown' if it exists.
        check_existence_and_move_to_teardown(handle, k8s_api, winfo)
    else:
        winfo.move_desiredstate("PostRun", k8s_api)


@message_callback_wrapper
def teardown_cb(handle, _t, msg, k8s_api):
    """dws.teardown RPC callback.

    The dws.teardown RPC is sent if a job hits an exception during the dws-epilog
    action.

    Move the workflow directly to Teardown.
    """
    jobid = msg.payload["jobid"]
    winfo = WorkflowInfo.get(jobid)
    if not winfo.toredown:
        check_existence_and_move_to_teardown(handle, k8s_api, winfo)


@message_callback_wrapper
def abort_cb(handle, _t, msg, k8s_api):
    """dws.abort RPC callback.

    The dws.abort RPC is sent if a job hits a special exception during the
    dws-epilog action.

    Move the workflow directly to Teardown, and look for nodes with active
    mounts and drain any that are found.
    """
    jobid = msg.payload["jobid"]
    winfo = WorkflowInfo.get(jobid)
    if not winfo.toredown:
        check_existence_and_move_to_teardown(handle, k8s_api, winfo)
    # get all clientmounts for the job that aren't unmounted
    to_drain = get_clientmounts_not_in_state(k8s_api, winfo.name, "unmounted")
    if to_drain:
        encoded_hostlist = Hostlist(to_drain).uniq().encode()
        LOGGER.debug(
            "Draining nodes %s with active mounts for workflow %s",
            encoded_hostlist,
            winfo.name,
        )
        handle.rpc(
            "resource.drain",
            payload={
                "targets": encoded_hostlist,
                "mode": "update",
                "reason": "failed to unmount rabbit",
            },
            nodeid=0,
        ).then(log_rpc_response)


def get_clientmounts_not_in_state(k8s_api, workflow_name, desired_state):
    """Return all nodes in a job with mounts that don't match a specified state.

    The job is specified by the name of the workflow.
    """
    try:
        clientmounts = k8s_api.list_cluster_custom_object(
            group=crd.CLIENTMOUNT_CRD.group,
            version=crd.CLIENTMOUNT_CRD.version,
            plural=crd.CLIENTMOUNT_CRD.plural,
            label_selector=(f"{crd.DWS_GROUP}/workflow.name={workflow_name}"),
        )["items"]
    except Exception as exc:
        LOGGER.warning(
            "Failed to fetch %s crds for workflow '%s': %s",
            crd.CLIENTMOUNT_CRD.plural,
            workflow_name,
            exc,
        )
        return []
    to_drain = []
    for resource in clientmounts:
        try:
            node = resource["spec"]["node"]
        except KeyError:
            # can't tell what node to drain, nothing to do
            LOGGER.warning(
                "%s resource found for workflow %s without '.spec.node': %s",
                crd.CLIENTMOUNT_CRD.plural,
                workflow_name,
                resource,
            )
            continue
        try:
            resource_name = resource["metadata"]["name"]
            mounts = resource["status"]["mounts"]
        except KeyError as exc:
            LOGGER.warning(
                "%s resource found for workflow %s without expected field: %s",
                crd.CLIENTMOUNT_CRD.plural,
                workflow_name,
                exc,
            )
            # assume node bad
            to_drain.append(node)
            continue
        if re.search(CLIENTMOUNT_NAME, resource_name) is None:
            # not a clientmount we care about because not a compute node, skip
            continue
        try:
            for mount in mounts:
                if mount["state"] != desired_state or not mount["ready"]:
                    to_drain.append(node)
                    break
        except (KeyError, TypeError) as exc:
            LOGGER.warning(
                "error inspecting mounts for %s resource found for workflow %s: %s",
                crd.CLIENTMOUNT_CRD.plural,
                workflow_name,
                exc,
            )
            # assume node bad
            to_drain.append(node)
    return to_drain


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
    except Exception:
        LOGGER.exception("Invalid event in workflow stream: %s", event)
        return
    if not WorkflowInfo.is_recognized(workflow_name):
        LOGGER.warning("unrecognized workflow '%s' in event stream", workflow_name)
        return
    winfo = WorkflowInfo.get(jobid)
    if event.get("TYPE") == "DELETED":
        # the workflow has been deleted, we can forget about it
        WorkflowInfo.remove(jobid)
        return
    try:
        _workflow_state_change_cb_inner(
            workflow, winfo, handle, k8s_api, disable_fluxion
        )
    except Exception:
        LOGGER.exception(
            "Failed to process event update for workflow '%s' with jobid %s:",
            workflow_name,
            jobid,
        )
        try:
            winfo.move_to_teardown(handle, k8s_api, workflow)
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


def _workflow_state_change_cb_inner(workflow, winfo, handle, k8s_api, disable_fluxion):
    """Handle workflow state transitions."""
    jobid = winfo.jobid
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
        cleanup.remove_finalizer(winfo.name, k8s_api, workflow)
    elif state_complete(workflow, "Teardown"):
        # Delete workflow object and tell DWS jobtap plugin that the job is done.
        # Attempt to remove the finalizer again in case the state transitioned
        # too quickly for it to be noticed earlier.
        handle.rpc("job-manager.dws.epilog-remove", payload={"id": jobid}).then(
            log_rpc_response, jobid
        )
        save_elapsed_time_to_kvs(handle, jobid, workflow)
        cleanup.delete_workflow(workflow)
        winfo.deleted = True
    elif winfo.toredown:
        # in the event of an exception, the workflow will skip to 'teardown'.
        # Without this early 'return', this function may try to
        # move a 'teardown' workflow to an earlier state because the
        # 'teardown' update is still in the k8s update queue.
        return
    elif state_complete(workflow, "Proposal"):
        resources = winfo.resources
        copy_offload = False
        if resources is None:
            resources = flux.job.kvslookup.job_kvs_lookup(handle, jobid)["jobspec"][
                "resources"
            ]
        try:
            if not disable_fluxion:
                resources, copy_offload = directivebreakdown.apply_breakdowns(
                    k8s_api, workflow, resources, _MIN_ALLOCATION_SIZE
                )
            else:
                _, copy_offload = directivebreakdown.apply_breakdowns(
                    k8s_api, workflow, resources, _MIN_ALLOCATION_SIZE
                )
        except ValueError as exc:
            errmsg = repr(exc.args[0])
        else:
            errmsg = None
        payload = {
            "id": jobid,
            "resources": resources,
            "copy-offload": copy_offload,
            "exclude": (
                storage.EXCLUDE_PROPERTY
                if disable_fluxion
                or not handle.conf_get("rabbit.drain_compute_nodes", True)
                else ""
            ),
        }
        if errmsg is not None:
            payload["errmsg"] = errmsg
        if resources is not None or copy_offload is not None:
            # both are None if the resource-update has already been applied
            handle.rpc(
                "job-manager.dws.resource-update",
                payload=payload,
            ).then(log_rpc_response, jobid)
            save_workflow_to_kvs(handle, jobid, workflow)
    elif state_complete(workflow, "Setup"):
        # move workflow to next stage, DataIn
        winfo.move_desiredstate("DataIn", k8s_api)
        save_elapsed_time_to_kvs(handle, jobid, workflow)
    elif state_complete(workflow, "DataIn"):
        # move workflow to next stage, PreRun
        winfo.move_desiredstate("PreRun", k8s_api)
        save_elapsed_time_to_kvs(handle, jobid, workflow)
    elif state_complete(workflow, "PreRun"):
        # tell DWS jobtap plugin that the job can start
        handle.rpc(
            "job-manager.dws.prolog-remove",
            payload={
                "id": jobid,
                "variables": workflow["status"].get("env", {}),
            },
        ).then(log_rpc_response, jobid)
        save_elapsed_time_to_kvs(handle, jobid, workflow)
    elif state_complete(workflow, "PostRun"):
        # move workflow to next stage, DataOut
        winfo.move_desiredstate("DataOut", k8s_api)
        save_elapsed_time_to_kvs(handle, jobid, workflow)
    elif state_complete(workflow, "DataOut"):
        # move workflow to next stage, teardown
        winfo.move_to_teardown(handle, k8s_api, workflow)
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
            winfo.move_to_teardown(handle, k8s_api, workflow)
    elif workflow["status"].get("status") == "TransientCondition":
        # a potentially fatal error has occurred, but may resolve itself
        message = workflow["status"].get("message", "")
        if winfo.jobid not in WORKFLOWS_IN_TC:
            WORKFLOWS_IN_TC[winfo.jobid] = TransientConditionInfo(time.time(), message)
        else:
            # grab the old time field and keep it, but replace the message
            new_tc = TransientConditionInfo(
                WORKFLOWS_IN_TC[winfo.jobid].last_time, message
            )
            WORKFLOWS_IN_TC[winfo.jobid] = new_tc
    else:
        if winfo.jobid in WORKFLOWS_IN_TC:
            del WORKFLOWS_IN_TC[winfo.jobid]


def kill_workflows_in_tc(_reactor, watcher, _r, tc_timeout):
    """Callback firing every (tc_timeout / 2) seconds.

    Raise exceptions on jobs stuck in TransientCondition for more than
    tc_timeout seconds.
    """
    curr_time = time.time()
    # iterate over a copy of the set
    # otherwise an exception occurs because we modify the set as we
    # iterate over it.
    for jobid, trans_cond in list(WORKFLOWS_IN_TC.items()):
        if curr_time - trans_cond.last_time > tc_timeout:
            watcher.flux_handle.job_raise(
                jobid,
                "exception",
                0,
                "DWS/Rabbit interactions failed: workflow in 'TransientCondition' "
                f"state too long: {trans_cond.last_message}",
            )
            del WORKFLOWS_IN_TC[jobid]


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
        "--min-allocation-size",
        "-m",
        default=_MIN_ALLOCATION_SIZE,
        metavar="N",
        help="Minimum allocation size of rabbit allocations, in bytes",
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
    parser.add_argument(
        "--retry-delay",
        metavar="N",
        default=10,
        type=float,
        help=(
            "Seconds to wait after a kubernetes call fails, doubling each time "
            "failures occur back-to-back"
        ),
    )
    return parser


def config_logging(args):
    """Configure logging for the script."""
    log_level = logging.WARNING
    if args.verbose > 0:
        log_level = logging.INFO
    if args.verbose > 1:
        log_level = logging.DEBUG
    logging.basicConfig(format="%(levelname)s - %(message)s")
    LOGGER.setLevel(log_level)
    # also set level on flux_k8s package
    logging.getLogger(flux_k8s.__name__).setLevel(log_level)


def register_services(handle, k8s_api, restrict_persistent):
    """register dws.create, dws.setup, and dws.post_run services."""
    serv_reg_fut = handle.service_register("dws")
    create_watcher = handle.msg_watcher_create(
        create_cb,
        FLUX_MSGTYPE_REQUEST,
        "dws.create",
        args=(k8s_api, restrict_persistent),
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
    teardown_watcher = handle.msg_watcher_create(
        teardown_cb, FLUX_MSGTYPE_REQUEST, "dws.teardown", args=k8s_api
    )
    teardown_watcher.start()
    abort_watcher = handle.msg_watcher_create(
        abort_cb, FLUX_MSGTYPE_REQUEST, "dws.abort", args=k8s_api
    )
    abort_watcher.start()
    serv_reg_fut.get()
    return (create_watcher, setup_watcher, post_run_watcher, abort_watcher)


def raise_self_exception(handle):
    """If this script is being run as a job, raise a low-severity job exception

    This job event is used to close the race condition between the python
    process starting and the `dws` service being registered, for
    testing purposes.
    Once https://github.com/flux-framework/flux-core/issues/3821 is
    implemented/closed, this can be replaced with that solution.
    """
    try:
        jobid = id_parse(os.environ["FLUX_JOB_ID"])
    except KeyError:
        return
    Future(handle.job_raise(jobid, "exception", 7, "dws watchers setup")).get()


def kubernetes_backoff(handle, orig_retry_delay):
    """Wrapper around reactor_run to back off if k8s is unresponsive."""
    retry_delay = orig_retry_delay
    last_error = 0
    while True:
        try:
            handle.reactor_run()
        except urllib3.exceptions.HTTPError as k8s_err:
            LOGGER.warning(
                "Hit an exception: '%s' while contacting kubernetes, sleeping for %s seconds",
                k8s_err,
                retry_delay,
            )
            now = time.time()
            if now - last_error < retry_delay + 5:
                # double the retry delay if we hit an error within
                # five seconds of trying again
                retry_delay = min(retry_delay * 2, 300)  # max out at 5 min
            else:
                retry_delay = orig_retry_delay
            last_error = now
            time.sleep(retry_delay)


def validate_config(config):
    """Validate the `rabbit` config table."""
    accepted_keys = {
        "save_datamovements",
        "kubeconfig",
        "tc_timeout",
        "drain_compute_nodes",
        "restrict_persistent_creation",
        "policy",
        "presets",
        "mapping",
        "soft_drain",
    }
    keys = set(config.keys())
    if not keys <= accepted_keys:
        LOGGER.warning(
            "misconfiguration: unrecognized `rabbit.%s` key in Flux config, "
            "accepted keys are %s",
            (keys - accepted_keys).pop(),
            accepted_keys,
        )
    if "policy" in config:
        if len(config["policy"]) != 1 or "maximums" not in config["policy"]:
            LOGGER.warning("`rabbit.policy` config table muxt have a `maximums` table")
        keys = set(config["policy"]["maximums"].keys())
        accepted_keys = set(directivebreakdown.ResourceLimits.TYPES)
        if not keys <= accepted_keys:
            LOGGER.warning(
                "misconfiguration: unrecognized `rabbit.policy.maximums.%s` key in "
                "Flux config, accepted keys are %s",
                (keys - accepted_keys).pop(),
                accepted_keys,
            )


def main():
    """Init script, begin processing of services."""
    args = setup_parsing().parse_args()
    _MIN_ALLOCATION_SIZE = args.min_allocation_size
    config_logging(args)
    # Remove FLUX_KVS_NAMESPACE from the environment if set, because otherwise
    # KVS lookups will look relative to that namespace, but this service
    # must operate on the default namespace.
    if "FLUX_KVS_NAMESPACE" in os.environ:
        del os.environ["FLUX_KVS_NAMESPACE"]
    handle = flux.Flux()
    validate_config(handle.conf_get("rabbit", {}))
    WorkflowInfo.save_datamovements = handle.conf_get("rabbit.save_datamovements", 0)
    # set the maximum allowable allocation sizes on the ResourceLimits class
    for fs_type in directivebreakdown.ResourceLimits.TYPES:
        setattr(
            directivebreakdown.ResourceLimits,
            fs_type,
            handle.conf_get(f"rabbit.policy.maximums.{fs_type}"),
        )
    try:
        k8s_api = cleanup.get_k8s_api(handle.conf_get("rabbit.kubeconfig"))
    except Exception:
        LOGGER.critical(
            "Service cannot run without access to kubernetes, shutting down"
        )
        sys.exit(_EXITCODE_NORESTART)
    cleanup.setup_cleanup_thread(handle.conf_get("rabbit.kubeconfig"))
    storage.populate_rabbits_dict(k8s_api)
    # create a timer watcher for killing workflows that have been stuck in
    # the "Error" state for too long
    tc_timeout = handle.conf_get("rabbit.tc_timeout", 10)
    handle.timer_watcher_create(
        tc_timeout / 2,
        kill_workflows_in_tc,
        repeat=tc_timeout / 2,
        args=tc_timeout,
    ).start()
    # start watching k8s workflow resources and operate on them when updates occur
    # or new RPCs are received
    with Watchers(handle, watch_interval=args.watch_interval) as watchers:
        storage.init_rabbits(
            k8s_api,
            handle,
            watchers,
            args.disable_fluxion,
            args.drain_queues,
        )
        services = register_services(
            handle, k8s_api, handle.conf_get("rabbit.restrict_persistent", True)
        )
        watchers.add_watch(
            Watch(
                k8s_api,
                crd.WORKFLOW_CRD,
                0,
                workflow_state_change_cb,
                handle,
                k8s_api,
                args.disable_fluxion,
            )
        )
        raise_self_exception(handle)
        kubernetes_backoff(handle, args.retry_delay)
        for service in services:
            service.stop()
            service.destroy()


if __name__ == "__main__":
    main()
