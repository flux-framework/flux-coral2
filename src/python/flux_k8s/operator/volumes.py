from kubernetes import client
from kubernetes.client.rest import ApiException
import flux_k8s.operator.defaults as defaults
import logging

LOGGER = logging.getLogger(__name__)


def teardown_rabbit_volumes(k8s_api, jobid, namespace):
    """
    Common function to teardown rabbits.

    We need to do this after a minicluster is deleted. If a MiniCluster is
    not found, assume something might have gone wrong and try to cleanup
    anyway. No harm done with 404 response.
    """
    # Cleanup PV/PVC last. The order needs to be:
    #   pods using it
    #   persistent volume claim
    #   persistent volume
    manager = VolumeManager(k8s_api, jobid=jobid, namespace=namespace)
    manager.delete_persistent_volume()
    manager.delete_persistent_volume_claim()


class VolumeManager:
    """
    A class to manage Kubernetes volumes for specific jobs.
    """

    def __init__(self, k8s_api, jobid, namespace="default"):
        """
        Initializes the manager with a job ID and namespace.
        """
        self.jobid = jobid
        self.namespace = namespace
        self.k8s_api = k8s_api

    @property
    def name(self):
        return str(self.jobid)

    def create_persistent_volume(self, rabbits, storage_capacity=None):
        """
        Creates a PersistentVolume specifically for a Lustre CSI driver.

        This function converts the provided YAML manifest into Python objects
        using the Kubernetes client library.
        """
        # TODO can we allow customizing storage capacity?
        storage_capacity = storage_capacity or defaults.storage_capacity

        # Claim Reference
        # This reserves the PV for a specific PVC. TODO: will we have >1 for a job?
        # If so, we can't name based on just the jobid, we need more.
        claim_ref = client.V1ObjectReference(
            kind="PersistentVolumeClaim", name=self.name, namespace=self.namespace
        )

        # CSI (Container Storage Interface) source
        csi_source = client.V1CSIPersistentVolumeSource(
            driver=defaults.csi_driver,
            volume_handle=defaults.volume_handle,
            fs_type=defaults.fs_type,
        )

        # Ensure we bind to the right rabbit nodes
        node_affinity = client.V1VolumeNodeAffinity(
            required=client.V1NodeSelector(
                node_selector_terms=[
                    client.V1NodeSelectorTerm(
                        match_expressions=[
                            client.V1NodeSelectorRequirement(
                                key="kubernetes.io/hostname",
                                operator="In",
                                values=rabbits,
                            )
                        ]
                    )
                ]
            )
        )

        # PersistentVolume Spec
        pv_spec = client.V1PersistentVolumeSpec(
            capacity={"storage": storage_capacity},
            volume_mode="Filesystem",
            access_modes=["ReadWriteMany"],
            storage_class_name=defaults.storage_class_name,
            persistent_volume_reclaim_policy=defaults.volume_reclaim_policy,
            claim_ref=claim_ref,
            csi=csi_source,
            node_affinity=node_affinity,
        )

        # Final PersistentVolume object
        persistent_volume = client.V1PersistentVolume(
            metadata=client.V1ObjectMeta(name=self.name),
            api_version="v1",
            kind="PersistentVolume",
            spec=pv_spec,
        )

        # 6. Call the Kubernetes API to create the PersistentVolume
        try:
            return self.k8s_api.create_persistent_volume(body=persistent_volume)
        except ApiException as e:
            if e.reason == "AlreadyExists":
                LOGGER.warning("PV already exists. No action taken.")
            else:
                LOGGER.warning(f"Error creating PersistentVolume {self.name}': {e}")
                raise

    def create_persistent_volume_claim(self, storage_capacity=None):
        """
        Creates a PersistentVolumeClaim to bind to a specific PersistentVolume.
        """
        storage_capacity = storage_capacity or defaults.storage_capacity

        # TODO this assumes 1 rabbit per jobid, which is unlikely.
        metadata = client.V1ObjectMeta(name=self.name, namespace=self.namespace)

        # Define the resource requests
        resources = client.V1ResourceRequirements(
            requests={"storage": defaults.storage_capacity}
        )

        # Define the PVC spec. The key is setting `volume_name` to bind to our specific PV.
        pvc_spec = client.V1PersistentVolumeClaimSpec(
            access_modes=["ReadWriteMany"],
            storage_class_name=defaults.storage_class_name,
            volume_name=self.name,
            resources=resources,
        )

        persistent_volume_claim = client.V1PersistentVolumeClaim(
            api_version="v1",
            kind="PersistentVolumeClaim",
            metadata=metadata,
            spec=pvc_spec,
        )

        try:
            return self.k8s_api.create_namespaced_persistent_volume_claim(
                namespace=self.namespace, body=persistent_volume_claim
            )
        except ApiException as e:
            if e.reason != "AlreadyExists":
                print(f"Error creating PersistentVolumeClaim '{self.name}': {e}")
                raise

    def delete_persistent_volume_claim(self):
        """
        Delete the PersistentVolumeClaim associated with the job.
        """
        try:
            self.k8s_api.delete_namespaced_persistent_volume_claim(
                name=self.name, namespace=self.namespace
            )
        except ApiException as e:
            if e.status != 404:
                LOGGER.warning(
                    f"Error deleting PersistentVolumeClaim '{self.name}': {e}"
                )
                raise

    def delete_persistent_volume(self):
        """
        Deletes the PersistentVolume associated with the job.
        Note: The associated PVC should be deleted first.
        """
        try:
            self.k8s_api.delete_persistent_volume(name=self.name)
        except ApiException as e:
            if e.status != 404:
                LOGGER.warning(f"Error deleting PersistentVolume '{self.name}': {e}")
                raise
