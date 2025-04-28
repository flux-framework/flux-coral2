"""Module defining cleanup routines for the coral2_dws service."""

import logging

import flux
import flux.kvs
from flux.hostlist import Hostlist
from flux.idset import IDset
from flux_k8s import watch
from flux_k8s import crd

LOGGER = logging.getLogger(__name__)
EXCLUDE_PROPERTY = "badrabbit"
HOSTNAMES_TO_RABBITS = {}  # maps compute hostnames to rabbit names
_RABBITS_TO_HOSTLISTS = {}  # maps rabbits to hostlists
_READY_STATUS = "Ready"


def _get_status(rabbit, default):
    """Get a rabbit's status or return `default` if not found."""
    try:
        return rabbit["status"]["status"]
    except KeyError:
        return default


def _get_offline_nodes(rabbit):
    """Return the set of all nodes marked as Offline by a rabbit."""
    offline_nodes = set()
    try:
        # rabbits don't have a 'status' field until they boot, in which case
        # there is nothing to do
        nodelist = rabbit["status"]["access"]["computes"]
    except KeyError:
        return offline_nodes
    for compute_node in nodelist:
        if compute_node["status"] != _READY_STATUS:
            offline_nodes.add(compute_node["name"])
    return offline_nodes


class RabbitManager:
    """Class for interfacing with k8s Storage resources.

    Offers methods for setting the `badrabbit` property on compute nodes, and for
    handling updates to Storage resources.
    """

    def __init__(self, handle, allowlist):
        if not HOSTNAMES_TO_RABBITS or not _RABBITS_TO_HOSTLISTS:
            raise RuntimeError("populate_rabbits_dict must be called first")
        self.handle = handle  # flux.Flux() handle to use
        self.allowlist = allowlist  # `set` of nodes to allow draining for, or None
        self._compute_rpaths = {}  # mapping from hostnames to fluxion paths
        self._get_rpaths()

    def _get_rpaths(self):
        """Map compute nodes to Fluxion resource paths."""
        instance_nodes = Hostlist(self.handle.attr_get("hostlist"))
        self._compute_rpaths = {
            hostname: f"/cluster0/{hostname}"
            for hostname in HOSTNAMES_TO_RABBITS
            if hostname in instance_nodes
        }
        # Do not attempt to send RPCs to Fluxion about any nodes in `resource.exclude`
        # because Fluxion will raise an error, since it doesn't know the nodes exist.
        exclude_str = self.handle.conf_get("resource.exclude")
        exclude = ()
        if not exclude_str:
            return
        try:
            idset = IDset(exclude_str)
        except Exception:
            try:
                exclude = Hostlist(exclude_str)
            except Exception:
                LOGGER.warning(
                    "`resource.exclude` (%s) is neither IDset nor hostlist", exclude_str
                )
                return
        else:
            exclude = instance_nodes[idset]
        for host in exclude:
            self._compute_rpaths.pop(host, None)

    def rabbit_state_change_cb(self, event):
        """Callback firing when a Storage object changes.

        Marks a rabbit as up or down.
        """
        rabbit = event["object"]
        if self.handle.conf_get("rabbit.drain_compute_nodes", True):
            # only drain compute nodes if allowed, admins may find it obnoxious
            self._drain_offline_nodes(rabbit)
        self._set_or_remove_property(rabbit)

    def _drain_offline_nodes(self, rabbit):
        """Drain nodes listed as offline in a given Storage resource.

        Drain all the nodes in the rabbit that are Offline, provided they are
        in `allowlist`.

        If draining is disabled in the rabbit config table, do nothing.
        """
        offline_nodes = _get_offline_nodes(rabbit)
        if isinstance(self.allowlist, set):
            offline_nodes &= self.allowlist
        if offline_nodes:
            encoded_hostlist = Hostlist(offline_nodes).encode()
            LOGGER.debug("Draining nodes %s", encoded_hostlist)
            self.handle.rpc(
                "resource.drain",
                payload={
                    "targets": encoded_hostlist,
                    "mode": "update",
                    "reason": "rabbit lost PCIe connection",
                },
                nodeid=0,
            ).then(log_rpc_response)

    def _set_or_remove_property(self, rabbit):
        """Set or remove properties on compute nodes so rabbit jobs can avoid them.

        This provides a mechanism for handling both down rabbits AND
        down rabbit-to-compute-node links. If the rabbit as a whole is down,
        all nodes should be marked with the property. If individual PCIe
        links are down, just the affected nodes should be marked.
        """
        name = rabbit["metadata"]["name"]
        all_nodes = set(_RABBITS_TO_HOSTLISTS[name])
        down_nodes = set()
        status = _get_status(rabbit, "Disabled")
        if status != _READY_STATUS:
            # all nodes should be marked with the property
            down_nodes = all_nodes
        elif not self.handle.conf_get(
            "rabbit.drain_compute_nodes", True
        ) and self.handle.conf_get("rabbit.soft_drain", True):
            # rabbit is up, draining disabled, individual nodes may be marked with property
            down_nodes = _get_offline_nodes(rabbit)
        up_nodes = all_nodes - down_nodes
        self.remove_property(up_nodes, f"marked as up by Storage {name}")
        self.set_property(down_nodes, f"marked as down by Storage {name}")

    def remove_property(self, up_nodes, reason=None):
        """Send RPCs to remove property from all `up_nodes`."""
        if up_nodes:
            LOGGER.debug(
                "Removing property %s from nodes %s%s",
                EXCLUDE_PROPERTY,
                Hostlist(up_nodes).uniq().encode(),
                f": {reason}" if reason is not None else "",
            )
        for hostname in up_nodes:
            if hostname in self._compute_rpaths:
                payload = {
                    "resource_path": self._compute_rpaths[hostname],
                    "key": EXCLUDE_PROPERTY,
                }
                self.handle.rpc("sched-fluxion-resource.remove_property", payload).then(
                    log_rpc_response
                )

    def set_property(self, down_nodes, reason=None):
        """Send RPCs to set property on all `down_nodes`."""
        if down_nodes:
            LOGGER.debug(
                "Adding property %s to nodes %s%s",
                EXCLUDE_PROPERTY,
                Hostlist(down_nodes).uniq().encode(),
                f": {reason}" if reason is not None else "",
            )
        for hostname in down_nodes:
            if hostname in self._compute_rpaths:
                self.handle.rpc(
                    "sched-fluxion-resource.set_property",
                    {
                        "sp_resource_path": self._compute_rpaths[hostname],
                        "sp_keyval": f"{EXCLUDE_PROPERTY}=bad",
                    },
                ).then(log_rpc_response)


