"""Module defining functions related to DirectiveBreakdown resources."""

import enum
import copy
import functools
import math
import collections
import abc

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


def check_is_lustre(breakdown_alloc_sets):
    """Return True if the directivebreakdown represents a Lustre file system."""
    for alloc_set in breakdown_alloc_sets:
        if alloc_set["label"] in LUSTRE_TYPES:
            return True
    return False


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
                counts_per_rabbit = {}
                while count > 0:
                    # count may be greater than the rabbits available, so we may need
                    # to place multiple on a single rabbit (hence the outer while-loop)
                    for name, _ in collections.Counter(nodes_per_nnf).most_common(
                        count
                    ):
                        counts_per_rabbit[name] = counts_per_rabbit.get(name, 0) + 1
                        count -= 1
                        if count == 0:
                            break
                for name, val in counts_per_rabbit.items():
                    storage_field.append(
                        {
                            "allocationCount": val,
                            "name": name,
                        }
                    )
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


class JobspecModifier(abc.ABC):
    """Base class for modifying Jobspecs to add rabbit resources."""

    def __init__(self, resources, min_size):
        self.resources = copy.deepcopy(resources)
        self._min_size = min_size
        self.ssd_resources = {"type": "ssd", "count": 0, "exclusive": True}
        self.limits = ResourceLimits()
        self.nodecount = 1

    def _get_capacity_per_node(self, allocation):
        """Parse a single 'allocationSet' and turn it into a per-node capacity."""
        expected_alloc_strats = {
            "xfs": AllocationStrategy.PER_COMPUTE.value,
            "raw": AllocationStrategy.PER_COMPUTE.value,
            "gfs2": AllocationStrategy.PER_COMPUTE.value,
            "ost": AllocationStrategy.ACROSS_SERVERS.value,
            "mdt": AllocationStrategy.ACROSS_SERVERS.value,
            "mgt": AllocationStrategy.SINGLE_SERVER.value,
            "mgtmdt": AllocationStrategy.ACROSS_SERVERS.value,
        }
        capacity_gb = max(
            self._min_size, math.ceil(allocation["minimumCapacity"] / (1024**3))
        )
        if (
            allocation["allocationStrategy"]
            != expected_alloc_strats[allocation["label"]]
        ):
            raise ValueError(
                f"{allocation['label']} allocationStrategy "
                f"must be {expected_alloc_strats[allocation['label']]!r} "
                f"but got {allocation['allocationStrategy']!r}"
            )
        self.limits.increment(allocation["label"], capacity_gb)
        if allocation["label"] in PER_COMPUTE_TYPES:
            return capacity_gb
        return math.ceil(capacity_gb / self.nodecount)

    def apply_allocation(self, allocation):
        """Apply a directivebreakdown to the jobspec."""

    def get_new_resources(self):
        """Return the newly modified jobspec resources."""


class NodeJobspecModifier(JobspecModifier):
    """Modifier class for jobspecs with top-level 'node' entries."""

    def __init__(self, resources, min_size):
        super().__init__(resources, min_size)
        self.nodecount = self.resources[0]["count"]

    def apply_allocation(self, allocation):
        """Apply a directivebreakdown to the jobspec."""
        self.ssd_resources["count"] += self._get_capacity_per_node(allocation)

    def get_new_resources(self):
        """Return the newly modified jobspec resources."""
        if self.ssd_resources["count"] <= 0:
            return None
        self.limits.validate(self.nodecount)
        self.resources[0]["count"] = 1
        return [
            {
                "type": "slot",
                "count": self.nodecount,  # the old nodecount, now for slots
                "label": "rabbit",
                "with": [
                    self.resources[0],
                    self.ssd_resources,
                ],
            }
        ]


class ChassisJobspecModifier(JobspecModifier):
    """Modifier class for jobspecs with top-level 'chassis' entries."""

    def __init__(self, resources, min_size):
        super().__init__(resources, min_size)
        if resources[0]["with"][0]["type"] != "node":
            raise ValueError(
                f"Expected 'node' type below 'chassis, got "
                f"{resources[0]['with'][0]['type']}"
            )
        self.nodes_per_chassis = resources[0]["with"][0]["count"]
        self.nodecount = self.nodes_per_chassis * resources[0]["count"]

    def get_new_resources(self):
        """Return the newly modified jobspec resources."""
        if self.ssd_resources["count"] <= 0:
            return None
        self.limits.validate(self.nodecount)
        self.resources[0]["with"].append(self.ssd_resources)
        return self.resources

    def apply_allocation(self, allocation):
        """Apply a directivebreakdown to the jobspec."""
        capacity_gb = self._get_capacity_per_node(allocation)
        self.ssd_resources["count"] += capacity_gb * self.nodes_per_chassis


def apply_breakdowns(k8s_api, workflow, resources, min_size):
    """Apply all of the directive breakdown information to a jobspec's `resources`.

    Return the modified resources, or, if it appears that the modification has already
    been applied, return None.
    """
    breakdown_list = list(fetch_breakdowns(k8s_api, workflow))
    if not resources:
        raise ValueError("jobspec resources empty")
    # check if jobspec already has `ssd` entries
    if resources[0]["type"] in ("slot", "chassis") and len(resources[0]["with"]) == 2:
        for subresource in resources[0]["with"]:
            if subresource["type"] not in ("ssd", "node"):
                raise ValueError(
                    f"jobspec resources has top level '{resources[0]['type']}' entry "
                    f"with {subresource['type']} below it"
                )
        # if we've reached here, jobspec has `ssd` entries, assume it was already
        # updated; return None.
        return None
    if len(resources) > 1:
        raise ValueError(
            "jobspec resources must have a single top-level 'node' or 'chassis' entry,"
            f" got {len(resources)} entries"
        )
    if resources[0]["type"] == "chassis":
        modifier = ChassisJobspecModifier(resources, min_size)
    elif resources[0]["type"] == "node":
        modifier = NodeJobspecModifier(resources, min_size)
    else:
        raise ValueError(
            "jobspec resources must have a single top-level 'node' or 'chassis' entry,"
            f" got {resources[0]['type']!r}"
        )
    # go through all the breakdowns and apply their resources to the jobspec
    for breakdown in breakdown_list:
        if breakdown["kind"] != "DirectiveBreakdown":
            raise ValueError(f"unsupported breakdown kind {breakdown['kind']!r}")
        if not breakdown["status"]["ready"]:
            raise RuntimeError("Breakdown marked as not ready")
        if "storage" in breakdown["status"]:  # persistentdw directives have no storage
            for allocation in breakdown["status"]["storage"]["allocationSets"]:
                modifier.apply_allocation(allocation)
    new_resources = modifier.get_new_resources()
    if new_resources is None:
        return resources  # return the original jobspec's resources section
    return new_resources


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
