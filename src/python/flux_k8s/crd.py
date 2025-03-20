"""Module defining constants for fetching k8s resources."""

from collections import namedtuple

CRD = namedtuple("CRD", ["group", "version", "namespace", "plural"])

DWS_GROUP = "dataworkflowservices.github.io"
DWS_API_VERSION = "v1alpha3"
DEFAULT_NAMESPACE = "default"

NNF_GROUP = "nnf.cray.hpe.com"
NNF_API_VERSION = "v1alpha6"


WORKFLOW_CRD = CRD(
    group=DWS_GROUP,
    version=DWS_API_VERSION,
    namespace=DEFAULT_NAMESPACE,
    plural="workflows",
)

RABBIT_CRD = CRD(
    group=DWS_GROUP,
    version=DWS_API_VERSION,
    namespace=DEFAULT_NAMESPACE,
    plural="storages",
)

DIRECTIVEBREAKDOWN_CRD = CRD(
    group=DWS_GROUP,
    version=DWS_API_VERSION,
    namespace=DEFAULT_NAMESPACE,
    plural="directivebreakdowns",
)

COMPUTE_CRD = CRD(
    group=DWS_GROUP,
    version=DWS_API_VERSION,
    namespace=DEFAULT_NAMESPACE,
    plural="computes",
)

SERVER_CRD = CRD(
    group=DWS_GROUP,
    version=DWS_API_VERSION,
    namespace=DEFAULT_NAMESPACE,
    plural="servers",
)

SYSTEMCONFIGURATION_CRD = CRD(
    group=DWS_GROUP,
    version=DWS_API_VERSION,
    namespace=DEFAULT_NAMESPACE,
    plural="systemconfigurations",
)

DATAMOVEMENT_CRD = CRD(
    group=NNF_GROUP,
    version=NNF_API_VERSION,
    namespace=None,
    plural="nnfdatamovements",
)
