"""Module defining functions related to DirectiveBreakdown resources."""

import enum
import copy
import functools
import math
import collections

from flux_k8s.crd import DIRECTIVEBREAKDOWN_CRD


class AllocationStrategy(enum.Enum):
    """Enum defining different AllocationStrategies."""

    PER_COMPUTE = "AllocatePerCompute"
    SINGLE_SERVER = "AllocateSingleServer"
    ACROSS_SERVERS = "AllocateAcrossServers"


PER_COMPUTE_TYPES = ("xfs", "gfs2", "raw")
LUSTRE_TYPES = ("ost", "mdt", "mgt", "mgtmdt")


class ResourceLimits:
    """Class for handling resource limits.

    Store limits as class attributes.
    """

    TYPES = PER_COMPUTE_TYPES + ("lustre",)
    xfs = None
    gfs2 = None
    lustre = None
    raw = None

    def __init__(self):
        """Store requested amounts as instance attributes."""
        self.xfs = 0
        self.gfs2 = 0
        self.lustre = 0
        self.raw = 0

    def validate(self, nodecount):
        """Raise a ValueError if the capacity requested per node is above the limit."""
        for attr in self.TYPES:
            requested = getattr(self, attr)
            allowable = getattr(type(self), attr)
            if attr == "lustre":
                requested = requested // nodecount
            if allowable is not None and requested > allowable:
                raise ValueError(
                    f"Requested a total of {requested} GiB of {attr} storage "
                    f"per node but max is {allowable} GiB per node"
                )

    def increment(self, attr, capacity):
        """Increase the requested amount of 'attr' storage by 'capacity'."""
        if attr in LUSTRE_TYPES:
            # ignore everything except OSTs, should be small anyway
            if attr == "ost":
                self.lustre += capacity
        elif attr in PER_COMPUTE_TYPES:
            setattr(self, attr, getattr(self, attr) + capacity)
        else:
            raise AttributeError(attr)


def build_allocation_sets(breakdown_alloc_sets, nodes_per_nnf, hlist, min_alloc_size):
    """Build the allocationSet for a Server based on its DirectiveBreakdown."""
    allocation_sets = []
    for alloc_set in breakdown_alloc_sets:
        storage_field = []
        strategy = alloc_set["allocationStrategy"]
        server_alloc_set = {
            "allocationSize": alloc_set["minimumCapacity"],
            "label": alloc_set["label"],
            "storage": storage_field,
        }
        if strategy == AllocationStrategy.PER_COMPUTE.value:
            # make an allocation on every rabbit attached to compute nodes
            # in the job
            for nnf_name, nodecount in nodes_per_nnf.items():
                storage_field.append(
                    {
                        "allocationCount": nodecount,
                        "name": nnf_name,
                    }
                )
        else:
            # handle SINGLE_SERVER the same as ACROSS_SERVERS with a count constraint of 1
            if (
                "count" in alloc_set.get("constraints", {})
                or strategy == AllocationStrategy.SINGLE_SERVER.value
            ):
                # a specific number of allocations is required (generally for MDTs)
                if strategy == AllocationStrategy.SINGLE_SERVER.value:
                    count = 1
                else:
                    count = alloc_set["constraints"]["count"]
                server_alloc_set["allocationSize"] = math.ceil(
                    alloc_set["minimumCapacity"] / count
                )
                # place the allocations on the rabbits with the most nodes allocated
                # to this job (and therefore the largest storage allocations)
                while count > 0:
                    # count may be greater than the rabbits available, so we may need
                    # to place multiple on a single rabbit (hence the outer while-loop)
                    for name, _ in collections.Counter(nodes_per_nnf).most_common(
                        count
                    ):
                        storage_field.append(
                            {
                                "allocationCount": 1,
                                "name": name,
                            }
                        )
                        count -= 1
                        if count == 0:
                            break
            else:
                nodecount_gcd = functools.reduce(math.gcd, nodes_per_nnf.values())
                server_alloc_set["allocationSize"] = math.ceil(
                    nodecount_gcd * alloc_set["minimumCapacity"] / len(hlist)
                )
                # split lustre across every rabbit, weighting the split based on
                # the number of the job's nodes associated with each rabbit
                for rabbit_name in nodes_per_nnf:
                    storage_field.append(
                        {
                            "allocationCount": int(
                                nodes_per_nnf[rabbit_name] / nodecount_gcd
                            ),
                            "name": rabbit_name,
                        }
                    )
        # enforce the minimum allocation size
        server_alloc_set["allocationSize"] = max(
            server_alloc_set["allocationSize"], min_alloc_size * 1024**3
        )
        allocation_sets.append(server_alloc_set)
    return allocation_sets


