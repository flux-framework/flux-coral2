"""Module defining cleanup routines for the coral2_dws service."""

import asyncio
import logging
import threading

import kubernetes as k8s
from kubernetes.client.rest import ApiException

from flux_k8s import crd

LOGGER = logging.getLogger(__name__)
FINALIZER = "flux-framework.readthedocs.io/workflow"
CLEANUP_LOOP = asyncio.get_event_loop()


def remove_finalizer(workflow_name, k8s_api, workflow):
    """Remove the finalizer from the workflow so it can be deleted."""
    try:
        workflow["metadata"]["finalizers"].remove(FINALIZER)
    except ValueError:
        # finalizer is not present, nothing to do
        pass
    else:
        k8s_api.patch_namespaced_custom_object(
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
        k8s_api = k8s.client.CustomObjectsApi(k8s_client)
    except ApiException as rest_exception:
        if rest_exception.status == 403:
            LOGGER.exception(
                "You must be logged in to the K8s or OpenShift cluster to continue"
            )
            raise
        LOGGER.exception("Cannot access kubernetes")
        raise
    return k8s_api


def log_error(fut):
    try:
        fut.result()
    except Exception as exc:
        LOGGER.exception("Exception in cleanup routine")


async def delete_workflow_coro(workflow):
    """Delete a workflow, retrying indefinitely (with backoff) upon error."""
    k8s_api = threading.current_thread().k8s_api
    attempts = 0
    name = workflow["metadata"]["name"]
    # attempt to delete the workflow in a loop
    while True:
        try:
            remove_finalizer(name, k8s_api, workflow)
            k8s_api.delete_namespaced_custom_object(*crd.WORKFLOW_CRD, name)
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
    asyncio.run_coroutine_threadsafe(
        delete_workflow_coro(workflow), CLEANUP_LOOP
    ).add_done_callback(log_error)


def cleanup_target(kubeconfig):
    """Run the asyncio event loop indefinitely."""
    curr_thread = threading.current_thread()
    curr_thread.k8s_api = get_k8s_api(kubeconfig)
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
