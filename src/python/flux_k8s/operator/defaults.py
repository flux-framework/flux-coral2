# Defaults
# https://github.com/converged-computing/flux-slingshot/blob/main/minicluster.yaml

# This has flux built with cxi for slingshot
container = "ghcr.io/converged-computing/flux-slingshot:ubuntu2404"

# Flux Operator versions
group = "flux-framework.org"
version = "v1alpha2"
namespace = "default"
plural = "miniclusters"
api_version = f"{group}/{version}"

# Devices and volumes
device_path = "/sys/devices"
net_path = "/sys/class/net"

# CXI device plugin label for request
cxi_device_label = "beta.hpe.com/cxi"

# Persistent Volume and Persistent Volume Claim defaults
storage_capacity = "1Gi"
fs_type = "lustre"
csi_driver = "lustre-csi.hpe.com"
storage_class_name = "nnf-lustre-fs"
volume_reclaim_policy = "Retain"
rabbit_mount = "/mnt/nnf/rabbit"

# TODO ask James if we can put this in config somewhere
volume_handle = "51@kfi:32@kfi:/lslide"

# Default environment for network
environment = {}

# Default volumes for network
volumes = {
    "devices": {"hostPath": device_path, "path": device_path},
    "net": {"hostPath": net_path, "path": net_path},
}

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
