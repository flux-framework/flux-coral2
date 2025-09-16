========================
flux-config-slingshot(5)
========================


DESCRIPTION
===========

Flux system instance configuration is needed to enable advanced HPE Cray
:term:`Slingshot` high speed interconnect support in Flux.  No configuration
is necessary in Flux sub-instances.

For more detail on Slingshot integration with Flux, refer to the
:ref:`Slingshot Interconnect <slingshot_interconnect>` design document
on the Flux CORAL2 documentation page referenced below.

COMPONENTS
==========

The `cray-slingshot.so` jobtap plugin must be loaded in the leader broker
of the Flux system instance.  It manages a pool of :term:`VNI` numbers
that Flux assigns to jobs.

Prolog, epilog, and housekeeping scripts, provided by the flux-coral2 package,
automatically run during those phases of a job.  The scripts allocate and
remove :term:`CXI services <CXI service>` on the NICs, essential functions
for Slingshot device management, but are disabled by default and must be
explicitly enabled by configuration.

A `cray-slingshot` shell plugin, responsible for managing the Slingshot
environment presented to applications, is loaded automatically for each job.

KEYS
====

The following keys are valid in the ``cray-slingshot`` TOML table:

vni-pool
   (optional) An RFC 22 idset string that specifies the pool of VNI numbers
   that the jobtap plugin reserves for jobs.  Valid VNIs are in the range
   of 1 to 65535, with VNI 1 and 10 reserved for the default CXI service.
   Default: ``"1024-65535"``.

vnis-per-job
   (optional) An integer value with a valid range of 0 through 4.
   At this time, nothing makes use of multiple VNIs in Flux.  Default: ``1``.

vni-reserve-fatal
   (optional) A boolean value that defines what happens when a VNI
   reservation cannot be created for a job.  If true, the job receives a
   fatal exception.  If false, the job gets an empty VNI reservation.
   Default: ``true``

cxi-enable
   (optional) A boolean value that enables prolog/epilog/housekeeping scripts
   to manage CXI services on behalf of Flux.  Default: ``false``

SECURITY NOTE
=============

VNI tagging, a Slingshot feature for isolating RDMA traffic and protecting
users from message injection attacks, is recommended by HPE.  If Slingshot
support is not enabled, applications using Slingshot must share the default
CXI service, which is insecure.

Sites are therefore encouraged to enable VNI tagging support in Flux.

EXAMPLE
=======

::

   [job-manager]
   plugins = [
     { load = "cray-slingshot.so" }
   ]

   # Default values are commented out
   [cray-slingshot]
   #vni-pool = "1024-65535"
   #vnis-per-job = 1
   #vni-reserve-fatal = true
   cxi-enable = true


SEE ALSO
========

:man1:`flux-slingshot`, :man1:`flux-shell-cray-slingshot`,
:core:man5:`flux-config`, :core:man5:`flux-config-job-manager`

Flux CORAL2 Documentation:
https://flux-framework.readthedocs.io/projects/flux-coral2
