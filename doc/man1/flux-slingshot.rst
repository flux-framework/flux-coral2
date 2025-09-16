=================
flux-slingshot(1)
=================

DESCRIPTION
===========

| **flux** **slingshot** **list** [*--no-header*] [*--max*]
| **flux** **slingshot** **jobinfo** [*--jobid=ID*]
| **flux** **slingshot** **prolog** [*--dry-run*] [*--userid=UID*] [*--jobid=ID*]
| **flux** **slingshot** **epilog** [*--dry-run*] [*--userid=UID*] [*--jobid=ID*] [*--retry-busy=FSD*]
| **flux** **slingshot** **clean** [*--dry-run*] [*--retry-busy=FSD*]

DESCRIPTION
===========

:program:`flux-slingshot` is a utility for manipulating HPE Cray Slingshot
CXI services on behalf of Flux.  For more detail on Slingshot integration
with Flux, refer to the
:ref:`Slingshot Interconnect <slingshot_interconnect>` design document
on the Flux CORAL2 documentation page referenced below.

COMMANDS
========

Several sub-commands are available.

list
----

.. program:: flux slingshot list

List the :term:`CXI service` allocations active across all Slingshot NICs on
the local node.  Services that are identical on multiple NICs are combined
and displayed on one line with the NIC device names in RFC 29 hostlist format.

CXI service IDs suffixed with ``/sys`` are system services.

CXI service IDs suffixed with a minus sign ``-`` are disabled.

The following sub-command options are available:

.. option:: --max

Show maximum resource quantities rather than reserved quantities.

.. option:: -n, --no-header

Suppress printing of column headings.

jobinfo
-------

.. program:: flux slingshot jobinfo

List the VNI reservation for a job, in JSON form.  The reservation is
obtained from the ``cray-slingshot`` job event posted to the job eventlog
by a jobtap plugin when the job enters RUN state.

The following sub-command options are available:

.. option:: -j, --jobid=ID

Specify which job to query.  By default the value of the :envvar:`FLUX_JOB_ID`
environment variable is used.

prolog
------

Read the VNI reservation for a job and allocate CXI services for each NIC
on the local node.  This is a privileged operation.

The following sub-command options are available:

.. option:: -j, --jobid=ID

Specify which job to query.  By default the value of the :envvar:`FLUX_JOB_ID`
environment variable is used.

.. option:: -u, --userid=UID

Specify the job user ID.  By default the value of :envvar:`FLUX_JOB_USERID` is
used.

.. option:: --dry-run

List the CXI services that would be created but take no action.

epilog
------

Read the VNI reservation for a job and remove matching CXI services for
each NIC on the local node.  This is a privileged operation.

A CXI service matches the reservation if the VNIS and user access restrictions
match, and it is not a system service.

The following sub-command options are available:

.. option:: -j, --jobid=ID

Specify which job to query.  By default the value of the :envvar:`FLUX_JOB_ID`
environment variable is used.

.. option:: -u, --userid=UID

Specify the job user ID.  By default the value of :envvar:`FLUX_JOB_USERID` is
used.

.. option:: ---retry-busy=FSD

If CXI service removal fails with EBUSY, sleep for one second then retry,
for up to the specified duration.  The duration is specified in RFC 23
Flux Standard Duration.

.. option:: --dry-run

List the CXI services that would be removed but take no action.

clean
-----

Remove all non-system CXI services that have VNI restrictions matching
Flux's VNI pool.  This is a privileged operation.

The following sub-command options are available:

.. option:: ---retry-busy=FSD

If CXI service removal fails with EBUSY, sleep for one second then retry,
for up to the specified duration.  The duration is specified in RFC 23
Flux Standard Duration.

.. option:: --dry-run

List the CXI services that would be removed but take no action.


SEE ALSO
========

:man1:`flux-shell-cray-slingshot`

Flux CORAL2 Documentation:
https://flux-framework.readthedocs.io/projects/flux-coral2
