import copy
import logging
import random

import flux_k8s.operator.defaults as defaults
from flux_k8s import cleanup
from flux_k8s.operator.rabbits import RabbitMPI
from flux_k8s.crd import DEFAULT_NAMESPACE
from kubernetes import client, config

LOGGER = logging.getLogger(__name__)

import flux
import flux.job

def teardown_minicluster(handle, winfo):
    """
    Tear down the MiniCluster, first saving the lead broker log to KVS
    """
    LOGGER.warning("START OF TEARDOWN MINICLUSTER")
    minicluster = RabbitMiniCluster(
        handle=handle,
        jobid=winfo.jobid,
        name=winfo.name,
        namespace=DEFAULT_NAMESPACE,
    )

    # Cut out early if we don't exist.
    LOGGER.warning("CHECKING EXISTS")
    if not minicluster.exists():
         return
    LOGGER.warning("I AM EXISTS")

    # Get the lead broker logs and save to KVS
    log = minicluster.logs()
    if not log:
        return
    LOGGER.warning(log)
    LOGGER.warning("WE HAAWDSADAD LOG")

    with flux.job.job_kvs(handle, winfo.jobid) as kvsdir:
        kvsdir["rabbitmpi_container_log"] = log[-50000:]

    # And finally, cleanup
    minicluster.delete()


def delete_minicluster(k8s_api, name, namespace):
    """
    Delete a MiniCluster by name and namespace.

    We can make this asynchronous with retry in a loop if needed.
    Kubernetes should not need that, so let's test without first.
    """
    # No grace period - be ruthless!
    delete_options = client.V1DeleteOptions(
        propagation_policy="Background", grace_period_seconds=0
    )
    try:
        k8s_api.delete_namespaced_custom_object(
            group=defaults.group,
            version=defaults.version,
            namespace=namespace,
            plural=defaults.plural,
            name=name,
            body=delete_options,
        )
        LOGGER.warning(
            f"MiniCluster '{name}' in namespace '{namespace}' deleted successfully."
        )
    except client.rest.ApiException as e:
        if e.status == 404:
            # Not found (never created or already cleaned up)
            return
        else:
            LOGGER.warning(
                f"API Error deleting MiniCluster '{name}' in '{namespace}': {e}"
            )


