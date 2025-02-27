"""Module defining cleanup routines for the coral2_dws service."""

import logging

import flux
import flux.kvs
from flux.hostlist import Hostlist
from flux_k8s import watch
from flux_k8s import crd

LOGGER = logging.getLogger(__name__)
EXCLUDE_PROPERTY = "badrabbit"
HOSTNAMES_TO_RABBITS = {}  # maps compute hostnames to rabbit names
_RABBITS_TO_HOSTLISTS = {}  # maps rabbits to hostlists


def log_rpc_response(rpc):
    """RPC callback for logging response."""
    try:
        msg = rpc.get()
    except Exception as exc:
        LOGGER.warning("RPC error %s", repr(exc))
    else:
        if msg:
            LOGGER.debug("RPC response was %s", msg)


def populate_rabbits_dict(k8s_api):
    """Populate the HOSTNAMES_TO_RABBITS dictionary."""
    systemconf = k8s_api.get_namespaced_custom_object(
        *crd.SYSTEMCONFIGURATION_CRD, "default"
    )
    for nnf in systemconf["spec"]["storageNodes"]:
        hlist = Hostlist()
        try:
            rabbit_computes = nnf["computesAccess"]
        except KeyError:
            rabbit_computes = []
        for compute in rabbit_computes:
            hostname = compute["name"]
            hlist.append(hostname)
            if hostname in HOSTNAMES_TO_RABBITS:
                raise KeyError(
                    f"Same hostname ({hostname}) cannot be associated with "
                    f"both {nnf['name']} and "
                    f"{HOSTNAMES_TO_RABBITS[hostname]}"
                )
            HOSTNAMES_TO_RABBITS[hostname] = nnf["name"]
        _RABBITS_TO_HOSTLISTS[nnf["name"]] = hlist.uniq()


def init_rabbits(k8s_api, handle, watchers, disable_fluxion, drain_queues):
    """Watch every rabbit ('Storage' resources in k8s) known to k8s.

    Whenever a Storage resource changes, mark it as 'up' or 'down' in Fluxion.

    Also, to initialize, check the status of all rabbits and mark each one as up or
    down, because status may have changed while this service was inactive.
    """
    api_response = k8s_api.list_namespaced_custom_object(*crd.RABBIT_CRD)
    if not disable_fluxion:
        rabbit_rpaths, compute_rpaths = _map_rabbits_to_fluxion_paths(handle)
    else:
        rabbit_rpaths = {}
        compute_rpaths = {
            hostname: f"/cluster0/{hostname}" for hostname in HOSTNAMES_TO_RABBITS
        }
    if drain_queues is not None:
        rset = flux.resource.resource_list(handle).get().all
        allowlist = set(rset.copy_constraint({"properties": drain_queues}).nodelist)
        if not allowlist:
            raise ValueError(
                f"No resources found associated with queues {drain_queues}"
            )
    else:
        allowlist = None
    resource_version = 0
    for rabbit in api_response["items"]:
        name = rabbit["metadata"]["name"]
        resource_version = rabbit["metadata"]["resourceVersion"]
        if disable_fluxion:
            # don't mark the rabbit up or down but add the rabbit to the mapping
            rabbit_rpaths[name] = (None, None)
        _rabbit_state_change_cb(
            {"object": rabbit},
            handle,
            rabbit_rpaths,
            disable_fluxion,
            allowlist,
            compute_rpaths,
        )
    watchers.add_watch(
        watch.Watch(
            k8s_api,
            crd.RABBIT_CRD,
            resource_version,
            _rabbit_state_change_cb,
            handle,
            rabbit_rpaths,
            disable_fluxion,
            allowlist,
            compute_rpaths,
        )
    )


def _set_property_on_compute_nodes(handle, rabbit, disable_fluxion, compute_rpaths):
    """Set properties on compute nodes so that rabbit jobs can avoid them

    This provides a mechanism for handling both down rabbits AND
    down rabbit-to-compute-node links. If the rabbit as a whole is down,
    all nodes should be marked with the property. If individual PCIe
    links are down, just the affected nodes should be marked.
    """
    name = rabbit["metadata"]["name"]
    all_nodes = set(_RABBITS_TO_HOSTLISTS[name])
    down_nodes = set()
    try:
        status = rabbit["status"]["status"]
    except KeyError:
        # if rabbit doesn't have a status, consider it down
        status = "Disabled"
    if status != "Ready" and disable_fluxion:
        # all nodes should be marked with the property, we can end here
        down_nodes = all_nodes
    elif (
        status == "Ready"
        and not handle.conf_get("rabbit.drain_compute_nodes", True)
        and handle.conf_get("rabbit.soft_drain", True)
    ):
        # rabbit is up, draining disabled, individual nodes may be marked with property
        try:
            nodelist = rabbit["status"]["access"]["computes"]
        except KeyError:
            nodelist = []
        for compute_node in nodelist:
            if compute_node["status"] != "Ready":
                down_nodes.add(compute_node["name"])
    up_nodes = all_nodes - down_nodes
    if up_nodes:
        LOGGER.debug(
            "Removing property %s from nodes %s attached to rabbit %s",
            EXCLUDE_PROPERTY,
            Hostlist(up_nodes).uniq(),
            name,
        )
    for hostname in up_nodes:
        if hostname in compute_rpaths:
            payload = {
                "resource_path": compute_rpaths[hostname],
                "key": EXCLUDE_PROPERTY,
            }
            handle.rpc("sched-fluxion-resource.remove_property", payload).then(
                log_rpc_response
            )
    if down_nodes:
        LOGGER.debug(
            "Adding property %s to nodes %s attached to rabbit %s",
            EXCLUDE_PROPERTY,
            Hostlist(down_nodes).uniq(),
            name,
        )
    for hostname in down_nodes:
        if hostname in compute_rpaths:
            handle.rpc(
                "sched-fluxion-resource.set_property",
                {
                    "sp_resource_path": compute_rpaths[hostname],
                    "sp_keyval": f"{EXCLUDE_PROPERTY}=bad",
                },
            ).then(log_rpc_response)


