# Defaults
# https://github.com/converged-computing/flux-slingshot/blob/main/minicluster.yaml

# This has flux built with cxi for slingshot
container = "ghcr.io/converged-computing/flux-slingshot:ubuntu2404"

# Flux Operator versions
group = "flux-framework.org"
version = "v1alpha2"
namespace = "default"
plural = "miniclusters"

# Devices and volumes
device_path = "/sys/devices"
net_path = "/sys/class/net"

# Not sure there is any reason to change this
podspec = {
    "pod": {"nodeSelector": {"cray.nnf.node": "true"}},
    "tolerations": [
        {
            "effect": "NoSchedule",
            "key": "cray.nnf.node",
            "operator": "Equal",
            "value": "true",
        }
    ],
}