class MiniCluster:
    """
    A MiniClusterBase does not require an official workflow.

    We can launch it directly on the rabbit nodes separately from a Flux Job.
    This is likely for testing (or fun) - "flux hop" - and we just require
    a populated job.
    """

    def __init__(self, handle, name, namespace=defaults.namespace, jobid=None):
        """
        A MiniCluster Family object is used for a scoped session in a Flux instance.

        We assume it is associated with a specific, top level jobid
        """
        self.handle = handle
        self.jobid = jobid
        self.name = name
        self.namespace = namespace
        self.k8s_api = cleanup.get_k8s_api(self.handle.conf_get("rabbit.kubeconfig"))

    @classmethod
    def is_requested(cls, jobspec):
        """
        Determine if a MiniCluster is required via the rabbit.mpi attribute.
        """
        return RabbitMPI(jobspec).is_enabled()

    @classmethod
    def is_allowed(cls, jobspec):
        """
        Determine if a MiniCluster is allowed.

        TODO: we need to check the user, specifics of the jobspec, etc.
        """
        allowed_users = ["corbett8", "sochat1", "milroy1", "mcfadden8"]
        assert allowed_users
        return True

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
        return defaults.podspec

    def generate(self, job):
        return self._generate(job)

    def _generate(self, job):
        """
        Generate a standalone MiniCluster.

        This is shared by both types of MiniCluster. The main difference is that
        an official rabbit job will be populated by an actual JobSpec and workflow,
        and a "flux hop" standalone cluster is generated artificially without one.
        """
        metadata = client.V1ObjectMeta(name=self.name, namespace=self.namespace)

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
            "name": self.name,
            "launcher": False,
            "environment": job.environment,
            # TODO: talk about rabbit mounts / volumes that are needed here
            "volumes": job.volumes,
            # TODO: what about resource limits/requests?
            "resources": {},
            "securityContext": job.security_context,
        }
        LOGGER.warning(container)

        # Should the job always succeed?
        # TODO: add other labels for query
        labels = {}
        if job.always_succeed:
            labels["always-succeed"] = "1"


        # The main spec needs the job container, sizes, and the podspec
        LOGGER.warning("STUFF IS HERE")
        LOGGER.warning(job.tasks)
        LOGGER.warning(len(nodes))
        spec = {
            "containers": [container],
            "interactive": job.interactive,
            "jobLabels": labels,
            # TODO: can we allow autoscaling?
            "maxSize": len(nodes),
            "size": len(nodes),
            "tasks": job.tasks,
            "pod": self.podspec,
            "flux": {},
        }

        # Add the Flux view? Defaults to yes
        # TODO: we will need to understand if the view should be customized.
        # E.g., normally this is an issue for ubuntu OS differences and platform
        if not job.add_flux():
            spec["flux"]["container"] = {"disable": True}

        # Ask for exclusive nodes
        if job.exclusive:
            spec['flux']['optionFlags'] = "--exclusive"

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
                **self.crd_info, body=minicluster
            )
        except client.rest.ApiException as e:
            name = minicluster["metadata"].name
            if e.reason == "Conflict":
                LOGGER.warning(
                    f"MiniCluster job for {name} exists, assuming resumed: {e.reason}"
                )
            else:
                LOGGER.warning(
                    f"There was a create MiniCluster error for {name}: {e.reason}, {e}"
                )

    def delete(self):
        """
        Basic deletion function for an instance
        """
        return delete_minicluster(self.k8s_api, self.name, self.namespace)

    @property
    def crd_info(self):
        """
        Shared MiniCluster information for requests
        """
        return {
            "group": defaults.group,
            "version": defaults.version,
            "namespace": self.namespace,
            "plural": defaults.plural,
        }

    def exists(self):
        """
        Determine if a MiniCluster exists.
        """
        LOGGER.warning(self.crd_info)
        LOGGER.warning(self.name)
        try:
            found = self.k8s_api.get_namespaced_custom_object(name=self.name, **self.crd_info)
            LOGGER.warning(found)
            return True
        except Exception as e:
            LOGGER.warning(f"Exception: {e}")
            return False

    def logs(self):
        """
        Get the lead broker log.
        """
        k8s_api = client.CoreV1Api(config.new_client_from_config(self.handle.conf_get("rabbit.kubeconfig")))

        # Get pods associated with the jobid
        selector = f"batch.kubernetes.io/job-name={self.name}"
        LOGGER.warning(selector)
        pods = k8s_api.list_namespaced_pod(
            label_selector=selector, namespace=self.namespace
        ).items

        # Just save the lead broker for now - should be the first one
        lead_broker = [x for x in pods if f"{self.name}-0-" in x.metadata.name]
        if not lead_broker:
            LOGGER.warning(f"Cannot find pods for {selector}")
            return
        lead_broker = lead_broker[0]

        try:
            return k8s_api.read_namespaced_pod_log(
                name=lead_broker.metadata.name,
                namespace=self.namespace,
                follow=False,
                timestamps=True,
            )
        except client.rest.ApiException as e:
            LOGGER.warning(f"Error getting logs: {e}")

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

    def generate(self, jobspec, wabbits):
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

        # We need to get the rabbit nodes from the job
        LOGGER.warning(f"handle: {self.handle}")
        LOGGER.warning(f"jobid: {self.jobid}")
        LOGGER.warning(f"wabbits: {wabbits}")

        # This serves as easy access to job metadata
        job = RabbitMPI(jobspec, wabbits)
        return self._generate(job)
