from flux_k8s.crd import DIRECTIVEBREAKDOWN_CRD


def apply_breakdowns(k8s_api, workflow, resources):
    """Apply all of the directive breakdown information to a jobspec's `resources`."""
    for breakdown in fetch_breakdowns(k8s_api, workflow):
        if breakdown["kind"] != "DirectiveBreakdown":
            raise ValueError(f"unsupported breakdown kind {breakdown['kind']!r}")
        for allocation in breakdown["status"]["allocationSet"]:
            apply_allocation(allocation, resources)


def fetch_breakdowns(k8s_api, workflow):
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


def apply_allocation(allocation, resources):
    """Parse a single 'allocationSet' and apply to it a jobspec's ``resources``."""
    if allocation["label"] == "xfs":
        apply_xfs(allocation, resources)
    elif allocation["label"] in ("ost", "mgt", "mdt"):
        apply_lustre(allocation, resources)
    else:
        raise ValueError(f"Unknown label {allocation['label']!r}")


def apply_xfs(allocation, resources):
    """Apply XFS (node-local storage) to a jobspec's ``resources``."""
    with_storage = {
        "type": "storage",
        "count": allocation["minimumCapacity"],
        "unit": "B",
    }
    for i, entry in enumerate(resources):
        if entry["type"] == "node":
            node = entry
            break
        if entry["type"] == "slot":
            node = {"type": "node", "count": {"min": 1}, "with": [entry]}
            resources[i] = node
            break
    else:
        raise ValueError(
            f"Neither 'node' nor 'slot' found within jobspec resources {resources}"
        )
    for entry in node["with"]:
        # if there is already a `rabbit-xfs[storage]` entry, add to its `count` field
        if entry["type"] == "rabbit-xfs":
            aggregate_resources(entry["with"], allocation["minimumCapacity"])
            return
    node["with"].append(
        {
            "type": "rabbit-xfs",
            "count": 1,
            "with": [
                {"type": "storage", "count": allocation["minimumCapacity"], "unit": "B"}
            ],
        }
    )


def apply_lustre(allocation, resources):
    """Apply Lustre OST/MGT/MDT to a jobspec's ``resources`` dictionary."""
    # if there is already a `rabbit-label[storage]` entry, add to its `count` field
    for entry in resources:
        if entry["type"] == f"rabbit-{allocation['label']}":
            aggregate_resources(entry["with"], allocation["minimumCapacity"])
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


def aggregate_resources(with_resources, additional_capacity):
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
