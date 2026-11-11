==========================
flux-rabbit-orphan-scan(1)
==========================


SYNOPSIS
========

**flux** **rabbit-orphan-scan** [*OPTIONS*]


DESCRIPTION
===========

:program:`flux rabbit-orphan-scan` finds orphaned resource state in the
Fluxion scheduler. Orphaned resource state is resource graph data
(allocations, reservations, planner spans, or job tags) that belongs to a
job that is not running. Orphaned state makes resources unavailable, and
jobs that need those resources stay in the SCHED state.

For each of the most recent inactive jobs, plus every running job as a
control, the command asks the ``sched-fluxion-resource`` module which
vertices still hold state for that job, what the module itself believes
the job's status is, and what flux-core believes (eventlog, housekeeping).
It also snapshots everything the module currently reports as allocated or
reserved, so that state owned by jobs outside the scanned window is
accounted for, and dumps the aggregate (pruning) filter counts.

The command reads data only. It does not change the scheduler. Only the
``find``, ``info``, ``params`` and ``stats-get`` RPCs of the resource
module are used.

Two files are written: :option:`--output` *PREFIX* ``.txt`` is a summary
for humans, and *PREFIX* ``.json`` holds all of the collected data for
further processing with tools such as ``jq``.

The command must be run as the owner of a Flux instance that is running
the ``sched-fluxion-resource`` module.


OPTIONS
=======

.. option:: -n, --count=N

  Scan the *N* most recent inactive jobs. All running jobs are always
  scanned. The default is 300.

.. option:: -o, --output=PREFIX

  Write ``PREFIX.json`` and ``PREFIX.txt``. The default prefix is
  ``flux-rabbit-orphan-scan.<timestamp>``.

.. option:: --delay=SECONDS

  Sleep this many seconds between jobs, to pace the load placed on the
  resource module. The default is 0. See `LOAD ON THE SCHEDULER`_.

.. option:: --timeout=SECONDS

  Maximum time to wait for a single resource module or job manager RPC.
  The default is 120. Job listing and KVS lookups are not bounded by this
  timeout.

.. option:: --settle=SECONDS

  A job that became inactive fewer than this many seconds ago is reported
  but not counted as orphaned, since its release may still be in flight.
  The default is 60.

.. option:: --only-with-R

  Skip inactive jobs that never ran. Such jobs cannot hold allocations.

.. option:: --eventlog-all

  Read the eventlog and **R** of every scanned job, not only the jobs that
  have leftover state.

.. option:: --full-vertices

  Write all vertex lists to the JSON file, including down vertices, all
  aggregate filters, and running jobs. The file becomes large.

.. option:: -q, --quiet

  Do not write progress or the summary to stderr. Warnings, such as a job
  whose scan failed, are still written.


OPERATION
=========

For each job, the command:

1. Asks the resource module which vertices hold state for the job
   (``jobid-alloc``, ``jobid-reserved``, ``jobid-span``, ``jobid-tag``).
2. Asks the resource module for its own record of the job (``ALLOCATED``,
   ``RESERVED``, ``ERROR``, or no record).
3. Reads the job eventlog from flux-core (``alloc``, ``release``, ``free``,
   ``clean``, ``exception`` events).
4. Checks whether the job is in housekeeping in the job manager.
5. Places the job in a class, as described in `JOB CLASSES`_.

The command also records all vertices that the resource module reports as
allocated, reserved, or down; the aggregate (pruning) filter counts
(``used`` and ``total`` for each resource type) on each vertex that has a
filter; and allocated vertices that no scanned job owns.


JOB CLASSES
===========

running
  The job is running and its state is correct. No action is needed.

inactive-and-clean
  The job is inactive and has no state in the graph. No action is needed.

held-pending-final-free
  The job is inactive and the module's record of the job is ``ALLOCATED``,
  but flux-core has not sent the final free: the job is in housekeeping, or
  the eventlog has no ``clean`` event. This is not an orphan. Check
  :core:man1:`flux-housekeeping`.

orphan-module-still-allocated
  flux-core has completed the job (``clean`` event) but the module's record
  of the job is still ``ALLOCATED``, meaning the final cancel did not reach
  the module. This is an orphan. Look for the job ID in
  :core:man1:`flux-dmesg` output.

orphan-module-no-record
  The module has no record of the job, but the graph still holds its state.
  This is an orphan, and indicates a leak in Fluxion.

module-error
  The module's record of the job is ``ERROR``, meaning a removal failed.
  Look for ``dfu_traverser_t::remove`` in :core:man1:`flux-dmesg` output.

reservation
  The module holds a reservation for an inactive job. This usually clears
  on the next scheduling loop.

running-no-graph-state
  The job is running, but the graph has no state for it. The job was
  possibly not reconstructed after a module reload.

running-module-unknown
  The job is running, but the module has no record of it. As above.

scan-error
  The scan of this job raised an error, for example a ``find`` RPC that
  timed out. The remaining jobs are still scanned. The ``error`` key of
  the job in the JSON file holds the message. The summary warns that the
  scan is incomplete and the orphan totals exclude jobs whose scans
  failed. The JSON records the failure count in ``summary.n_jobs_failed``.

