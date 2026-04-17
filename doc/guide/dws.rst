.. _dws_rabbit_storage:

##########################
Rabbit Near-Node Storage
##########################

:term:`CORAL-2` systems at LLNL include HPE Rabbit near-node flash (:term:`NNF`)
storage nodes.  Each Rabbit is a storage appliance connected over PCIe to a
small set of compute nodes (one Rabbit per chassis on El Capitan).  Rabbit
storage is managed by HPE's *Data Workflow Services* (:term:`DWS`)
[#dws]_ [#nnfsos]_, a set of Kubernetes controllers and :term:`CRDs <CRD>` that govern
the full lifecycle of a storage allocation: creation, mounting, data
movement, unmounting, and teardown.

Flux exposes Rabbit storage to users through ``#DW`` job directives
(see :ref:`rabbit` for the user guide).  This document describes how the
integration works internally.

**********
Background
**********

DWS represents a storage allocation as a *Workflow* Kubernetes custom
resource.  The Workflow object encodes the user's ``#DW`` directives and
moves through a series of states under the control of two parties:

- The *workload manager* — Flux, in this case — drives the Workflow
  forward by patching its ``spec.desiredState`` field.

- The *DWS controllers* on the management cluster do the actual work (creating
  file systems, mounting, moving data, tearing down) and signal completion by
  advancing ``status.state`` to match ``spec.desiredState``.

Flux waits for ``status.state`` to equal ``spec.desiredState`` before
advancing to the next state.

**********
Components
**********

Four software components implement the Flux–DWS integration.

dws-jobtap.so
  A C Flux jobtap plugin loaded in the job manager of the system instance.
  It intercepts job lifecycle events (submission, allocation, run, cleanup,
  exceptions) and drives the per-job state machine by sending RPCs to the
  ``dws`` service.  It also exposes an RPC service under
  ``job-manager.dws.*`` for callbacks from ``coral2_dws``, and holds jobs in
  prolog and epilog actions while DWS does its work, preventing jobs from
  running before storage is ready and from finishing before storage is cleaned
  up.

coral2_dws (flux-coral2-dws systemd service)
  A Python process running alongside the rank-0 broker.  It owns the
  connection to the Kubernetes API server and does everything that requires
  k8s access: creating and deleting Workflow CRD objects, watching for state
  changes, computing resource allocations from DirectiveBreakdown CRDs,
  patching jobspecs, and communicating timing data to the job KVS.  It
  exposes an RPC service under ``dws.*`` that the jobtap plugin calls.

flux_k8s Python package
  A library bundled with ``coral2_dws`` that provides higher-level
  abstractions: :class:`~flux_k8s.workflow.WorkflowInfo` (per-job state
  tracking), :class:`~flux_k8s.storage.RabbitManager` (cluster-wide rabbit
  health and allocation tracking), :class:`~flux_k8s.watch.Watchers` (k8s
  watch loops), :mod:`flux_k8s.directivebreakdown` (resource allocation from
  DWS breakdown objects), :mod:`flux_k8s.systemstatus` (propagating DWS
  system health into Flux), and :mod:`flux_k8s.cleanup` (workflow deletion
  helpers).

dws_environment.so
  A Flux shell plugin that reads the ``dws_environment`` event posted to
  the job eventlog at prolog completion and injects the DWS-supplied
  environment variables (e.g. ``$DW_JOB_*`` mount paths) into the job
  shell.

***********************
Workflow State Machine
***********************

A DWS Workflow object progresses through seven named states.  Flux drives
each transition by writing to ``spec.desiredState``; DWS confirms completion
by setting ``status.state`` to the same value.  ``coral2_dws`` watches the
Workflow CRD stream and reacts to each completion event.

.. code-block:: text

                ┌──────────┐
                │ Proposal │  ← Flux creates Workflow here
                └────┬─────┘
                     │ DWS validates directives, issues DirectiveBreakdowns
                     ▼
                ┌──────────┐
                │  Setup   │  ← Flux writes R (resource assignment) to Computes
                └────┬─────┘
                     │ DWS creates file systems on rabbits
                     ▼
                ┌──────────┐
                │  DataIn  │  ← copy_in data movement (if requested)
                └────┬─────┘
                     │
                     ▼
                ┌──────────┐
                │  PreRun  │  ← compute nodes mount file systems
                └────┬─────┘
                     │ Flux releases dws-setup prolog; job starts
                     ▼
                 JOB RUNS
                     │ job enters CLEANUP
                     ▼
                ┌──────────┐
                │ PostRun  │  ← compute nodes unmount file systems
                └────┬─────┘
                     │
                     ▼
                ┌──────────┐
                │ DataOut  │  ← copy_out data movement (if requested)
                └────┬─────┘
                     │
                     ▼
                ┌──────────┐
                │ Teardown │  ← DWS destroys file systems and frees resources
                └────┬─────┘
                     │ Flux releases dws-epilog epilog; job finishes
                     ▼
                  INACTIVE

On exception, the workflow skips directly to Teardown from whatever state
it is currently in (see `Error Handling`_ below).

Proposal
========

The Proposal state is the first state of a Workflow.  Flux creates the
Workflow object with ``spec.desiredState = Proposal`` during the job's
DEPEND phase (:doc:`rfc:spec_21`).  The DWS controller validates the
``#DW`` directives and creates one DirectiveBreakdown CRD per directive,
each describing the storage resources required (which rabbits, how much
capacity, what file system type).

``coral2_dws`` detects Proposal completion via the k8s watch stream.  It
reads the DirectiveBreakdown objects, calls
:func:`~flux_k8s.directivebreakdown.apply_breakdowns` to compute which
rabbits satisfy the request, and patches the jobspec ``resources`` field
(:doc:`rfc:spec_25`) to include the required rabbit resources.  It then
sends a ``job-manager.dws.resource-update`` RPC to the jobtap plugin, which removes
the ``dws-create`` dependency (:doc:`rfc:spec_26`) and allows the job to
be scheduled.

For example, a job requesting 2 nodes with ``#DW jobdw type=xfs capacity=10GiB``
starts with a ``resources`` section like:

.. code-block:: json

   [
     {
       "type": "node",
       "count": 2,
       "with": [
         {
           "type": "slot",
           "count": 1,
           "label": "task",
           "with": [{"type": "core", "count": 1}]
         }
       ]
     }
   ]

After :func:`~flux_k8s.directivebreakdown.apply_breakdowns`, the node entry
is wrapped in a ``rabbit``-labeled slot and an ``ssd`` resource is added:

.. code-block:: json

   [
     {
       "type": "slot",
       "count": 2,
       "label": "rabbit",
       "with": [
         {
           "type": "node",
           "count": 1,
           "with": [
             {
               "type": "slot",
               "count": 1,
               "label": "task",
               "with": [{"type": "core", "count": 1}]
             }
           ]
         },
         {"type": "ssd", "count": 10, "exclusive": true}
       ]
     }
   ]

The ``ssd`` ``count`` field is the requested capacity in GiB.  Each ssd
vertex in Fluxion's resource graph represents ``total_capacity /
chunks_per_nnf`` GiB; Fluxion allocates as many vertices as needed to
satisfy the request (see :man1:`flux-dws2jgf`).  The ``rabbit``-labeled
slot binds each group of compute nodes to their associated rabbit chassis
for co-scheduling.  The rabbit node itself is not scheduled as a compute
resource.

During Proposal, constraints are also added to the job to steer the
scheduler away from compute nodes whose connected rabbits are marked offline
(see `Resource Scheduling Integration`_).

Setup
=====

After the scheduler assigns compute nodes to the job, ``dws-jobtap``
intercepts the transition to RUN state and starts a ``dws-setup`` prolog
action, holding the job there.  It fetches the resource assignment *R*
(:doc:`rfc:spec_20`) from the KVS and sends a ``dws.setup`` RPC to
``coral2_dws`` with the compute hostlist and a per-rabbit node count.

``coral2_dws.setup_cb()`` patches the Workflow's Computes resource with
the list of assigned compute node hostnames (excluding any nodes whose
rabbits failed during Proposal), then sets
``spec.desiredState = Setup``.  The DWS controller creates the requested
file systems on each rabbit.

Setup completion is detected by the k8s watch.  ``coral2_dws`` then sets
``spec.desiredState = DataIn`` and saves the Setup elapsed time to the job
KVS as ``rabbit_setup_timing``.

DataIn
======

DataIn handles ``copy_in`` data movement [#dm]_ — copying data from a
global file system (e.g. Lustre) onto the rabbit before the job runs.  The
transition is driven by DWS; Flux simply advances
``spec.desiredState = DataIn`` when Setup completes and then waits.

If no ``copy_in`` directives were provided, DWS completes DataIn almost
immediately.  On completion, ``coral2_dws`` sets
``spec.desiredState = PreRun``, saves ``rabbit_datain_timing`` to the job
KVS, and optionally starts a prerun timeout timer.

PreRun
======

PreRun is when compute nodes mount the rabbit file systems.  The
``nnf-clientmount`` [#clientmount]_ systemd service on each compute node
is responsible for performing the mount.  The ``zstop_nnf_clientmount.sh``
prolog script ensures ``nnf-clientmount`` is running (starting it if
needed) and then waits for the ``dws_environment`` event to appear in the
job eventlog, blocking the prolog until mounts are confirmed ready.  After
the event arrives, the prolog script stops ``nnf-clientmount`` to reset the
unit state; the mounts themselves persist as kernel mounts independent of
the service.

``coral2_dws`` watches for PreRun completion via the k8s Workflow stream.
When ``status.state = PreRun`` and ``status.ready = true``, it fetches the
DWS-provided environment variables (``$DW_JOB_*`` paths) from the Workflow
status, then sends a ``job-manager.dws.prolog-remove`` RPC carrying those variables to
``dws-jobtap``.

The jobtap plugin posts a ``dws_environment`` event to the job eventlog
(which ``dws_environment.so`` reads to set up the environment) and then
releases the ``dws-setup`` prolog, allowing the job to enter RUN state.

PostRun
=======

When the job finishes and enters CLEANUP state, ``dws-jobtap`` starts a
``dws-epilog`` epilog action, holding the job in CLEANUP.  It sends a
``dws.post_run`` RPC to ``coral2_dws``.

``coral2_dws.post_run_cb()`` sets ``spec.desiredState = PostRun``, which
causes the DWS controller to initiate unmounting by updating the ClientMount
resources on each compute node.  The ``start_nnf_clientmount.sh`` epilog
script starts ``nnf-clientmount`` on each compute node to ensure the service
is running and able to act on those ClientMount instructions;
``nnf-clientmount`` is what performs the actual unmounts.

On PostRun completion, ``coral2_dws`` sets
``spec.desiredState = DataOut`` and saves ``rabbit_postrun_timing``.

.. note::

   If a job was cancelled before it entered RUN state (i.e. it never
   actually ran), ``coral2_dws.post_run_cb()`` skips PostRun and DataOut
   and moves the Workflow directly to Teardown.

DataOut
=======

DataOut handles ``copy_out`` data movement — copying results from rabbit
back to a global file system after the job finishes.  As with DataIn,
if no ``copy_out`` directives were provided this completes immediately.

On DataOut completion, ``coral2_dws`` calls
:meth:`~flux_k8s.workflow.WorkflowInfo.move_to_teardown`, which saves the
current workflow state
and timing to the job KVS, then patches ``spec.desiredState = Teardown``.

Teardown
========

In Teardown, DWS destroys the file systems on the rabbits and frees all
storage resources.  ``coral2_dws`` removes a Kubernetes :term:`finalizer` from the
Workflow object as soon as Teardown begins (to allow the object to be
garbage-collected), and sends a ``job-manager.dws.epilog-remove`` RPC to ``dws-jobtap``
once Teardown is complete.  The jobtap plugin releases the ``dws-epilog``
epilog, allowing the job to proceed to INACTIVE.

After sending the epilog-remove RPC, ``coral2_dws`` marks the rabbits used
by the job as free in :class:`~flux_k8s.storage.RabbitManager`, saves final
timing data, and deletes
the Workflow CRD object from Kubernetes.

TransientCondition
==================

DWS may set ``status.status = TransientCondition`` on a Workflow when it
encounters a problem that may resolve itself (e.g. a transient mount failure).
``coral2_dws`` tracks the time a Workflow first enters TransientCondition.
If the condition persists longer than ``rabbit.tc_timeout`` seconds
(default: 10 s), ``kill_workflows_in_tc()`` raises a fatal exception for
the job, which triggers the exception path and moves the Workflow to
Teardown.

*************
RPC Interface
*************

``dws-jobtap`` and ``coral2_dws`` communicate exclusively through Flux RPCs.
All fields are required unless marked optional.

.. object:: dws.create

   Job entered DEPEND state with a ``#DW`` directive; ``coral2_dws`` creates
   the Workflow CRD and adds a ``dws-create`` dependency to hold the job.

   jobid (integer)
      Flux job ID.

   userid (integer)
      UID of the job owner.

   dw_directives (array)
      List of ``#DW`` directive strings from the jobspec.

   resources (object)
      Jobspec ``resources`` field.

   failure_tolerance (integer)
      Number of rabbit failures to tolerate before raising a job exception.

.. object:: dws.setup

   Job was allocated compute nodes; jobtap started a prolog and sends the
   resource assignment *R*.

   jobid (integer)
      Flux job ID.

   R (object)
      Resource assignment (:doc:`rfc:spec_20`) from the KVS, used to
      determine which rabbits and compute nodes were allocated.

.. object:: dws.post_run

   Job entered CLEANUP state; jobtap started an epilog to hold it there.

   jobid (integer)
      Flux job ID.

   run_started (boolean)
      True if the job reached RUN state; false if it was cancelled before
      running (in which case ``coral2_dws`` skips PostRun and DataOut).

.. object:: dws.teardown

   A job exception occurred during the normal epilog path; ``coral2_dws``
   moves the Workflow to Teardown.

   jobid (integer)
      Flux job ID.

.. object:: dws.abort

   The ``epilog-timeout`` expired (``dws-epilog-timeout`` exception);
   ``coral2_dws`` queries for active mounts, drains affected compute nodes,
   and disables rabbits with active allocations, then the epilog is released
   without waiting for Teardown.

   jobid (integer)
      Flux job ID.

.. object:: job-manager.dws.resource-update

   Proposal state completed; ``coral2_dws`` sends the updated jobspec
   resources and scheduling constraints so jobtap can remove the
   ``dws-create`` dependency and allow scheduling to proceed.

   id (integer)
      Flux job ID.

   resources (object)
      Updated jobspec ``resources`` field reflecting the final rabbit
      assignment.

   exclude (object)
      Scheduling constraints (:doc:`rfc:spec_26`) excluding compute nodes
      whose rabbits failed during Proposal.  May be null.

   errmsg (string, optional)
      Error message set if Proposal failed.

.. object:: job-manager.dws.prolog-remove

   PreRun completed; ``coral2_dws`` sends the DWS-provided environment
   variables so jobtap can post the ``dws_environment`` event and release
   the prolog.

   id (integer)
      Flux job ID.

   variables (object)
      Map of ``$DW_JOB_*`` environment variable names to values.

.. object:: job-manager.dws.epilog-remove

   Teardown completed; jobtap releases the ``dws-epilog`` epilog and allows
   the job to proceed to INACTIVE.

   id (integer)
      Flux job ID.

*********************************
Resource Scheduling Integration
*********************************

Rabbit storage is modeled as a schedulable resource within Fluxion, the
Flux scheduler.

Topology mapping
================

The physical relationship between rabbits and compute nodes is described in
a *rabbitmapping* JSON file generated by :man1:`flux-rabbitmapping` from
the live Kubernetes state.  The mapping records, for each rabbit, the list
of compute nodes connected to it over PCIe.

This file is referenced by ``rabbit.mapping`` in the Flux configuration
and is read at ``coral2_dws`` startup to populate the
``storage.HOSTNAMES_TO_RABBITS`` and ``storage.RABBITS_TO_HOSTLISTS``
dictionaries.


JGF generation
==============

:man1:`flux-dws2jgf` extends the system JGF (JSON Graph Format) resource
graph (:doc:`rfc:spec_20`, :doc:`rfc:spec_40`) to add rabbit storage nodes.
Each rabbit is added to the graph as a chassis vertex, and its storage
capacity is represented as a set of schedulable storage chunks.  The
extended JGF is consumed by Fluxion at startup (via ``resource.scheduling``
in the Flux configuration).

Fluxion must be configured with ``match-format = "rv1"`` (rather than
``rv1_nosched``) so that the scheduling section of the resource assignment
is preserved and available to ``coral2_dws`` for determining which rabbits
were allocated to each job.

DirectiveBreakdown allocation
=============================

After a Workflow completes the Proposal state, DWS creates one
DirectiveBreakdown CRD per ``#DW jobdw`` directive.  Each breakdown
specifies the minimum capacity per rabbit and, for file systems that are
distributed across multiple rabbits (e.g. Lustre), the number of rabbits
required.

:func:`~flux_k8s.directivebreakdown.apply_breakdowns` reads these CRDs and
computes
which of the rabbits allocated to the job by Fluxion should serve each
directive.  It then rewrites the jobspec ``resources`` field to express the
final rabbit assignment, and passes this updated resources field back to
``dws-jobtap`` via the ``job-manager.dws.resource-update`` RPC.

Node exclusion properties
=========================

:class:`~flux_k8s.storage.RabbitManager` monitors the Kubernetes Storage
CRDs that describe each rabbit's health.  When a rabbit reports that a
compute node has lost its PCIe connection to the rabbit, it can set a
``badrabbit``
property on that compute node in Fluxion, causing the scheduler to avoid
it.  This behavior is controlled by the ``rabbit.drain_compute_nodes``
configuration key.

When the Proposal state completes, ``coral2_dws`` adds a scheduling
constraint to the job excluding any compute nodes marked with the
``badrabbit`` property, ensuring the job is not placed on nodes without
functional rabbit access.

**************
Error Handling
**************

The DWS integration includes several mechanisms for handling failures
gracefully.

Workflow errors
===============

If DWS sets ``status.status = Error`` on a Workflow at any point,
``coral2_dws`` raises a fatal exception for the corresponding Flux job.
The exception triggers the jobtap exception callback, which moves the
Workflow to Teardown if it has not already been moved there.

Node failure tolerance
======================

A user may set ``attributes.system.dw_failure_tolerance = N`` in a jobspec
to allow up to *N* nodes to fail rabbit file system creation or mounting
without aborting the job.  When a mount failure is detected,
:meth:`~flux_k8s.workflow.WorkflowInfo.notify_of_node_failure` removes the
affected nodes from
the Workflow's Computes resource (so subsequent mounts are not attempted)
and patches ``spec.forceReady = True`` to tell DWS to proceed without those
nodes.  The failed nodes are drained so they are not re-scheduled until
investigated.

State timeouts
==============

Several per-state timeouts can be configured in the ``[rabbit]`` table
of the Flux TOML configuration (see :man5:`flux-config-rabbit`) to
prevent jobs from hanging indefinitely if DWS stalls.  All timeouts
are optional.

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Config key
     - Effect when timer fires

   * - ``setup_timeout``
     - Job is cancelled; Workflow moves to Teardown.

   * - ``prerun_timeout``
     - Nodes that have not completed mounting are identified; if within
       the failure tolerance they are excluded and the job proceeds,
       otherwise the job is cancelled.

   * - ``postrun_timeout``
     - Workflow is moved to Teardown, abandoning unmounting.

   * - ``teardown_after``
     - Workflow is moved to Teardown after spending too long in PostRun
       or DataOut.

   * - ``tc_timeout``
     - Job is cancelled after its Workflow has been in TransientCondition
       longer than the timeout.

Epilog timeout and abort
========================

The ``epilog-timeout`` option to :man1:`flux-jobtap-dws` is the last
resort for freeing a job stuck in CLEANUP.  When it fires, ``dws-jobtap`` sends a ``dws.abort`` RPC
instead of the normal ``dws.teardown``.  ``coral2_dws.abort_cb()`` queries
Kubernetes for mounts that are still active and drains those compute nodes;
it also disables (via DWS) any rabbits that still have active allocations.
The jobtap epilog is then released immediately, without waiting for DWS to
complete Teardown, so the job can proceed to INACTIVE.

.. note::

  Because the epilog is released before DWS completes cleanup, the rabbit
  resources freed by a timeout may not be immediately available for use by
  new jobs.  Manual intervention (undrain, re-enable) may be required.

**************
Implementation
**************

dws-jobtap.c
============

The jobtap plugin registers callbacks on the following job events:

``job.state.depend``
  ``depend_cb()`` checks whether the jobspec contains a non-empty ``dw``
  attribute.  If so, it adds a ``dws-create`` dependency and sends the
  ``dws.create`` RPC.

``job.state.run``
  ``run_cb()`` starts the ``dws-setup`` prolog and sends the ``dws.setup``
  RPC with the resource assignment *R*.

``job.state.cleanup``
  ``cleanup_cb()`` starts the ``dws-epilog`` epilog and sends the
  ``dws.post_run`` RPC.

``job.event.exception``
  ``exception_cb()`` cleans up any outstanding prolog or epilog and sends
  either ``dws.teardown`` or ``dws.abort`` depending on the exception type.

Inbound RPCs from ``coral2_dws`` are handled by registered message
callbacks:

``job-manager.dws.resource-update``
  Removes the ``dws-create`` dependency and updates the jobspec resources
  and scheduling constraints.

``job-manager.dws.prolog-remove``
  Posts the ``dws_environment`` event to the job eventlog (carrying the
  ``$DW_JOB_*`` environment variables), then releases the ``dws-setup``
  prolog.

``job-manager.dws.epilog-remove``
  Releases the ``dws-epilog`` epilog.

coral2_dws.py
=============

``coral2_dws`` is a Python process driven by the Flux
reactor.  It registers Flux message watchers for each inbound RPC topic and
passes a k8s API client object and :class:`~flux_k8s.storage.RabbitManager`
instance through to each callback as closure arguments.

Kubernetes watches are managed by :class:`~flux_k8s.watch.Watchers`
(``flux_k8s.watch``), which creates a persistent watch on each CRD type and
feeds update events to registered callbacks.  The primary watch is on the
Workflow CRD; the ``workflow_state_change_cb()`` function dispatches to
state-specific logic based on the current ``status.state`` and
``spec.desiredState`` fields.

:class:`~flux_k8s.storage.RabbitManager` (``flux_k8s.storage``) maintains
two levels of state:

- *Cluster-level*: which rabbits exist, which compute nodes they serve, and
  which are currently healthy.  This is updated from the Storage CRD watch.

- *Job-level*: which rabbits are currently allocated to each job.  This
  allows ``coral2_dws`` to free the correct rabbits when a job completes
  and to identify which rabbits to disable during an epilog timeout.

dws_environment.so
==================

The shell plugin registers a callback that fires before the job shell starts
tasks.  It reads the ``dws_environment`` event from the job eventlog (posted
by ``dws-jobtap`` when PreRun completes) and calls ``setenv()`` for each
variable in the event payload.  If the event is not present (e.g. the job
does not use rabbit storage), the plugin does nothing.

.. rubric:: References

.. [#dws] https://github.com/DataWorkflowServices/dws

.. [#nnfsos] https://github.com/NearNodeFlash/nnf-sos

.. [#clientmount] https://github.com/NearNodeFlash/nnf-clientmount

.. [#dm] https://github.com/NearNodeFlash/nnf-dm
