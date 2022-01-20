from flux_k8s.crd import DIRECTIVEBREAKDOWN_CRD


def apply_breakdowns(k8s_api, workflow, resources):
    """Apply all of the directive breakdown information to a jobspec's `resources`."""
    for breakdown in _fetch_breakdowns(k8s_api, workflow):
        if breakdown["kind"] != "DirectiveBreakdown":
            raise ValueError(f"unsupported breakdown kind {breakdown['kind']!r}")
        for allocation in breakdown["status"]["allocationSet"]:
            _apply_allocation(allocation, resources)


def _fetch_breakdowns(k8s_api, workflow):
    """Fetch all of the directive breakdowns associated with a workflow."""
    if not workflow["status"]["directiveBreakdowns"]:
        raise ValueError(f"workflow {workflow} has no directive breakdowns")
    for breakdown in workflow["status"]["directiveBreakdowns"]:
        yield k8s_api.get_namespaced_custom_object(
            DIRECTIVEBREAKDOWN_CRD.group,
            DIRECTIVEBREAKDOWN_CRD.version,
            breakdown["namespace"],
            DIRECTIVEBREAKDOWN_CRD.plural,
            breakdown["name"],
        )


def _apply_allocation(allocation, resources):
    """Parse a single 'allocationSet' and apply to it a jobspec's ``resources``."""
    if allocation["label"] == "xfs":
        _apply_xfs(allocation["minimumCapacity"], resources)
    elif allocation["label"] in ("ost", "mgt", "mdt"):
        _apply_lustre(allocation, resources)
    else:
        raise ValueError(f"Unknown label {allocation['label']!r}")


def _get_nnf_resource(capacity):
    return {
        "type": "nnf",
        "count": 1,
        "with": [{"type": "ssd", "count": max(1, capacity // (1024 ** 3)), "exclusive": True}],
    }


def _apply_xfs(capacity, resources):
    """Apply XFS (node-local storage) to a jobspec's ``resources``."""
    if len(resources) > 1 or resources[0]["type"] != "node":
        raise ValueError("jobspec resources must have a single top-level 'node' entry")
    node = resources[0]
    nodecount = node["count"]
    resources.append(_get_nnf_resource(capacity))
    # node["count"] = 1
    # resources[0] = {"type": "slot", "label": "foobar", "count": nodecount, "with": [node, _get_nnf_resource(capacity)]}


def _apply_lustre(allocation, resources):
    """Apply Lustre OST/MGT/MDT to a jobspec's ``resources`` dictionary."""
    # if there is already a `rabbit-label[storage]` entry, add to its `count` field
    for entry in resources:
        if entry["type"] == f"rabbit-{allocation['label']}":
            _aggregate_resources(entry["with"], allocation["minimumCapacity"])
            return
    resources.append(
        {
            "type": f"rabbit-{allocation['label']}",
            "count": 1,
            "with": [
                {"type": "storage", "count": allocation["minimumCapacity"], "unit": "B"}
            ],
        }
    )


def _aggregate_resources(with_resources, additional_capacity):
    for resource in with_resources:
        if resource["type"] == "storage":
            if resource.get("unit") == "B":
                resource["count"] = resource.get("count", 0) + additional_capacity
            else:
                raise ValueError(
                    f"Unit mismatch: expected 'B', got {resource.get('unit')}"
                )
            break
    else:
        raise ValueError(f"{entry} has no 'storage' entry")
