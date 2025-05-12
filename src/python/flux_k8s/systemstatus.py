"""Module defining routines for handling k8s SystemStatus resources."""

import logging

from kubernetes.client.rest import ApiException

import flux
from flux.idset import IDset
from flux.hostlist import Hostlist
from flux_k8s import crd

LOGGER = logging.getLogger(__name__)


class SystemStatusManager:
    """Class for updating the k8s systemstatus resource.

    A node may be marked as Disabled in the systemstatus resource for one of two
    reasons: either the node has an offline broker, or the node failed to unmount
    in a timely manner and is drained while the mount is removed.

    Nodes are no longer marked as Disabled once the broker comes online, or once
    the node is undrained.
    """

    def __init__(self, handle, k8s_api):
        self.handle = handle
        self.k8s_api = k8s_api
        self._hlist = Hostlist(handle.attr_get("hostlist"))  # instance hostlist
        self._idset = IDset(f"0-{len(self._hlist) - 1}")  # instance IDset
        self._last_online = IDset("")  # nodes most recently listed as online

    def start(self):
        """Begin updating the systemstatus resource."""
        self.handle.rpc(
            "groups.get",
            {"name": "broker.online"},
            nodeid=0,
            flags=flux.constants.FLUX_RPC_STREAMING,
        ).then(self._rpc_callback)
        return self

    def _rpc_callback(self, rpc):
        """Wrap _update_offline in try/finally."""
        try:
            self._update_offline(rpc)
        except Exception:
            LOGGER.exception("Exception in systemstatus watch:")
        finally:
            rpc.reset()

    def _update_offline(self, rpc):
        """Update the set of known offline brokers."""
        online = IDset(rpc.get()["members"])
        newly_online = online - self._last_online
        offline = self._idset - online
        self._last_online = online
        self._patch_resource(self._hlist[newly_online], self._hlist[offline])

    def _patch_resource(self, newly_online=(), newly_offline=()):
        """Patch the systemstatus kubernetes object with the latest disabled nodes.

        A disabled node is one that either has an offline broker or a failed unmount.
        """
        nodes = {node_name: "Enabled" for node_name in newly_online}
        for node_name in newly_offline:
            nodes[node_name] = "Disabled"
        try:
            self.k8s_api.patch_namespaced_custom_object(
                *crd.SYSTEMSTATUS_CRD, "default", {"data": {"nodes": nodes}}
            )
        except ApiException as api_err:
            if api_err.status == 404:
                LOGGER.debug("could not find systemstatus resource")
            else:
                LOGGER.exception("Failed to patch systemstatus resource")