def _drain_offline_nodes(handle, rabbit, allowlist):
    """Drain nodes listed as offline in a given Storage resource.

    Drain all the nodes in `nodelist` that are Offline, provided they are
    in `allowlist`.

    If draining is disabled in the rabbit config table, do nothing.
    """
    # rabbits don't have a 'status' field until they boot, in which case
    # there is nothing to do
    try:
        nodelist = rabbit["status"]["access"]["computes"]
    except KeyError:
        return
    offline_nodes = Hostlist()
    for compute_node in nodelist:
        if compute_node["status"] != "Ready":
            if allowlist is None or compute_node["name"] in allowlist:
                offline_nodes.append(compute_node["name"])
    if offline_nodes:
        encoded_hostlist = offline_nodes.encode()
        LOGGER.debug("Draining nodes %s", encoded_hostlist)
        handle.rpc(
            "resource.drain",
            payload={
                "targets": encoded_hostlist,
                "mode": "update",
                "reason": "rabbit lost PCIe connection",
            },
            nodeid=0,
        ).then(log_rpc_response)


def _mark_rabbit(handle, status, resource_path, ssdcount, name):
    """Send RPCs to mark a rabbit as up or down in Fluxion."""
    if status == "Ready":
        LOGGER.debug("Marking rabbit %s as up", name)
        status = "up"
    else:
        LOGGER.debug("Marking rabbit %s as down, status is %s", name, status)
        status = "down"
    for ssdnum in range(ssdcount):
        payload = {"resource_path": resource_path + f"/ssd{ssdnum}", "status": status}
        handle.rpc("sched-fluxion-resource.set_status", payload).then(log_rpc_response)


def _rabbit_state_change_cb(
    event, handle, rabbit_rpaths, disable_fluxion, allowlist, compute_rpaths
):
    """Callback firing when a Storage object changes.

    Marks a rabbit as up or down.
    """
    rabbit = event["object"]
    name = rabbit["metadata"]["name"]
    if name not in rabbit_rpaths:
        LOGGER.error(
            "Encountered an unknown Storage object '%s' in the event stream", name
        )
        return
    if not disable_fluxion:
        try:
            status = rabbit["status"]["status"]
        except KeyError:
            # if rabbit doesn't have a status, consider it down
            _mark_rabbit(handle, "Down", *rabbit_rpaths[name], name)
        else:
            _mark_rabbit(handle, status, *rabbit_rpaths[name], name)
    if handle.conf_get("rabbit.drain_compute_nodes", True):
        _drain_offline_nodes(handle, rabbit, allowlist)
    _set_property_on_compute_nodes(handle, rabbit, disable_fluxion, compute_rpaths)
    # TODO: add some check for whether rabbit capacity has changed
    # TODO: update capacity of rabbit in resource graph (mark some slices down?)


def _map_rabbits_to_fluxion_paths(handle):
    """Read the fluxion resource graph and map rabbit hostnames to resource paths."""
    rabbit_rpaths = {}
    compute_rpaths = {}
    try:
        nodes = flux.kvs.get(handle, "resource.R")["scheduling"]["graph"]["nodes"]
    except Exception as exc:
        raise ValueError(
            "Could not load rabbit resource graph data from KVS's resource.R"
        ) from exc
    for vertex in nodes:
        metadata = vertex["metadata"]
        if metadata["type"] == "rack" and "rabbit" in metadata["properties"]:
            rabbit_rpaths[metadata["properties"]["rabbit"]] = (
                metadata["paths"]["containment"],
                int(metadata["properties"].get("ssdcount", 36)),
            )
        if metadata["type"] == "node":
            compute_rpaths[metadata["name"]] = metadata["paths"]["containment"]
    return rabbit_rpaths, compute_rpaths
