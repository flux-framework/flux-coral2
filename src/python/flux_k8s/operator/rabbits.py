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
            "devices": {"hostPath": defaults.device_path, "path": defaults.device_path},
            "net": {"hostPath": defaults.net_path, "path": defaults.net_path},
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
