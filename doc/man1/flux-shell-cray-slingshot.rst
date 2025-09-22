============================
flux-shell-cray-slingshot(1)
============================

DESCRIPTION
===========

**flux** **run** *-o cray-slingshot[OPTS]*

DESCRIPTION
===========

:program:`cray-slingshot` is a :core:man1:`flux-shell` plugin that configures
the environment for applications that use the HPE Cray :term:`Slingshot`
high speed interconnect.  The environment variables managed by this plugin are
:envvar:`SLINGSHOT_VNIS`, :envvar:`SLINGSHOT_DEVICES`,
:envvar:`SLINGSHOT_SVC_IDS`, and :envvar:`SLINGSHOT_TCS`.  For more detail
on Slingshot integration with Flux, refer to the
:ref:`Slingshot Interconnect <slingshot_interconnect>` design document
on the Flux CORAL2 documentation page referenced below.

When flux-coral2 is installed on a system, the plugin is enabled by default.

The plugin operates in three possible modes:

Reservation
  Jobs launched directly by a Flux system instance, including batch and alloc
  Flux sub-instances, are assigned a :term:`VNI` reservation when they enter
  RUN state.  :term:`CXI services <CXI service>` are allocated on the
  :term:`Cassini` NICs prior to task launch.  The CXI services, which are
  only usable by the job owner, permit access to the reserved VNI, NIC
  resources such as transmit and receive queues, and a set of
  :term:`traffic class` options.

Inherit
  Jobs launched by a Flux sub-instance inherit the Slingshot environment from
  the enclosing instance.  Inheritance also works if the Flux instance is
  launched by a foreign resource manager that supports Slingshot, such as Slurm.
  Flux sub-instances do not further subdivide or isolate Slingshot resources
  for their jobs.  Inheritance propagates to any Flux instance depth.

Default
  If neither reservation nor inheritance are available, the Slingshot
  environment is cleared.  Applications that need the high speed interconnect
  will attempt to use the default CXI service.

SHELL OPTIONS
=============

.. option:: cray-slingshot=off

  Disable the shell plugin and suppress VNI allocation and CXI service
  creation.  This reduces the job's startup overhead slightly.  However,
  note that this completely disengages the shell plugin and could allow
  the Slingshot environment to propagate to tasks from the job submission
  environment, confusing applications.  It is advisable to prevent this,
  e.g.::

    flux batch -o cray-slingshot=off --env=-SLINGSHOT_* ...

.. option:: cray-slingshot.vnicount=N

  Request more than one VNI (up to four).  Additional VNIs are ignored by
  the Cray application stack at this time so this option is not recommended.


SEE ALSO
========

:core:man1:`flux-submit`, :core:man1:`flux-shell`, :man1:`flux-shell-cray-pals`

Flux CORAL2 Documentation:
https://flux-framework.readthedocs.io/projects/flux-coral2
