.. _slingshot_interconnect:

######################
Slingshot Interconnect
######################

:term:`CORAL-2` systems use the HPE Cray :term:`Slingshot` Ethernet-compliant
interconnect.  Slingshot consists of :term:`Rosetta` switches and
:term:`Cassini` NICs connected in a :term:`dragonfly` topology.

The HPE-provided Slingshot software includes the *Slingshot Fabric Manager*
and *Slingshot Host Software* products.
The *Slingshot Host Software* is open source and includes:

.. list-table::
   :header-rows: 0

   * - kfabric and kfi_cxi provider
     - The kernel API [#kfabric]_ for Slingshot.
       Example user: Lustre kfilnd [#horn2023]_.

   * - cxi_ss1
     - The kernel device driver [#cxi-driver]_ for the NIC.

   * - libcxi
     - The user space API [#libcxi]_ for the NIC device driver.

   * - libfabric and fi_cxi provider
     - The user space API [#libfabric]_ for Slingshot.
       Example user: Cray :term:`MPICH`.

Although Flux was made capable of launching Cray MPICH applications that
use the interconnect early on without any specific Slingshot support,
advanced capabilities such as :term:`VNI` tagging, NIC resource management,
and hardware collective offload require specialized Slingshot support from
Flux, described here.

.. warning::

  As of Sept 2025, the Hardware Collective offload section is a preliminary
  design without an implementation.  The design still needs some details
  worked out.

***********
VNI Tagging
***********

VNI tagging is a mechanism for isolating application RDMA traffic, enforced
at the NIC level.  A VNI tag is an integer value stamped on each RDMA message.
A user may only send or receive messages with a given VNI tag if the local
NIC driver has allocated a :term:`CXI service` (a privileged operation) that
grants that user access to that VNI.  The user presents the CXI service id
to the driver when requesting direct access to hardware resources for RDMA.

VNI tagging support in Flux is implemented as a two step process.  First the
system allocates a set of unique VNIs to the job, then a CXI service is
created on each NIC that authorizes the job to send and receive messages
using the reserved VNIs.

.. note::

   When Flux VNI tagging is not enabled, applications fall back to a default
   CXI service that grants them access to two default VNIs (1 and 10).
   Use of these shared VNIs make applications vulnerable to message injection
   attacks from other users.  Now that Flux supports VNI tagging, the default
   CXI service should be disabled as recommended by HPE [#ssops2024]_.

VNI Reservation
===============

VNI numbers range from 0 to 65535 with 1 and 10 reserved as defaults.
Flux may be configured to use any range, typically 1024-65535.

Flux reserves unique VNIs (typically one) for each job at the Flux system
instance level when it enters RUN state.  Since only the Flux system instance
can spawn jobs as other users, allocating each system instance job a unique VNI
effectively isolates users from each other.  Jobs launched in Flux
sub-instances share the parent job's VNI and have no isolation from each other.

.. note::

  In contrast, Slurm [#slurmplug]_ allocates a block of VNIs to each job and
  isolates job steps from one another.  This confers no security advantage
  but does allow NIC resources to be managed among steps.  Implementing this
  in Flux is possible but not currently planned due to the extra challenges
  presented by the lack of coupling within the Flux instance hierarchy
  and lack of privileged capability in Flux sub-instances.

When a job enters CLEANUP state, all CXI service allocations for the job's
reserved VNIs are destroyed and the job's VNI reservation is released and may
be reused.

CXI Service Allocation
======================

When a job in the Flux system instance enters RUN state, the VNI reservation
is retrieved and CXI services are allocated on each node, one for each NIC.
The CXI service authorizes only the job owner to use the job's reserved VNI.
The job shell then passes the CXI service information to libfabric [#fi_cxi]_
via these environment variables:

.. envvar:: SLINGSHOT_VNIS

   Comma-separated list of VNI numbers the job can use.

.. envvar:: SLINGSHOT_DEVICES

   Comma separated list of local NICs the job can use.  Flux always assigns
   all available NICs.  Note that since nodes may have different numbers
   of operational NICs, this environment variable may have different values
   on different nodes of the job.

.. envvar:: SLINGSHOT_SVC_IDS

   Comma-separated list of CXI service IDs the job can use, corresponding to
   the :envvar:`SLINGSHOT_DEVICES` list.  Note that since
   CXI services are allocated through the local NIC, this environment variable
   may have different values on different nodes of the job.

Example::

   SLINGSHOT_VNIS=4034
   SLINGSHOT_DEVICES=cxi0,cxi1,cxi2,cxi3
   SLINGSHOT_SVC_IDS=11,11,12,11

When the job is a Flux instance, these environment variables are captured on
each node so that the sub-instance can pass them through to its jobs, and so on
if there are more Flux instance levels.

When the system instance job enters CLEANUP state, all CXI services that were
created for the job are destroyed.

Exceptional Conditions
======================

Rarely, CXI service destruction may need to be retried for up to several
minutes while the NIC attempts to complete network operations on behalf of
the CXI service user.  Rather than delay the job from completing CLEANUP state
and releasing its resources, Flux times out the initial destruction quickly
and retries in housekeeping, after the job has entered INACTIVE state.
The implementation must prevent these VNIs from being reused before
destruction is successful.

Failures in VNI reservation causes a fatal job exception to be raised.
For jobs that do not require Slingshot, VNI reservation can be disabled
as a job submission option.

Failure to allocate a CXI service for a reservation causes a fatal job
exception to be raised.

Failure to destroy a lingering CXI service in housekeeping drains the node.

Instance Restart
================

When a Flux system instance restarts, jobs may continue to use VNIs that
were allocated before the restart.  The pool allocation state is persisted
in the KVS across Flux restarts.

Running under Slurm
===================

Inherited VNI reservations and CXI services work the same in a Flux
sub-instance, regardless of whether it was launched by Flux or Slurm.
VNI tagging should thus work the same on *El Capitan*, which runs only
Flux, and *Summit*, when Flux is used as a portable workflow layer under Slurm.

***************
Traffic Classes
***************

Slingshot users can request that messages use a quality of service profile
or :term:`traffic class`.  For example, Cray MPICH users can use
:func:`MPI_Info_set` on the ``traffic_class`` key to assign one to an MPI
communicator.  The available Slingshot traffic classes are described
by Kandalla et al. [#kandalla2023]_ as follows:

TC_BEST_EFFORT
   The Best Effort traffic class is the default shared traffic class and
   provides each application a "fair share" of networking resources within
   the same class.

TC_LOW_LATENCY
   The Low Latency traffic class is best suited for applications that are
   vulnerable to the performance of small message collective operations.
   Such latency sensitive operations are given a higher priority in the
   network and this allows applications to benefit from lower latency and
   potentially lower jitter due to variability in network round trip times.
   However this traffic class is also associated with a specific bandwidth
   cap.

TC_DEDICATED_ACCESS
   The Dedicated Access traffic class allows network packets issued by the
   communications library to benefit from a guaranteed bandwidth allocation.
   This traffic class is ideally used for highly specialized users and very
   high priority jobs that run on production systems.

TC_BULK_DATA
   The Bulk Data traffic class allows for the system fabric to isolate
   I/O traffic from every other type of traffic in the fabric.

The list of traffic classes allowed by the CXI service determines
whether a user request would be honored by the Cassini device driver.
Currently, Flux allows :const:`TC_BEST_EFFORT` and :const:`TC_LOW_LATENCY`.
This is reflected in the job environment:

.. envvar:: SLINGSHOT_TCS

   Bitmask of allowed traffic classes. The bit encoding is
   :const:`DEDICATED ACCESS` (1), :const:`LOW_LATENCY` (2),
   :const:`BULK_DATA` (4), :const:`BEST_EFFORT` (8).  This environment
   variable is interpreted by Cray MPICH.

Example::

   SLINGSHOT_TCS=0x0a

***********************
NIC Resource Management
***********************

Some Cassini NIC resources can be managed using CXI services, so that each
user sharing the NIC can be guaranteed a minimum quantity needed to make
progress and is prevented from starving out other users.

Each resource can be assigned a *reserved* and a *maximum* quantity in the CXI
service.  A user of a CXI service is guaranteed to be able to obtain the
*reserved* quantity of a resource, but cannot exceed the *maximum* quantity.
HPE recommends the following values for each job, with the maximum quantity
fixed and the reserved quantity scaled by the expected number of task ranks
within the job that will share the CXI service on the node.  Since the Flux
system instance that creates the CXI service doesn't know how many task ranks
will be launched on the node by Flux sub-instances, it uses *ncores*, the
number of allocated cores, to calculate the reserved quantities instead.

.. list-table::
   :header-rows: 1

   * - Resource
     - Description
     - Reserved
     - Maximum

   * - TXQs
     - Transmit command queues
     - 2*ncores
     - 2048

   * - TGQs
     - Target command queues
     - 1*ncores
     - 1024

   * - EQs
     - Event queue
     - 2*ncores
     - 2047

   * - CTs
     - Counters
     - 1*ncores
     - 2047

   * - TLEs
     - Trigger list entries
     - 1*ncores
     - 1*ncores (special case)

   * - PTEs
     - Portal table entries
     - 6*ncores
     - 2048

   * - LEs
     - List entries
     - 16*ncores
     - 16384

   * - ACs
     - Addressing contexts
     - 2*ncores
     - 1022

When Flux creates the CXI service, if insufficient NIC resources are available
to fulfill the above quantities, the request is scaled back to fit what is
available and a warning message is printed.

As noted above, a potential issue arises from Flux not subdividing CXI
services for jobs run in Flux sub-instances, such as batch jobs.  Although
the batch job is constrained to its NIC resource allocation, jobs within it
competing for local NIC resources have no protection from each other.

***************************
Hardware Collective Offload
***************************

Slingshot implements hardware collective offload for *barrier*, *broadcast*
(small payload), *reduce*, and *allreduce* MPI operations that may benefit
large applications.  Enabling them requires Flux and the user's application
to interact with the Slingshot :term:`fabric manager` to reserve multicast
addresses and instantiate multicast trees to fit each job.

Multicast address reservations for eligible jobs are allocated and released
(only) by the Flux system instance through fabric manager requests.

Multicast trees are instantiated and destroyed within a reservation by
libfabric-enabled applications, using environment variables set by Flux,
communicating directly with the fabric manager.  These applications may run
at any Flux instance level.

Multicast Address Reservation
=============================

The Flux system instance leader broker logs in to the fabric manager at
startup using credentials that are only available to the ``flux`` system user.
It then makes multicast address reservations for each eligible job that
enters the RUN state according to the system instance configuration.
Configurable parameters include

- The number of multicast addresses to reserve for each job
  (it is not dependent on job size)

- The minimum job size required for automatic reservation.  If not set,
  users must explicitly request to enable hardware collectives for their job.

.. note::

   HPE recommends [#slurmcoll]_ that the number of multicast addresses per
   job be calculated as follows.  If :math:`M` is the total available addresses
   for hardware collectives, :math:`S` is the system size, :math:`s` is the
   minimum job size, and :math:`j` is the number of jobs expected to be sharing
   nodes, then the number of addresses per job is :math:`(M / (S / s)) / j`.

   Using :math:`M = 4086`, :math:`j = 1`, and :math:`s = 64`,
   a system the size of *El Capitan* with :math:`S = 11136` would reserve
   :math:`(4086 / (11136 / 64)) / 1 = 23` multicast addresses per job.

The fabric manager returns a job :class:`sessionToken` for each reservation
that allows the bearer to connect to the fabric manager and create or destroy
multicast trees within the job's reservation.  The job :class:`sessionToken`
becomes part of the address reservation and is set in the job's environment
for use by libfabric and Flux sub-instances.  Note that specific multicast
addresses are not part of the reservation.

When the job enters the CLEANUP state, the Flux system instance requests
that the fabric manager destroy any remaining multicast trees and release
the address reservation.

Multicast Tree Instantiation
============================

Multicast trees are instantiated by libfabric using the following information
set in the environment:

.. envvar:: FI_CXI_HWCOLL_MIN_NODES

   The configured minimum job size.

.. envvar:: FI_CXI_HWCOLL_ADDRS_PER_JOB

   The configured number of multicast addresses allocated to each job.

.. envvar:: FI_CXI_COLL_JOB_ID

   The :class:`jobID` *string* associated with the multicast address
   reservation.  The reservation is inherited from the enclosing Flux
   instance and may not refer to the current job.

.. envvar:: FI_CXI_COLL_MCAST_TOKEN

   The :class:`sessionToken` *string* associated with the multicast address
   reservation.

.. envvar:: FI_CXI_COLL_FABRIC_MGR_URL

   The fully qualified URL of the fabric manager.

.. envvar:: FI_CXI_COLL_JOB_STEP_ID

   A *string* identifier associated with the *current* job, that is unique
   within the multicast address reservation.  For example, the job id
   path [#jobidpath]_ of the current job.

When the job is a Flux instance, all environment variables but the last
are captured so they can be passed through to its jobs, and so on if there
are more Flux levels.

Multicast Tree Cleanup
======================

Although the libfabric-enabled application instantiates multicast trees
and destroys them on exit, cleanup can be missed if the application aborts.
Multicast trees that are left behind will be cleaned up by the Flux system
instance when the reservation is released, but until then, other sub-instance
jobs may be unable to instantiate multicast trees if the reservation is used
up by aborted jobs.

To resolve this, when a job enters CLEANUP state at *any* Flux instance level,
Flux connects to the fabric manager using the :class:`sessionToken` and
deletes all multicast addresses within the reservation that are associated
with the job identifier that was used for :envvar:`FI_CXI_COLL_JOB_STEP_ID`.

Exception Handling
==================

If the system instance leader broker's connection to the fabric manager
is interrupted, fabric manager operations are paused while the system
instance reconnects.

Since jobs can trivially fall back to the unassisted collectives
implementation, reservation requests to the fabric manager that take too
long may be timed out quickly and treated as a non-fatal error by the job.

Requests by the system instance leader broker to the fabric manager to
release reservations for jobs in CLEANUP state execute asynchronously
so the job's transition to INACTIVE is not delayed by a slow fabric manager.
If the fabric manager connection is lost, on reconnect, any reservations
for INACTIVE jobs are discovered and released.

Requests by Flux sub-instances to the fabric manager to release reservations
using the :class:`sessionToken` are also asynchronous, under timeout, and
treated as non-fatal to the job.

Flux Instance Restart
=====================

Upon restart, the Flux system instance reloads reservation state from the
KVS that was saved at shutdown.  It then re-connects to the fabric manager.
If an active reservation has disappeared from the fabric manager, a
fatal job exception is raised.  Any reservations for INACTIVE jobs are
discovered and released.

Running under Slurm
===================

Inherited multicast address reservations and multicast tree cleanup
using the :class:`sessionToken` work the same in a Flux sub-instance,
regardless of whether it was launched by Flux or Slurm.

**************
Implementation
**************

Phase I: Interfacing with the NIC
=================================

The first phase of implementation covers VNI tagging, traffic classes,
and NIC resource management.  Several Flux components work together to
this phase:

jobtap plugin
  The cray-slingshot jobtap plugin is loaded only in the Flux system
  instance. It manages a configurable pool of VNI numbers and creates
  VNI reservations for jobs when they enter the RUN state.  Reservations
  are posted to the job eventlog as a `cray-slingshot` event, e.g.

  .. code:: json

    {
      "timestamp": 1751386927.8443174,
      "name": "cray-slingshot",
      "context": {
        "reservation": { "vnis": [ 1024 ] }
      }
    }

  Jobs that do not use slingshot can specify the ``cray-slingshot=off``
  shell option to suppress the reservation.  Jobs that want more than one
  VNI may use ``cray-slingshot.vnicount=N`` to request up to four, which
  is maximum that may be associated with one CXI service.

  The plugin releases reservations when the job enters CLEANUP state.
  To keep the initial implementation simple, yet make it unlikely that
  a VNI could be reused before CXI services are cleaned up, VNI numbers
  are allocated round-robin from the pool.

  When the instance restarts, the jobtap plugin recovers the state of
  the VNI pool as the job eventlogs are replayed.

prolog
  CXI service allocation is a root-only operation.  In the Flux system
  instance, the job prolog invokes :option:`flux-slingshot prolog` on each
  allocated node, which retrieves the reservation from the job eventlog
  and allocates CXI services on each Slingshot NIC.  The CXI services
  restrict access to the job owner, VNIs to the reserved VNI numbers,
  traffic classes to :const:`TC_BEST_EFFORT` and :const:`TC_LOW_LATENCY`,
  and resources to the HPE recommended values scaled by *ncores*.

shell plugin
  The cray-slingshot shell plugin is responsible for setting up the
  environment to enable libfabric-enabled applications to use Slingshot.
  There are three modes:

  #. In the Flux system instance, it fetches the reservation from the job
     eventlog, then finds matching CXI services on each Slingshot NIC.

  #. In a Flux sub-instance, it asks the broker on the local node for
     the Slingshot environment variables to pass along to the job.

  #. If there is no reservation and no inheritable environment, it
     clears the Slingshot environment so that libfabric-enabled applications
     will try to use the default CXI service.

epilog
  CXI service destruction is a root-only operation.  In the Flux system
  instance, the job epilog invokes :option:`flux-slingshot epilog`
  on each allocated node, which retrieves the reservation from the job
  eventlog and destroys matching CXI services on each Slingshot NIC.
  Failure to remove a matching CXI service at this phase results in a
  warning but does not cause the job to fail.

housekeeping
  Housekeeping again invokes :option:`flux-slingshot epilog`, but with
  an option to retry CXI service destruction for a longer period of time.
  If CXI services cannot be destroyed, the node is drained.

  In addition to cleaning up after the current job, housekeeping may invoke
  :option:`flux-slingshot clean --all` to remove all user CXI services from
  the node.  This may be useful as an extra precaution on node-scheduled
  systems like *El Capitan*, in case CXI services were left on the NIC by
  another job that Flux was unable to clean up, for example if Flux was
  not running.

Example 1
---------

An MPI program is run directly in the Flux system instance:

.. code::

  $ flux run -N2 ./mpi-hello

#. The jobtap plugin on rank 0 sees the transition of the job to RUN state
   and posts a VNI reservation to the job eventlog before the ``start`` event.

#. The prolog script calls :option:`flux-slingshot prolog`, which fetches
   the reservation and creates matching CXI services on each Slingshot NIC.

#. The job shell plugin fetches the reservation, then queries each Slingshot
   NIC for matching CXI services.  The job tasks are launched with the
   appropriate Slingshot environment.

#. The job transitions to CLEANUP state.

#. The epilog script calls :option:`flux-slingshot epilog`,
   which fetches the reservation and destroys matching CXI services on
   each Slingshot NIC.  Any retries are deferred to housekeeping so the
   job's resources can be returned to the scheduler.

#. In parallel with the previous step, the jobtap plugin on rank 0 releases
   the reservation.

#. The housekeeping script calls :option:`flux-slingshot epilog --timeout=5m`,
   which fetches the reservation and destroys matching CXI services on
   each Slingshot NIC. Recalcitrant CXI services cause the node to be
   drained after the timeout expires.

Example 2
---------

An MPI program is run in a batch sub-instance:

.. code::

  $ flux batch -N2 --wrap flux run -N2 ./mpi-hello

The sequence in Example 1 is followed, except the "job" is a Flux sub-instance.
Within the sub-instance the following occurs:

#. At startup, the shell plugin on each rank reads the Slingshot environment
   variables from the local broker environment and creates an inherited reservation
   that will be re-used for all jobs.

That's it.  The broker module acts independently on each rank using only
the information that it received from the local environment.  There is no
prolog or housekeeping.


Phase II: Interfacing with the Fabric Manager
=============================================

The second phase of implementation enables hardware collective offload,
building on the infrastructure created in Phase II.

TODO

.. rubric:: References

.. [#kfabric] https://github.com/HewlettPackard/shs-kfabric

.. [#horn2023] `Kfabric Lustre Network Driver, Horn et al., CUG, May 2023 <https://cug.org/proceedings/cug2023_proceedings/includes/files/pres119s2.pdf>`_

.. [#cxi-driver] https://github.com/HewlettPackard/shs-cxi-driver

.. [#libcxi] https://github.com/HewlettPackard/shs-libcxi

.. [#libfabric] https://github.com/HewlettPackard/shs-libfabric

.. [#fi_cxi] `fi_cxi(7) - The fi_cxi fabric provider fi_cxi <https://ofiwg.github.io/libfabric/v1.21.1/man/fi_cxi.7.html>`_

.. [#slurmplug] *Slurm Slingshot Plugin Design*, internal HPE document,
   received May 2025.

.. [#ssops2024] Section 6.3, `HPE Slingshot Operations Guide 2.1.3 S-9000, Aug 2024 <https://support.hpe.com/hpesc/public/docDisplay?docId=dp00004990en_us>`_

.. [#kandalla2023] Section III.B, `Designing the HPE Cray Message Passing Toolkit Software Stack for HPE Cray EX Supercomputers, Kandalla et al., CUG, 2023 <https://cug.org/proceedings/cug2023_proceedings/includes/files/pap144s2-file1.pdf>`_

.. [#slurmcoll] *Slurm Slingshot Collectives Design*, internal HPE document,
   received May 2025.

.. [#jobidpath] `flux-core github issue #6876: need unique identifier for jobs run at any level on a system <https://github.com/flux-framework/flux-core/issues/6876>`_
