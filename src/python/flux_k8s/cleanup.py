"""Module defining cleanup routines for the coral2_dws service."""

from flux_k8s import crd

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
