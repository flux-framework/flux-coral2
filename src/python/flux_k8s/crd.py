from collections import namedtuple

CRD = namedtuple("CRD", ["group", "version", "namespace", "plural"])

WORKFLOW_CRD = CRD(
    group="dataworkflowservices.github.io",
    version="v1alpha2",
    namespace="default",
    plural="workflows",
)

RABBIT_CRD = CRD(
    group="dataworkflowservices.github.io",
    version="v1alpha2",
    namespace="default",
    plural="storages",
)

DIRECTIVEBREAKDOWN_CRD = CRD(
    group="dataworkflowservices.github.io",
    version="v1alpha2",
    namespace="default",
    plural="directivebreakdowns",
)

COMPUTE_CRD = CRD(
    group="dataworkflowservices.github.io",
    version="v1alpha2",
    namespace="default",
    plural="computes",
)

SERVER_CRD = CRD(
    group="dataworkflowservices.github.io",
    version="v1alpha2",
    namespace="default",
    plural="servers",
)
