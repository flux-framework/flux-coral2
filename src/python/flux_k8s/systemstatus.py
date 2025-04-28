"""Module defining routines for handling k8s SystemStatus resources."""

import logging

import flux
from flux.idset import IDset
from flux.hostlist import Hostlist
from flux_k8s import crd

LOGGER = logging.getLogger(__name__)


def _update_resource(rpc, hlist, k8s_api):
    """Update k8s `systemstatus` resource based on online brokers."""
    online = IDset(rpc.get()["members"])
    offline = IDset(f"0-{len(hlist) - 1}") - online
    disabled_dict = {node_name: "Disabled" for node_name in hlist[offline]}
    k8s_api.patch_namespaced_custom_object(
        *crd.SYSTEMSTATUS_CRD, "default", {"data": {"nodes": disabled_dict}}
    )


def _rpc_callback(rpc, hlist, k8s_api):
    """Wrap _update_resource in try/finally."""
    try:
        _update_resource(rpc, hlist, k8s_api)
    except Exception:
        LOGGER.exception("Exception in systemstatus watch:")
        raise
    finally:
        rpc.reset()


def start_watch(k8s_api, handle):
    """Start watching for node status updates on `handle` and update k8s."""
    hlist = Hostlist(handle.attr_get("hostlist"))
    handle.rpc(
        "groups.get",
        {"name": "broker.online"},
        nodeid=0,
        flags=flux.constants.FLUX_RPC_STREAMING,
    ).then(_rpc_callback, hlist, k8s_api)