def apply_breakdowns(k8s_api, workflow, old_resources, min_size):
    """Apply all of the directive breakdown information to a jobspec's `resources`."""
    limits = ResourceLimits()
    resources = copy.deepcopy(old_resources)
    breakdown_list = list(fetch_breakdowns(k8s_api, workflow))
    if not resources:
        raise ValueError("jobspec resources empty")
    if len(resources) > 1 or resources[0]["type"] != "node":
        raise ValueError(
            "jobspec resources must have a single top-level 'node' entry, "
            f"got {len(resources)} entries, first entry {resources[0]['type']!r}"
        )
    ssd_resources = {"type": "ssd", "count": 0, "exclusive": True}
    nodecount = resources[0]["count"]
    resources[0]["count"] = 1
    # construct a new jobspec resources with top-level 'slot' resources
    new_resources = [
        {
            "type": "slot",
            "count": nodecount,  # the old nodecount, now for slots
            "label": "rabbit",
            "with": [
                resources[0],
                ssd_resources,
            ],
        }
    ]
    allocation_applied = False
    copy_offload = False
    # update ssd_resources to the right number
    for breakdown in breakdown_list:
        if "copy-offload" in breakdown["status"].get("requiredDaemons", []):
            copy_offload = True
        if breakdown["kind"] != "DirectiveBreakdown":
            raise ValueError(f"unsupported breakdown kind {breakdown['kind']!r}")
        if not breakdown["status"]["ready"]:
            raise RuntimeError("Breakdown marked as not ready")
        if "storage" in breakdown["status"]:  # persistentdw directives have no storage
            for allocation in breakdown["status"]["storage"]["allocationSets"]:
                _apply_allocation(
                    allocation, ssd_resources, nodecount, min_size, limits
                )
                allocation_applied = True
    limits.validate(nodecount)
    if not allocation_applied:
        return (old_resources, copy_offload)
    return (new_resources, copy_offload)


def fetch_breakdowns(k8s_api, workflow):
    """Fetch all of the directive breakdowns associated with a workflow."""
    if not workflow["status"].get("directiveBreakdowns"):
        return  # destroy_persistent DW directives have no breakdowns
    for breakdown in workflow["status"]["directiveBreakdowns"]:
        yield k8s_api.get_namespaced_custom_object(
            DIRECTIVEBREAKDOWN_CRD.group,
            DIRECTIVEBREAKDOWN_CRD.version,
            breakdown["namespace"],
            DIRECTIVEBREAKDOWN_CRD.plural,
            breakdown["name"],
        )


def _apply_allocation(allocation, ssd_resources, nodecount, min_size, limits):
    """Parse a single 'allocationSet' and apply to it a jobspec's ``resources``."""
    expected_alloc_strats = {
        "xfs": AllocationStrategy.PER_COMPUTE.value,
        "raw": AllocationStrategy.PER_COMPUTE.value,
        "gfs2": AllocationStrategy.PER_COMPUTE.value,
        "ost": AllocationStrategy.ACROSS_SERVERS.value,
        "mdt": AllocationStrategy.ACROSS_SERVERS.value,
        "mgt": AllocationStrategy.SINGLE_SERVER.value,
        "mgtmdt": AllocationStrategy.ACROSS_SERVERS.value,
    }
    capacity_gb = max(min_size, allocation["minimumCapacity"] // (1024**3))
    if allocation["allocationStrategy"] != expected_alloc_strats[allocation["label"]]:
        raise ValueError(
            f"{allocation['label']} allocationStrategy "
            f"must be {expected_alloc_strats[allocation['label']]!r} "
            f"but got {allocation['allocationStrategy']!r}"
        )
    limits.increment(allocation["label"], capacity_gb)
    if allocation["label"] in PER_COMPUTE_TYPES:
        ssd_resources["count"] += capacity_gb
    else:
        ssd_resources["count"] += capacity_gb // nodecount
