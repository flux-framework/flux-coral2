from collections import namedtuple

CRD = namedtuple('CRD', ['group', 'version', 'namespace', 'plural'])

WORKFLOW_CRD = CRD(
    group = "dws.cray.hpe.com",
    version = "v1alpha1",
    namespace = "default",
    plural = "workflows"
)
