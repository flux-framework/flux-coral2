from collections import namedtuple

CRD = namedtuple('CRD', ['group', 'version', 'namespace', 'plural'])

WORKFLOW_CRD = CRD(
    group = "dws.cray.hpe.com",
    version = "v1alpha1",
    namespace = "default",
    plural = "workflows"
)

RABBIT_CRD = CRD(
    group = "rabbit.hpe.com",
    version = "v1alpha",
    namespace = "default",
    plural = "nearnodeflashes",
)

DIRECTIVEBREAKDOWN_CRD = CRD(
    group = "dws.cray.hpe.com",
    version = "v1alpha1",
    namespace = "default",
    plural = "directivebreakdowns",
)

COMPUTE_CRD = CRD(
    group = "dws.cray.hpe.com",
    version = "v1alpha1",
    namespace = "default",
    plural = "computes",
)
