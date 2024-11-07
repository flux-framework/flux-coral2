"""Module defining cleanup routines for the coral2_dws service."""

import asyncio
import logging

import kubernetes as k8s
from kubernetes.client.rest import ApiException

from flux_k8s import crd

LOGGER = logging.getLogger(__name__)
FINALIZER = "flux-framework.readthedocs.io/workflow"


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
