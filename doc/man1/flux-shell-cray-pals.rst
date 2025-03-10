=======================
flux-shell-cray-pals(1)
=======================

DESCRIPTION
===========

**flux** **run** *-opmi=cray-pals*

DESCRIPTION
===========

:program:`cray-pals` is a :core:man1:`flux-shell` plugin that assists
with the launch of programs built with Cray MPICH.  It creates an ``apinfo``
data file on each node and sets several environment variables which are
used by Cray PMI to initialize.

After :program:`cray-pals` places that data on each node, Cray PMI bootstraps
an overlay network and handles the PMI data exchange without Flux.

SHELL OPTIONS
=============

.. option:: pmi=cray-pals

  Enable only the cray-pals PMI plugin.  Other PMI implementations may
  be added, separated by commas.

.. option:: cray-pals.no-edit-env

  Prevent the cray-pals PMI plugin from removing Flux's PMI library
  directory from :envvar:`LD_LIBRARY_PATH`, if present.

  It is removed by default to ensure that Cray PMI library is found
  before Flux's.

.. option:: cray-pals.apinfo-version=1

  Force HPE apinfo version 1.  The default is version 5.

.. note::

  On systems where Cray MPICH is used, it may be helpful for system
  administrators to customize ``/etc/flux/shell/initrc`` to enable
  :program:`cray-pals` by default:

  .. code-block:: lua

    if shell.options['pmi'] == nil then
        shell.options['pmi'] = 'cray-pals,simple'
    end

  :program:`simple` PMI is required to launch Flux instances, so if the
  :option:`pmi` default is changed, be sure to include it also.


ENVIRONMENT
===========

The following environment variables are set by :program:`cray-pals`,
as required by Cray PMI.

.. envvar:: PALS_APID

  Alias for :envvar:`FLUX_JOB_ID`, forced into integer form.

.. envvar:: PALS_APINFO

  The path to the aforementioned ``apinfo`` file on the local node.

.. envvar:: PALS_RANKID

  Alias for :envvar:`FLUX_TASK_RANK`.

.. envvar:: PALS_NODEID

  The index of the local node relative to the job.

.. envvar:: PALS_SPOOL_DIR

  Alias for :envvar:`FLUX_JOB_TMPDIR`.

.. envvar:: PMI_CONTROL_PORT

  Set to a comma-separated pair of port numbers allocated to the job by
  the :program:`cray_pals_port_distributor` jobtap plugin and passed to
  :program:`cray-pals` via the job eventlog.

.. envvar:: PMI_SHARED_SECRET

  Set to a random 64 bit integer, also allocated to the job by
  :program:`cray_pals_port_distributor`.

APINFO
======

The APINFO contains application data in the following sections:

comm profiles
  One comm profile per NIC, each of which defines a CXI service that
  includes VNI numbers for access control and allowed traffic classes.
  The default CXI service is used if none is provided here.
  Not supported by :program:`cray-pals`, but a high priority for future
  development.

command
  One entry per MPMD application, each with tasks per node and CPU per
  task.  MPMD is not supported by :program:`cray-pals` so there is
  always just one entry.

pes
  One entry per task rank, each containing a node-local task index,
  a reference to the assigned MPMD command, and a node index.

nodes
  One entry per node allocated to the job, each containing a hostname
  and a node index.

nics
  One entry per NIC for each NIC assigned to the job across all nodes.
  Each entry contains the NIC address, etc., for scalable program launch.
  Not supported by :program:`cray-pals`.

DEBUGGING
=========

The following may be useful if :func:`MPI_Init()` is failing for unknown
reasons.

.. tip::

  Obtain a Flux allocation with :option:`flux alloc` that will fit the minimum
  MPI size that can reproduce the issue.

1. Run with :option:`flux run -o verbose=2` and check for output from
:program:`cray-pals`.

