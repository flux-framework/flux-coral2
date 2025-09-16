from kubernetes import client
from flux_k8s import cleanup
import logging
import random
import copy

LOGGER = logging.getLogger(__name__)


# Defaults
# https://github.com/converged-computing/flux-slingshot/blob/main/minicluster.yaml

# This has flux built with cxi for slingshot
default_container = "ghcr.io/converged-computing/flux-slingshot:ubuntu2404"

# Flux Operator versions
default_group = "flux-framework.org"
default_version = "v1alpha2"
default_namespace = "default"
default_plural = "miniclusters"

# Devices and volumes
device_path = "/sys/devices"
net_path = "/sys/class/net"

# Not sure there is any reason to change this
default_podspec = {
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


class RabbitMPI:
    """
    A RabbitMPI Job is a Flux MiniCluster job running on the rabbits.

    This class serves as a wrapper around a Flux jobspec to easily get
    rabbit MPI attributes for the MiniCluster. "Bwing in... the wabbits!"
    It can be a real jobspec, or a faux one with attributes populated.
    """

    def __init__(self, jobspec, wabbits=None):
        self.jobspec = jobspec

        # We must have the wabbit nodes.
        self.set_wabbits(wabbits)

    def is_enabled(self):
        """
        Having the MPI attribute (with anything) indicates being enabled.
        """
        if not self.jobspec.get("attributes", {}).get("system", {}).get("rabbit"):
            return False
        return (
            self.jobspec.get("attributes", {})
            .get("system", {})
            .get("rabbit")
            .get("mpi")
            is not None
        )

    def is_false(self, value):
        """
        Determine if a directive is false.

        We assume unset (None) defaults to whatever the field default is.
        """
        # So many ways to say no!
        if isinstance(value, str):
            value = value.lower()
        return value in ["false", False, "no", "0", 0]

    def get_attribute(self, name):
        """
        Get an attribute from the jobspec for the rabbit.mpi

        This needs to return None if there is an empty string or similar.
        I'd ideally like to put this under attributes (and not system) but likely
        system is more correct :)
        """
        rabbit_directive = (
            self.jobspec.get("attributes", {}).get("system", {}).get("rabbit")
        )
        if not rabbit_directive or not isinstance(rabbit_directive, dict):
            return None

        mpi_directive = rabbit_directive.get("mpi")
        if not mpi_directive or not isinstance(mpi_directive, dict):
            return None

        return (
            self.jobspec.get("attributes", {})
            .get("system", {})
            .get("rabbit")
            .get("mpi", {})
            .get(name)
            or None
        )

    @property
    def container(self):
        """
        User specified container image, or use flux slingshot (cxi) base

        Example:
          --setattr=rabbit.mpi.image="ghcr.io/converged-computing/lammps-reax:ubuntu2404-cxi"
        """
        return self.get_attribute("image") or default_container

    @property
    def workdir(self):
        """
        User specified working directory, or honor what container has set.

        Example:
          --setattr=rabbit.mpi.workdir="/opt/lammps/examples/reaxff/HNS"
        """
        return self.get_attribute("workdir")

    @property
    def command(self):
        """
        User specified command (tested, this works)!

        Example:
          --setattr=rabbit.mpi.command='lmp -x1 -x2 -x3'
        """
        return self.get_attribute("command")

    def add_flux(self):
        """
        A directive that says "I already have Flux in my container"
        We really only care if this is set to some variant of NO.

        Example:
          --setattr=rabbit.mpi.add_flux=false
        """
        # If we are using default container, we don't add flux
        if self.container == default_container:
            return False

        # Nothing set, we assume adding the flux view
        value = self.get_attribute("add_flux")
        if not value:
            return True

        # Otherwise, we only care if it's set to False
        return not self.is_false(value)

    def set_wabbits(self, wabbits):
        """
        This is a hard requirement to have a list of rabbit nodes.
        """
        self.wabbits = wabbits

    @property
    def interactive(self):
        """
        Determine if the minicluster should be interactive.
        This is based on a command being set or not.
        """
        return self.command is not None

    @property
    def always_succeed(self):
        """
        Always succeed the job.

        Example:
          --setattr=rabbit.mpi.succeed=true
        """
        return self.get_attribute("succeed") is not None

    @property
    def tasks(self):
        """
        Number of tasks to request for the job.
        Assume for now the user knows what they are doing. The job
        will not be satisfiable if not, and that is user error.

        Example:
          --setattr=rabbit.mpi.tasks=96
        """
        return self.get_attribute("tasks")

    @property
    def environment(self):
        """
        Derive the default environment plus whatever extra the user has asked for.

        If these are bad/wrong, we might not want to add by default.

        Example:
          --setattr=rabbit.mpi.env.one=ketchup --setattr=rabbit.mpi.env.two=mustard
        """
        environ = {
            "OMPI_MCA_orte_base_help_aggregate": "0",
            "OMPI_MCA_btl": "^openib",
        }
        # User preferences override
        environ.update(self.get_attribute("env") or {})
        return environ

    @property
    def volumes(self):
        """
        Get default rabbit volumes.

        volumes:
          devices:
            hostPath: /sys/devices
            path: /sys/devices
          net:
            hostPath: /sys/class/net
            path: /sys/class/net
        """
        # TODO: should we be binding other volumes from the host?
        return {
            "devices": {"hostPath": device_path, "path": device_path},
            "net": {"hostPath": net_path, "path": net_path},
        }

    @property
    def security_context(self):
        """
        Get default security context for MiniCluster

        securityContext:
          privileged: true

        This will need to be further tweaked I suspect.
        """
        return {"privileged": True}

    @property
    def rabbits(self):
        """
        The user can request specific rabbit names, e.g., a subset.

        Example:
          --setattr=rabbit.mpi.rabbits=hetchy201,hetchy202
        """
        return self.get_attribute("rabbits")

    @property
    def nodes(self):
        """
        Number of nodes for the job
        Request MUST be less than or equal to number of rabbits.

        Example:
          --setattr=rabbit.mpi.nodes=4
        """
        nnodes = self.get_attribute("nodes")

        # This must parse, otherwise we fall back to the number of rabbits requested
        if nnodes is not None:
            try:
                nnodes = int(nnodes)
            except ValueError:
                LOGGER.warning(
                    f"Cannot parse user directive for rabbit.mpi.nodes: {nnodes}"
                )
                nnodes = None
        return nnodes


class MiniCluster:
    """
    A MiniClusterBase does not require an official workflow.

    We can launch it directly on the rabbit nodes separately from a Flux Job.
    This is likely for testing (or fun) - "flux hop" - and we just require
    a populated job.
    """

    def __init__(self, handle, jobid=None):
        """
        A MiniCluster Family object is used for a scoped session in a Flux instance.

        We assume it is associated with a specific, top level jobid
        """
        self.handle = handle
        self.jobid = jobid
        self.k8s_api = cleanup.get_k8s_api(self.handle.conf_get("rabbit.kubeconfig"))

    @classmethod
    def is_requested(cls, jobspec):
        """
        Determine if a MiniCluster is required via the rabbit.mpi attribute.
        """
        return RabbitMPI(jobspec).is_enabled()

    @property
    def podspec(self):
        """
        Generate the PodSpec for the MiniCluster. E.g.,

        pod:
          nodeSelector:
            cray.nnf.node: "true"
        tolerations:
         - effect: NoSchedule
           key: cray.nnf.node
           operator: Equal
           value: "true"
        """
        return default_podspec

    def generate(self, job, name, namespace, labels=None):
        return self._generate(job, name, namespace, labels)

    def _generate(self, job, name, namespace, labels=None):
        """
        Generate a standalone MiniCluster.

        This is shared by both types of MiniCluster. The main difference is that
        an official rabbit job will be populated by an actual JobSpec and workflow,
        and a "flux hop" standalone cluster is generated artificially without one.
        """
        metadata = client.V1ObjectMeta(name=name, namespace=namespace)
        labels = labels or {}

        # TODO: I think we can leave duration unset, assuming it will be
        # cleaned up by job deletion. If this cannot be assumed, we need to set
        # something to be slightly less than the job (but I don't like this).

        # For resources, we don't need to do anything complicated.
        # We assign to number of rabbit nodes (or fewer).
        # This returns a list of rabbit names, accounting for
        # user requests for count and specific nodes
        nodes = self.calculate_nodes(job)

        # TODO: this is what resources should look like, but with rabbit AMD, etc.
        # resources = {"cpu": cores_per_task, "nvidia.com/gpu": gpus_per_task}
        # return {"requests": resources, "limits": resources}

        # TODO: how should a user specify a command?
        # TODO: what about pull policy - allow to set?
        # For now we can do interactive.
        container = {
            "command": job.command,
            "image": job.container,
            "workingDir": job.workdir,
            "name": name,
            "launcher": False,
            "environment": job.environment,
            # TODO: talk about rabbit mounts / volumes that are needed here
            "volumes": job.volumes,
            # TODO: what about resource limits/requests?
            "resources": {},
            "securityContext": job.security_context,
        }

        # Should the job always succeed?
        if job.always_succeed:
            labels["always-succeed"] = "1"

        # The main spec needs the job container, sizes, and the podspec
        spec = {
            "containers": [container],
            "interactive": job.interactive,
            "jobLabels": labels,
            # TODO: can we allow autoscaling?
            "maxSize": len(nodes),
            "size": len(nodes),
            "tasks": job.tasks,
            "pod": self.podspec,
        }

        # Add the Flux view? Defaults to yes
        # TODO: we will need to understand if the view should be customized.
        # E.g., normally this is an issue for ubuntu OS differences and platform
        if not job.add_flux():
            spec["flux"] = {"container": {"disable": True}}

        # Make this bad boi.
        minicluster = {
            "kind": "MiniCluster",
            "metadata": metadata,
            "apiVersion": "flux-framework.org/v1alpha2",
            "spec": spec,
        }
        return self.create(minicluster)

    def create(self, minicluster):
        """
        Wrapper to create the MiniCluster with the CustomObject API
        """
        try:
            return self.k8s_api.create_namespaced_custom_object(
                group="flux-framework.org",
                version="v1alpha2",
                namespace=minicluster["metadata"].namespace,
                plural="miniclusters",
                body=minicluster,
            )
        except client.rest.ApiException as e:
            name = minicluster["metadata"].name
            if e.reason == "Conflict":
                LOGGER.warning(
                    f"MiniCluster job for {name} exists, assuming resumed: {e.reason}"
                )
            else:
                LOGGER.info(
                    f"There was a create MiniCluster error for {name}: {e.reason}, {e}"
                )

    def calculate_nodes(self, job):
        """
        Calculate the desired number of nodes.

        We assume a size == the number of rabbits.
        We allow the user to specify fewer.
        """
        # This is the number of nodes, and rabbit node names
        nnodes = job.nodes
        LOGGER.warning(job.wabbits)
        LOGGER.warning(type(job.wabbits))
        wabbits = copy.deepcopy(job.wabbits)

        # Not allowed to request more than the number of rabbits!
        nnodes = len(wabbits) if not nnodes else min(len(wabbits), nnodes)

        # Let's assume we want random selection, unless the user requests differently
        random.shuffle(wabbits)

        # Check if we have node names. Note that if there are fewer names
        # requested than total rabbits, we only provision the subset.
        rabbit_names = job.rabbits
        if rabbit_names is not None:
            wabbits = list(set(wabbits).intersection(set(rabbit_names)))

        # To be more efficient, return the node names here
        return wabbits[0:nnodes]


class RabbitMiniCluster(MiniCluster):
    """
    Handle to interact with and generate Flux Operator MiniClusters.

    This MiniCluster is created with an official rabbit job and Flux
    """

    def generate(self, jobspec, workflow, wabbits):
        """
        Submit a minicluster job to Kubernetes on the rabbits.

        We receive the Workflow CRD to retrieve metadata for. If necessary,
        we should get and interact with other CRD abstractions related to the
        rabbits. We need to inspect what the workflow gives us (and what is missing)
        to decide.
        """
        # If we don't have a jobid, we can't continue
        if not self.jobid:
            LOGGER.warning(
                "A jobid is required for a RabbitMiniCluster to associate rabbit nodes."
            )
            return

        # TODO: inspect and discuss which to keep / not keep
        # TODO: if jobid not a label, we should add it
        # TODO: putting these on the job - should we do anything on pod?
        # TODO: do we want (need) annotations too? Job or Pod?
        labels = workflow["metadata"].get("labels") or {}

        # We need to get the rabbit nodes from the job
        LOGGER.warning(f"handle: {self.handle}")
        LOGGER.warning(f"jobid: {self.jobid}")
        LOGGER.warning(f"wabbits: {wabbits}")

        # This serves as easy access to job metadata
        job = RabbitMPI(jobspec, wabbits)

        # Assume we will generate a MiniCluster with the same workflow name
        # The namespace should technically always be populated
        LOGGER.warning(workflow["metadata"])
        name = workflow["metadata"]["name"]
        namespace = workflow["metadata"].get("namespace") or default_namespace
        return self._generate(job, name, namespace, labels=labels)
