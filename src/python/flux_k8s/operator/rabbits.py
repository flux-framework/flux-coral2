import logging

import flux_k8s.operator.defaults as defaults

LOGGER = logging.getLogger(__name__)


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
        self.wabbits = wabbits

    def is_enabled(self):
        """
        Having the MPI attribute (with anything) indicates being enabled.
        """
        if not isinstance(
            self.jobspec.get("attributes", {}).get("system", {}).get("rabbit"), dict
        ):
            return False
        return self.jobspec["attributes"]["system"]["rabbit"].get("mpi") is not None

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
        mpi_directive = (
            self.jobspec.get("attributes", {})
            .get("system", {})
            .get("rabbit", {})
            .get("mpi")
        )
        if not mpi_directive or not isinstance(mpi_directive, dict):
            return None
        return self.jobspec["attributes"]["system"]["rabbit"]["mpi"]

    @property
    def container(self):
        """
        User specified container image, or use flux slingshot (cxi) base

        Example:
          --setattr=rabbit.mpi.image="ghcr.io/converged-computing/lammps-reax:ubuntu2404-cxi"
        """
        return self.get_attribute("image") or defaults.container

    @property
    def workdir(self):
        """
        User specified working directory, or honor what container has set.

        Example:
          --setattr=rabbit.mpi.workdir="/opt/lammps/examples/reaxff/HNS"
        """
        return self.get_attribute("workdir")

    @property
    def pull_policy(self):
        """
        User specified pull policy (defaults to IfNotPresent)

        Example:
          --setattr=rabbit.mpi.pull_policy=Always
        """
        return self.get_attribute("pull_policy")

    @property
    def pull_secret(self):
        """
        User specified pull secret for application container.

        Example:
          --setattr=rabbit.mpi.pull_secret=name-of-secret
        """
        return self.get_attribute("pull_secret")

    @property
    def command(self):
        """
        User specified command (tested, this works)!

        Example:
          --setattr=rabbit.mpi.command='lmp -x1 -x2 -x3'
        """
        return self.get_attribute("command")

    @property
    def exclusive(self):
        """
        User requested exclusive nodes

        Example:
          --setattr=rabbit.mpi.exclusive=true
        """
        return self.get_attribute("exclusive") is not None

    def add_flux(self):
        """
        A directive that says "I already have Flux in my container"
        We really only care if this is set to some variant of NO.

        Example:
          --setattr=rabbit.mpi.add_flux=false
        """
        # If we are using default container, we don't add flux
        if self.container == defaults.container:
            return False

        # Nothing set, we assume adding the flux view
        value = self.get_attribute("add_flux")
        if not value:
            return True

        # Otherwise, we only care if it's set to False
        return not self.is_false(value)

    @property
    def interactive(self):
        """
        Determine if the minicluster should be interactive.
        This is based on a command being set or not.
        """
        return self.command is None

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
        return self.get_attribute("tasks") or 0

    @property
    def environment(self):
        """
        Derive the default environment plus whatever extra the user has asked for.

        If these are bad/wrong, we might not want to add by default.

        Example:
          --setattr=rabbit.mpi.env.one=ketchup --setattr=rabbit.mpi.env.two=mustard
        """
        environ = defaults.environment

        # User preferences override
        environ.update(self.get_attribute("env") or {})
        return environ

    @property
    def rabbits(self):
        """
        The user can request specific rabbit names, e.g., a subset.

        Example:
          --setattr=rabbit.mpi.rabbits=hetchy201,hetchy202
        """
        return self.get_attribute("rabbits")

    @property
    def rabbit_mount(self):
        """
        The user can request specific rabbit mount for inside the container

        Example:
          --setattr=rabbit.mpi.rabbit_mount=/mnt/wabbit
        """
        return self.get_attribute("rabbit_mount") or defaults.rabbit_mount

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
