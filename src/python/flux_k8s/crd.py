"""Module defining constants for fetching k8s resources."""

import logging

from kubernetes.client.rest import ApiException


LOGGER = logging.getLogger(__name__)

DWS_GROUP = "dataworkflowservices.github.io"
DWS_API_VERSIONS = ["v1alpha7", "v1alpha6"]
DEFAULT_NAMESPACE = "default"

NNF_GROUP = "nnf.cray.hpe.com"
NNF_API_VERSIONS = ["v1alpha9", "v1alpha8"]


def determine_api_versions(handle, k8s_api):
    """Attempt to determine dynamically what the best API version is to use."""
    config_dws_version = handle.conf_get("rabbit.dws_api_version")
    if config_dws_version is not None:
        DWS_API_VERSIONS.insert(0, config_dws_version)
    config_nnf_version = handle.conf_get("rabbit.nnf_api_version")
    if config_nnf_version is not None:
        NNF_API_VERSIONS.insert(0, config_nnf_version)

    # determine API version for DWS
    for api_version in DWS_API_VERSIONS:
        success = True
        for resource in (RABBIT_CRD, SYSTEMSTATUS_CRD, SYSTEMCONFIGURATION_CRD):
            try:
                k8s_api.list_namespaced_custom_object(
                    group=resource.group,
                    version=api_version,
                    plural=resource.plural,
                    namespace=resource.namespace,
                    limit=2,
                )
            except ApiException as exc:
                LOGGER.warning(
                    "DWS API version %s failed for %s: %s",
                    api_version,
                    resource.plural,
                    exc,
                )
                success = False
                break
        if success:
            LOGGER.info("Using DWS API version %s", api_version)
            break
    else:
        raise RuntimeError(
            f"could not find suitable API version for {DWS_GROUP} "
            f"(out of {DWS_API_VERSIONS})"
        )
    for dws_crd in _DWS_CRDS:
        dws_crd.version = api_version

    # determine API version for NNF
    for api_version in NNF_API_VERSIONS:
        try:
            k8s_api.list_cluster_custom_object(
                group=DATAMOVEMENT_CRD.group,
                version=api_version,
                plural=DATAMOVEMENT_CRD.plural,
                limit=2,
            )
        except ApiException as exc:
            LOGGER.warning("NNF API version %s failed: %s", api_version, exc)
        else:
            LOGGER.info("Using NNF API version %s", api_version)
            break
    else:
        raise RuntimeError(
            f"could not find suitable API version for {NNF_GROUP} "
            f"(out of {NNF_API_VERSIONS})"
        )
    for nnf_crd in _NNF_CRDS:
        nnf_crd.version = api_version


class CRD:
    """Simple class for storing data, needs to be mutable so not `namedtuple`."""

    def __init__(self, group, version, namespace, plural):
        self.group = group
        self.version = version
        self.namespace = namespace
        self.plural = plural

    def __repr__(self):
        return (
            f"{type(self).__name__}({self.group}, {self.version}, "
            f"{self.namespace}, {self.plural})"
        )

    def __iter__(self):
        return iter((self.group, self.version, self.namespace, self.plural))


WORKFLOW_CRD = CRD(
    group=DWS_GROUP,
    version=DWS_API_VERSIONS[0],
    namespace=DEFAULT_NAMESPACE,
    plural="workflows",
)

RABBIT_CRD = CRD(
    group=DWS_GROUP,
    version=DWS_API_VERSIONS[0],
    namespace=DEFAULT_NAMESPACE,
    plural="storages",
)

DIRECTIVEBREAKDOWN_CRD = CRD(
    group=DWS_GROUP,
    version=DWS_API_VERSIONS[0],
    namespace=DEFAULT_NAMESPACE,
    plural="directivebreakdowns",
)

COMPUTE_CRD = CRD(
    group=DWS_GROUP,
    version=DWS_API_VERSIONS[0],
    namespace=DEFAULT_NAMESPACE,
    plural="computes",
)

SERVER_CRD = CRD(
    group=DWS_GROUP,
    version=DWS_API_VERSIONS[0],
    namespace=DEFAULT_NAMESPACE,
    plural="servers",
)

SYSTEMCONFIGURATION_CRD = CRD(
    group=DWS_GROUP,
    version=DWS_API_VERSIONS[0],
    namespace=DEFAULT_NAMESPACE,
    plural="systemconfigurations",
)

DATAMOVEMENT_CRD = CRD(
    group=NNF_GROUP,
    version=NNF_API_VERSIONS[0],
    namespace=None,
    plural="nnfdatamovements",
)

CLIENTMOUNT_CRD = CRD(
    group=DWS_GROUP,
    version=DWS_API_VERSIONS[0],
    namespace=None,
    plural="clientmounts",
)

SYSTEMSTATUS_CRD = CRD(
    group=DWS_GROUP,
    version=DWS_API_VERSIONS[0],
    namespace=DEFAULT_NAMESPACE,
    plural="systemstatuses",
)

_NNF_CRDS = (DATAMOVEMENT_CRD,)

_DWS_CRDS = (
    SYSTEMSTATUS_CRD,
    CLIENTMOUNT_CRD,
    SYSTEMCONFIGURATION_CRD,
    SERVER_CRD,
    COMPUTE_CRD,
    DIRECTIVEBREAKDOWN_CRD,
    RABBIT_CRD,
    WORKFLOW_CRD,
)