.. code-block::

  $ flux run -o pmi=cray-pals -N2 -n2 -o verbose=2 true
  ...
  0.051s: flux-shell[1]: DEBUG: pmi-cray-pals: enabled
  0.068s: flux-shell[1]: TRACE: pmi-cray-pals: created pals apinfo file
    /var/tmp/user/flux-tBlt5H/jobtmp-1-f4yBboYGo/libpals_apinfo
  0.069s: flux-shell[1]: TRACE: pmi-cray-pals: set PMI_SHARED_SECRET to 16945943893152566943
  0.069s: flux-shell[1]: TRACE: pmi-cray-pals: set PALS_NODEID to 1
  0.069s: flux-shell[1]: TRACE: pmi-cray-pals: set PALS_APID to 8762756694016
  0.069s: flux-shell[1]: TRACE: pmi-cray-pals: set PALS_SPOOL_DIR to
    /var/tmp/user/flux-tBlt5H/jobtmp-1-f4yBboYGo
  0.069s: flux-shell[1]: TRACE: pmi-cray-pals: set PALS_APINFO to
    /var/tmp/user/flux-tBlt5H/jobtmp-1-f4yBboYGo/libpals_apinfo
  0.070s: flux-shell[1]: TRACE: pmi-cray-pals: set PALS_RANKID to 1
  0.047s: flux-shell[0]: DEBUG: pmi-cray-pals: enabled
  0.064s: flux-shell[0]: TRACE: pmi-cray-pals: created pals apinfo file
    /var/tmp/user/flux-pSw4um/jobtmp-0-f6jyUdR2P/libpals_apinfo
  0.065s: flux-shell[0]: TRACE: pmi-cray-pals: set PMI_CONTROL_PORT to 11998,11999
  0.065s: flux-shell[0]: TRACE: pmi-cray-pals: set PMI_SHARED_SECRET to 11872392986869071399
  0.065s: flux-shell[0]: TRACE: pmi-cray-pals: set PALS_NODEID to 0
  0.065s: flux-shell[0]: TRACE: pmi-cray-pals: set PALS_APID to 12675874553856
  0.065s: flux-shell[0]: TRACE: pmi-cray-pals: set PALS_SPOOL_DIR to
    /var/tmp/user/flux-pSw4um/jobtmp-0-f6jyUdR2P
  0.065s: flux-shell[0]: TRACE: pmi-cray-pals: set PALS_APINFO to
    var/tmp/user/flux-pSw4um/jobtmp-0-f6jyUdR2P/libpals_apinfo
  0.066s: flux-shell[0]: TRACE: pmi-cray-pals: set PALS_RANKID to 0

2. Check that you can launch a PMI test program configured to use Cray PMI
using the same options.  In this example, :core:man1:`flux pmi` is used.

.. code-block::

  $ flux run -o pmi=cray-pals --label-io -N2 -n2 flux pmi --method=libpmi2 --verbose barrier
  0: libpmi2: using /opt/cray/pe/lib64/libpmi2.so (cray quirks enabled)
  0: libpmi2: initialize: rank=0 size=2 name=kvs_160608288768: success
  0: libpmi2: barrier: success
  0: libpmi2: barrier: success
  0: libpmi2: finalize: success
  0: f5DhQTk3: completed pmi barrier on 2 tasks in 0.000s.
  1: libpmi2: using /opt/cray/pe/lib64/libpmi2.so (cray quirks enabled)
  1: libpmi2: initialize: rank=1 size=2 name=kvs_160608288768: success
  1: libpmi2: barrier: success
  1: libpmi2: barrier: success
  1: libpmi2: finalize: success

3. Check that you can launch an MPI hello world program compiled with
Cray MPICH.

.. code-block::

  $ flux run -o pmi=cray-pals --label-io -N2 -n2 proj/mpi-test/hello
  0: fdfdnnoy: completed MPI_Init in 0.581s.  There are 2 tasks
  0: fdfdnnoy: completed first barrier in 0.002s
  0: fdfdnnoy: completed MPI_Finalize in 0.017s

4. Activate debugging output for Cray PMI.

.. code-block::

  $ flux run --env=PMI_DEBUG=1 --label-io -N2 -n2 proj/mpi-test/hello
  1: Mon Mar 10 14:46:06 2025: [unset]: _pmi_pals_init:my_peidx=1,npes=2,
    nnodes=2,napps=1,my_cmd.pes_per_node=1,my_cmd.npes=2,my_pe.localidx=0,
    my_pe.nodeidx=1,my_pe.cmdidx=0,nid=1
  1: Mon Mar 10 14:46:06 2025: [PE_1]: _pmi2_kvs_hash_entries = 1
  1: Mon Mar 10 14:46:06 2025: [PE_1]: mmap in a file for shared memory type 4 len 345600
  1: Mon Mar 10 14:46:06 2025: [PE_1]:  pals_get_nodes nnodes = 2 pals_get_nics nnics = 0
  ...

If all else fails, Cray MPICH works at least superficially with Flux's
:program:`simple` PMI:

.. code-block::

  $ flux run -o pmi=simple -n2 -N2 proj/mpi-test/hello
  fB6P3jXzo: completed MPI_Init in 0.396s.  There are 2 tasks
  fB6P3jXzo: completed first barrier in 0.000s
  fB6P3jXzo: completed MPI_Finalize in 0.010s


SEE ALSO
========

:core:man1:`flux-submit`, :core:man1:`flux-shell`