class FluxionRabbitManager(RabbitManager):
    """Class for interfacing with k8s Storage resources.

    Assumes Fluxion has been augmented to use a resource graph with `rack` and
    `ssd` vertices as produced by `flux dws2jgf`.

    Offers methods for setting the `badrabbit` property on compute nodes, and for
    handling updates to Storage resources.
    """

    def __init__(self, handle, allowlist):
        self._rabbit_rpaths = {}  # maps rabbit hostnames to Fluxion rack paths
        super().__init__(handle, allowlist)

    def _get_rpaths(self):
        """Read the fluxion resource graph and map rabbit hostnames to resource paths."""
        try:
            nodes = flux.kvs.get(self.handle, "resource.R")["scheduling"]["graph"][
                "nodes"
            ]
        except Exception as exc:
            raise ValueError(
                "Could not load rabbit resource graph data from KVS's resource.R"
            ) from exc
        for vertex in nodes:
            metadata = vertex["metadata"]
            if metadata["type"] == "rack" and "rabbit" in metadata["properties"]:
                self._rabbit_rpaths[metadata["properties"]["rabbit"]] = (
                    metadata["paths"]["containment"],
                    int(metadata["properties"].get("ssdcount", 36)),
                )
            if metadata["type"] == "node":
                self._compute_rpaths[metadata["name"]] = metadata["paths"][
                    "containment"
                ]

    def rabbit_state_change_cb(self, event):
        """Callback firing when a Storage object changes.

        Runs superclass's method and also marks a rabbit as up or down.
        """
        super().rabbit_state_change_cb(event)
        rabbit = event["object"]
        name = rabbit["metadata"]["name"]
        if name not in self._rabbit_rpaths:
            LOGGER.error(
                "Encountered an unknown Storage object '%s' in the event stream", name
            )
            return
        status = _get_status(rabbit, "Down")
        self._mark_rabbit(status, name)
        # TODO: add some check for whether rabbit capacity has changed
        # TODO: update capacity of rabbit in resource graph (mark some slices down?)

    def _mark_rabbit(self, status, name):
        """Send RPCs to mark ssd vertices as up or down."""
        resource_path, ssdcount = self._rabbit_rpaths[name]
        if status == _READY_STATUS:
            LOGGER.debug("Marking rabbit %s as up", name)
            status = "up"
        else:
            LOGGER.debug("Marking rabbit %s as down, status is %s", name, status)
            status = "down"
        for ssdnum in range(ssdcount):
            payload = {
                "resource_path": resource_path + f"/ssd{ssdnum}",
                "status": status,
            }
            self.handle.rpc("sched-fluxion-resource.set_status", payload).then(
                log_rpc_response
            )

    def _set_or_remove_property(self, rabbit):
        """Set properties on compute nodes so that rabbit jobs can avoid them.

        Overrides superclass's method of the same name.

        If the rabbit as a whole is down, there should be no need to set properties
        because all SSD vertices will have been marked down. If however individual PCIe
        links are down but the rabbit is up, the affected nodes should be marked.
        """
        name = rabbit["metadata"]["name"]
        all_nodes = set(_RABBITS_TO_HOSTLISTS[name])
        down_nodes = set()
        status = _get_status(rabbit, "Disabled")
        if (
            status == _READY_STATUS
            and not self.handle.conf_get("rabbit.drain_compute_nodes", True)
            and self.handle.conf_get("rabbit.soft_drain", True)
        ):
            # rabbit is up, draining disabled, individual nodes may be marked with prop
            down_nodes = _get_offline_nodes(rabbit)
        up_nodes = all_nodes - down_nodes
        self.remove_property(up_nodes, f"marked as up by Storage {name}")
        self.set_property(down_nodes, f"marked as down by Storage {name}")


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

    Return a `RabbitManager` instance for managing the rabbits, after adding
    a watch on Storage resources.

    To initialize, check the status of all rabbits and mark each one as up or
    down, because status may have changed while this service was inactive.
    """
    api_response = k8s_api.list_namespaced_custom_object(*crd.RABBIT_CRD)
    if drain_queues is not None:
        rset = flux.resource.resource_list(handle).get().all
        allowlist = set(rset.copy_constraint({"properties": drain_queues}).nodelist)
        if not allowlist:
            raise ValueError(
                f"No resources found associated with queues {drain_queues}"
            )
    else:
        allowlist = None
    if disable_fluxion:
        manager = RabbitManager(handle, allowlist)
    else:
        manager = FluxionRabbitManager(handle, allowlist)
    resource_version = 0
    for rabbit in api_response["items"]:
        resource_version = rabbit["metadata"]["resourceVersion"]
        manager.rabbit_state_change_cb(
            {"object": rabbit},
        )
    watchers.add_watch(
        watch.Watch(
            k8s_api, crd.RABBIT_CRD, resource_version, manager.rabbit_state_change_cb
        )
    )
    return manager
