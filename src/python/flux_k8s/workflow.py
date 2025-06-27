"""Module defining classes and functions for storing and manipulating workflows."""

import collections
import logging
import enum

import flux
import flux.job

from flux_k8s import cleanup, crd


LOGGER = logging.getLogger(__name__)


class WorkflowState(str, enum.Enum):
    """Enum for possible Workflow States."""

    PROPOSAL = "Proposal"
    SETUP = "Setup"
    DATAIN = "DataIn"
    PRERUN = "PreRun"
    POSTRUN = "PostRun"
    DATAOUT = "DataOut"
    TEARDOWN = "Teardown"
    TRANSIENTCONDITION = "TransientCondition"


# Represents and holds information about a TransientCondition for a workflow
TransientConditionInfo = collections.namedtuple(
    "TransientConditionInfo", ["last_time", "last_message", "prerun"]
)


class WorkflowInfo:
    """Represents and holds information about a specific workflow object.

    The class offers methods for maintaining a set of instances.
    """

    save_datamovements = 0

    _WORKFLOWINFO_CACHE = {}  # maps jobids to WorkflowInfo objects
    _WORKFLOW_NAME_PREFIX = "fluxjob-"
    _WORKFLOW_NAME_FORMAT = _WORKFLOW_NAME_PREFIX + "{jobid}"

    @classmethod
    def add(cls, jobid, *args, **kwargs):
        """Add an entry to the cache of instances."""
        new_instance = cls(jobid, *args, **kwargs)
        cls._WORKFLOWINFO_CACHE[new_instance.jobid] = new_instance
        return new_instance

    @classmethod
    def get(cls, jobid):
        """Return an instance with the given jobid."""
        return cls._WORKFLOWINFO_CACHE.setdefault(jobid, cls(jobid))

    @classmethod
    def remove(cls, jobid):
        """Remove an instance with the given jobid."""
        del cls._WORKFLOWINFO_CACHE[jobid]

    @classmethod
    def get_name(cls, jobid):
        """Get the name of a workflow."""
        return cls._WORKFLOW_NAME_FORMAT.format(jobid=jobid)

    @classmethod
    def is_recognized(cls, name):
        """Return True if the given workflow name is consistent with the scheme."""
        return name.startswith(cls._WORKFLOW_NAME_PREFIX)

    @classmethod
    def known_workflows(cls):
        return cls._WORKFLOWINFO_CACHE.keys()

    def __init__(self, jobid, name=None, resources=None):
        self.jobid = jobid
        if name is None:
            self.name = self.get_name(jobid)
        else:
            self.name = name  # name of the k8s workflow
        self.resources = resources  # jobspec 'resources' field
        self.toredown = False  # True if workflows has been moved to teardown
        self.deleted = False  # True if delete request has been sent to k8s
        self.epilog_removed = False  # True if jobtap epilog was already removed
        self.postrun_watcher = None  # Flux timer-watcher for the PostRun state

    def move_to_teardown(self, handle, k8s_api, workflow=None):
        """Move a workflow to the 'Teardown' desiredState."""
        if workflow is None:
            workflow = k8s_api.get_namespaced_custom_object(
                *crd.WORKFLOW_CRD, self.name
            )
        datamovements = self._get_datamovements(k8s_api)
        save_workflow_to_kvs(handle, self.jobid, workflow, datamovements)
        cleanup.teardown_workflow(workflow)
        self.toredown = True

    def _get_datamovements(self, k8s_api):
        """Fetch datamovement resources and optionally dump them to the logs.

        Save every datamovement to the logs if loglevel is INFO or more verbose.

        Return 'self.save_datamovements' datamovements.
        """
        if self.save_datamovements <= 0:
            return []
        try:
            api_response = k8s_api.list_cluster_custom_object(
                group=crd.DATAMOVEMENT_CRD.group,
                version=crd.DATAMOVEMENT_CRD.version,
                plural=crd.DATAMOVEMENT_CRD.plural,
                limit=self.save_datamovements,
                label_selector=(
                    f"{crd.DWS_GROUP}/workflow.name={self.name},"
                    f"{crd.DWS_GROUP}/workflow.namespace=default"
                ),
            )
        except Exception as exc:
            LOGGER.warning(
                "Failed to fetch %s crds for workflow '%s': %s",
                crd.DATAMOVEMENT_CRD.plural,
                self.name,
                exc,
            )
            return []
        datamovements = []
        successful_datamovements = []
        for dm_crd in api_response["items"]:
            if len(datamovements) < self.save_datamovements:
                if dm_crd.get("status", {}).get("status") == "Failed":
                    datamovements.append(dm_crd)
                else:
                    successful_datamovements.append(dm_crd)
        if len(datamovements) < self.save_datamovements:
            datamovements.extend(
                successful_datamovements[: self.save_datamovements - len(datamovements)]
            )
        return datamovements

    def move_desiredstate(self, desiredstate, k8s_api):
        """Helper function for moving workflow to a desiredState."""
        k8s_api.patch_namespaced_custom_object(
            *crd.WORKFLOW_CRD,
            self.name,
            {"spec": {"desiredState": desiredstate}},
        )


def save_workflow_to_kvs(handle, jobid, workflow, datamovements=None):
    """Save a workflow to a job's KVS, ignoring errors."""
    try:
        timing = workflow["status"]["elapsedTimeLastState"]
        state = workflow["status"]["state"].lower()
    except KeyError:
        timing = None
        state = None
    try:
        with flux.job.job_kvs(handle, jobid) as kvsdir:
            kvsdir["rabbit_workflow"] = workflow
            if timing is not None and state is not None:
                kvsdir[f"rabbit_{state}_timing"] = timing
            if datamovements is not None:
                kvsdir["rabbit_datamovements"] = datamovements
    except Exception:
        LOGGER.exception(
            "Failed to update KVS for job %s: workflow is %s", jobid, workflow
        )
