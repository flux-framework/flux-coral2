"""Module defining cleanup routines for the coral2_dws service."""

import asyncio
import logging
import threading

import kubernetes as k8s
from kubernetes.client.rest import ApiException
from kubernetes.config.config_exception import ConfigException

from flux_k8s import crd
import flux_k8s.workflow
import flux
import flux.job

LOGGER = logging.getLogger(__name__)
FINALIZER = "flux-framework.readthedocs.io/workflow"
CLEANUP_LOOP = asyncio.get_event_loop()


def remove_finalizer(workflow_name, crd_api, workflow):
    """Remove the finalizer from the workflow so it can be deleted.

    If an outdated version of the workflow is being used, in particular
    a version of the workflow that has more finalizers than the current version,
    the call to remove the flux finalizer will fail with a 422 error code, because
    the server will interpret the patch as an attempt to *add* a finalizer.

    If an ApiException is received, fetch the workflow again and then make
    another attempt.
    """
    try:
        _remove_finalizer(workflow_name, crd_api, workflow)
    except ApiException:
        workflow = crd_api.get_namespaced_custom_object(
            *crd.WORKFLOW_CRD, workflow_name
        )
        _remove_finalizer(workflow_name, crd_api, workflow)


def _remove_finalizer(workflow_name, crd_api, workflow):
    """Remove the finalizer from the workflow so it can be deleted."""
    try:
        workflow["metadata"]["finalizers"].remove(FINALIZER)
    except ValueError:
        # finalizer is not present, nothing to do
        pass
    else:
        crd_api.patch_namespaced_custom_object(
            *crd.WORKFLOW_CRD,
            workflow_name,
            {"metadata": {"finalizers": workflow["metadata"]["finalizers"]}},
        )


def get_k8s_api(kubeconfig):
    """Return a handle to the k8s cluster's CustomObjectsApi."""
    try:
        k8s_client = k8s.config.new_client_from_config(kubeconfig)
    except ConfigException:
        LOGGER.exception("Kubernetes misconfigured")
        raise
    try:
        crd_api = k8s.client.CustomObjectsApi(k8s_client)
    except ApiException as rest_exception:
        if rest_exception.status == 403:
            LOGGER.exception(
                "You must be logged in to the K8s or OpenShift cluster to continue"
            )
            raise
        LOGGER.exception("Cannot access kubernetes")
        raise
    return crd_api


def log_error(fut):
    """Log an error if the future hit one."""
    try:
        fut.result()
    except Exception:
        LOGGER.exception("Exception in cleanup routine")


async def delete_workflow_coro(workflow):
    """Delete a workflow, retrying indefinitely (with backoff) upon error."""
    crd_api = threading.current_thread().crd_api
    attempts = 0
    name = workflow["metadata"]["name"]
    # attempt to delete the workflow in a loop
    while True:
        try:
            remove_finalizer(name, crd_api, workflow)
            crd_api.delete_namespaced_custom_object(*crd.WORKFLOW_CRD, name)
        except Exception as gen_exc:
            if isinstance(gen_exc, ApiException) and gen_exc.status == 404:
                # workflow was not found, presume it was deleted already
                return
            attempts += 1
            if attempts >= 5:
                LOGGER.warning(
                    "Failed to delete workflow %s after %i attempts. Error is %s",
                    name,
                    attempts,
                    gen_exc,
                )
            await asyncio.sleep(5 * 2 ** (attempts - 1))
        else:
            return


def delete_workflow(workflow):
    """Submit a deletion request to the cleanup loop."""
    asyncio.run_coroutine_threadsafe(
        delete_workflow_coro(workflow), CLEANUP_LOOP
    ).add_done_callback(log_error)


def save_pod_log(workflow_name, jobid, core_api, handle):
    """Save the logs for a pod associated with a workflow to the KVS.

    Not all jobs have a pod, only those with a `#DW container` directive.
    """
    api_response = core_api.list_namespaced_pod(
        "default",
        limit=1,
        label_selector=(
            f"{crd.DWS_GROUP}/workflow.name={workflow_name},"
            f"{crd.DWS_GROUP}/workflow.namespace=default"
        ),
    )
    if not api_response.items:
        return
    log = core_api.read_namespaced_pod_log(
        api_response.items[0].metadata.name, namespace="default"
    )
    with flux.job.job_kvs(handle, jobid) as kvsdir:
        kvsdir["rabbit_container_log"] = log[-50000:]


async def teardown_workflow_coro(workflow):
    """Teardown a workflow, retrying indefinitely (with backoff) upon error."""
    crd_api = threading.current_thread().crd_api
    attempts = 0
    name = workflow["metadata"]["name"]
    try:
        workflow["metadata"]["finalizers"].remove(FINALIZER)
    except ValueError:
        pass
    # attempt to teardown the workflow in a loop
    try:
        save_pod_log(
            name,
            flux.job.JobID(workflow["spec"]["jobID"]),
            threading.current_thread().core_api,
            threading.current_thread().flux_handle,
        )
    except Exception:
        LOGGER.warning("Failed to fetch pod logs for workflow %s", name)
    while True:
        try:
            crd_api.patch_namespaced_custom_object(
                *crd.WORKFLOW_CRD,
                name,
                {
                    "spec": {"desiredState": flux_k8s.workflow.WorkflowState.TEARDOWN},
                    "metadata": {"finalizers": workflow["metadata"]["finalizers"]},
                },
            )
        except Exception as gen_exc:
            if isinstance(gen_exc, ApiException) and gen_exc.status == 404:
                # workflow was not found, presume it was torn down already
                return
            attempts += 1
            if attempts >= 0:
                LOGGER.warning(
                    "Failed to teardown workflow %s after %i attempts. Error is %s",
                    name,
                    attempts,
                    gen_exc,
                )
            await asyncio.sleep(5 * 2 ** (attempts - 1))
        else:
            return


def teardown_workflow(workflow):
    """Submit a teardown request to the cleanup loop."""
    asyncio.run_coroutine_threadsafe(
        teardown_workflow_coro(workflow), CLEANUP_LOOP
    ).add_done_callback(log_error)


def cleanup_target(kubeconfig):
    """Run the asyncio event loop indefinitely."""
    curr_thread = threading.current_thread()
    curr_thread.k8s_client = k8s.config.new_client_from_config(kubeconfig)
    curr_thread.crd_api = get_k8s_api(kubeconfig)
    curr_thread.core_api = k8s.client.CoreV1Api(curr_thread.k8s_client)
    curr_thread.flux_handle = flux.Flux()
    try:
        CLEANUP_LOOP.run_forever()
    finally:
        CLEANUP_LOOP.close()


def setup_cleanup_thread(kubeconfig):
    """Start the thread that will run cleanup actions on workflows."""
    cleanup_thread = threading.Thread(
        target=cleanup_target,
        args=(kubeconfig,),
        name="workflow_cleanup_thread",
        daemon=True,
    )
    cleanup_thread.start()