recent-\*
  One of the classes above, but the job became inactive fewer than
  :option:`--settle` seconds ago. Run the scan again later.


THE SUMMARY
===========

The summary has the following sections.

**graph snapshot**
  The number of allocated, reserved, and down vertices. The ``find`` RPC
  also returns the ancestors of each matching vertex, so a result that has
  one ``ssd`` also has its ``chassis`` and the ``cluster``. The ``leaf``
  count includes only the vertices with no matching descendant, and is
  usually the number to read. A ``leaf by type`` entry of
  ``{'ssd': 3, 'core': 6}`` means that 3 ssd vertices and 6 core vertices
  hold the state.

**aggregate (pruning) filters with used != 0**
  The planner counts that the traverser uses to reject a subtree. If no job
  is running, all ``used`` values must be 0. A nonzero ``used`` value while
  no job is running is orphaned planner state.

**job classification**
  The number of jobs in each class.

**jobs with leftover graph state**
  One line for each inactive job that still has state. The columns
  ``alloc``, ``resv``, ``span``, and ``tag`` give the number of vertices
  with that type of state. The ``eventlog`` column holds flags: ``A`` for
  alloc, ``R<n>`` for *n* release events, ``F`` for free, ``C`` for clean,
  and ``X`` for exception. A dash means the event is not present.

**orphaned vertices**
  The *allocated* vertices that belong to jobs in the classes
  ``orphan-module-no-record``, ``orphan-module-still-allocated``, and
  ``module-error``.

  Vertices returned by the ``jobid-span``, ``jobid-tag``, and
  ``jobid-reserved`` queries for the same jobs are reported on a separate
  line and in ``summary.orphaned_residue`` in the JSON. Each identifiable
  vertex appears once per job, with the queries that returned it recorded
  in its ``predicates`` list. Query results include ancestors for context,
  so this list may overlap the allocation list: do not add the two sets of
  counts. A job whose only leftover state is residue has an empty orphaned
  allocation list.

**allocated vertices not explained by scanned jobs**
  These vertices may belong to jobs older than the scan window, or to
  non-job allocations. If any job scan failed, they may also belong to
  those jobs: resolve the reported errors and rerun before increasing
  :option:`--count`. Otherwise, run again with a larger :option:`--count`.
  Resource release during the scan can also cause this result; see
  `CAVEATS`_.

**housekeeping**
  Jobs that the job manager still holds in housekeeping, with the ranks
  that have not been released. A job in housekeeping is already inactive
  and already has a ``clean`` event, so housekeeping is the only thing
  that separates it from a genuine orphan. If the
  ``job-manager.stats-get`` RPC fails, the command cannot make that
  distinction: it prints a warning at the top of the summary, records the
  failure under ``meta.housekeeping_error`` in the JSON, and every such
  job is reported as ``orphan-module-still-allocated``. Treat the orphan
  classes with suspicion when that warning is present.


EXIT STATUS
===========

If a per-job aggregate-filter query fails, the predicate results,
classification, and orphan totals are preserved. The job's JSON record
contains ``agfilter_error`` and a null ``graph_state.agfilter-per-job``.
The command prints a warning and records it in the text summary. This
diagnostic failure does not change the exit status.

0
  Every selected job was scanned successfully.

1
  At least one job scan failed. Both output files are written before the
  command exits, so the partial results are preserved, and the summary
  warns that the orphan totals exclude the jobs that failed.

2
  The scan could not be run at all, because an RPC failed before any job
  was scanned: the resource module did not answer, or the job listing
  failed. No output files are written. The reason is written to stderr.


LOAD ON THE SCHEDULER
=====================

The resource module answers each ``find`` RPC on its main thread, and while
it does so it is not scheduling jobs. The time for one ``find`` grows with
the size of the resource graph: on a graph with 19000 vertices, one ``find``
takes between 5 and 100 milliseconds.

The command sends one ``find`` for each job, plus 5 more for each job that
has leftover state. For 300 jobs on a healthy system, the total time spent
in the module is less than a few seconds. On a busy system, use
:option:`--delay` to spread out the load.


EXAMPLES
========

A healthy system:

::

  $ flux rabbit-orphan-scan -n 100 -o /tmp/scan
  ...
  ## job classification
  running                              12
  inactive-and-clean                   100

  ## orphaned vertices
  by type: {}   leaf only: {}

  ## allocated vertices not explained by scanned jobs
  0 vertices, 0 leaf  {}

All inactive jobs are ``inactive-and-clean`` and no vertices are orphaned,
so no action is necessary.

A system with one orphaned ssd:

::

  ## graph snapshot
    allocated       15 vertices,       9 leaf,      6 rank-less   leaf by type: {'ssd': 3, 'core': 6}

  ## job classification
  running                              1
  orphan-module-still-allocated        1

  ## jobs with leftover graph state (excluding running jobs)
         jobid class                                module     alloc  resv  span   tag rankless  eventlog  ...  leaf types
       f2yUbiAAGQP orphan-module-still-allocated        ALLOCATED      3     0     1     3        3  AR1FC-    ...  {'ssd': 1}

  ## orphaned vertices
  by type: {'ssd': 1, 'chassis': 1, 'cluster': 1}   leaf only: {'ssd': 1}
       f2yUbiAAGQP orphan-module-still-allocated  ssd          rank=-1    /hetchy/chassis0/ssd1
       f2yUbiAAGQP orphan-module-still-allocated  chassis      rank=-1    /hetchy/chassis0
       f2yUbiAAGQP orphan-module-still-allocated  cluster      rank=-1    /hetchy

The job is complete in flux-core (the ``C`` flag) but the module's record of
it is still ``ALLOCATED``, so the ssd ``/hetchy/chassis0/ssd1`` is orphaned.
The ``chassis`` and ``cluster`` lines are its ancestors; the ``leaf only``
count shows that only the ssd holds the state.

State held by housekeeping:

::

  ## job classification
  held-pending-final-free              1

  ## jobs with leftover graph state (excluding running jobs)
         jobid class                                module     alloc  resv  span   tag rankless  eventlog  ...
       f4yBboYGo held-pending-final-free              ALLOCATED      5     0     3     5        3  AR1FCX    ...

  ## housekeeping: 1 jobs still in housekeeping
       f4yBboYGo started=2026-10-01T22:03:48+00:00 pending=20 allocated=20

The job is in housekeeping on rank 20 and flux-core has not sent the final
free, so the state is correct and is not an orphan. If the job stays in
housekeeping for a long time, examine the housekeeping script on that rank.

A long scan on a large system:

::

  $ nohup flux rabbit-orphan-scan -n 2000 --delay 0.2 --only-with-R -q \
        -o /var/tmp/orphan-scan-$(date +%F) > /var/tmp/orphan-scan.log 2>&1 &

This scans 2000 jobs, waits 0.2 seconds between jobs, skips jobs that did
not run, and writes no progress output.

The JSON output may be processed with ``jq``. To count the
orphaned vertices of each type:

::

  $ jq '.summary.orphaned_vertices_by_type' /tmp/scan.json

To list the orphaned ssd vertices with their owning jobs:

::

  $ jq -r '.summary.orphaned_vertices[] | select(.type=="ssd") | "\(.jobid) \(.path)"' /tmp/scan.json

To list the aggregate filters with a nonzero ``used`` value:

::

  $ jq -r '.agfilter.nonzero[] | "\(.path) \(.agfilter)"' /tmp/scan.json


CAVEATS
=======

The scan is not atomic. The global graph snapshots are taken before the
job listings and per-job queries. A job listed as running may finish and
release its resources before its per-job query, causing a healthy job to
appear as ``running-no-graph-state`` and its former allocation to appear
as unexplained. Longer scans, including those paced with :option:`--delay`,
give jobs more time to change state between queries. Repeat the scan and
check the current job state before treating these results as persistent
orphaned state. Increasing :option:`--count` does not eliminate this race.

The JGF writer of the resource module cannot emit a set of vertices that
has no edges, and in that case the command falls back to the ``simple``
writer. That writer emits a name and a size but no containment path, rank, or
type, so the command reports the path as the bare name, leaves the rank
unset, and guesses the type from the name prefix. A name with no trailing
digits, such as a cluster named ``hetchy``, yields no usable prefix and
the type is reported as ``unknown``. When a type was guessed this way the
JSON marks the vertex with ``type_guessed_from_name: true``. The
``rankless`` column counts only vertices with a known rank of -1, so for
these jobs it can be lower than the true number.

The bare names from the simple writer do not uniquely identify vertices.
Residue records from that writer are therefore kept separately for each
query, and their counts may include the same vertex more than once.

The ``sched-fluxion-resource.status`` RPC used by ``flux ion-resource
status`` consults a cache and shows only vertices that have a broker rank.
This command does not use it. It uses ``find`` with the JGF writer, which
shows all vertices, including rank-less ssd vertices.

This command does not remove orphaned state. To remove it, restart the
resource module using the site's configured restart procedure.

When restarting manually, remove ``sched-fluxion-qmanager``, reload
``sched-fluxion-resource`` with its original module arguments, then load
``sched-fluxion-qmanager`` with its original module arguments.
:core:man1:`flux-module` ``reload`` does not reuse arguments from the
previous load or apply the module arguments configured for
:core:man1:`flux-modprobe`. Record the original arguments for both modules
before removing them. Preserve resource options such as ``load-file``,
``load-format``, ``match-policy``, and ``prune-filters``, along with the
queue manager options. Losing the original graph or scheduling options
can leave rabbit resources missing or change scheduling behavior.

Run this command before the restart to keep a record of the orphaned state.


SEE ALSO
========

:core:man1:`flux-dmesg`, :core:man1:`flux-housekeeping`,
:core:man1:`flux-jobs`
