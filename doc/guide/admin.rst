.. _coral2-admin-guide

###########################
Flux CORAL-2 Administration
###########################

This supplements the `Flux Administrator's Guide <https://flux-framework.readthedocs.io/projects/flux-core/en/latest/guide/admin.html>`_
with specifics for :term:`CORAL-2` systems.

**********
Background
**********

The CORAL-2 systems at Livermore are running a variant of the TOSS
operating system based on Red Hat Enterprise Linux rather than the SuSE
based distribution normally provided by HPE.

****************************
Installing Software Packages
****************************

Besides the base required packages, install the following.

flux-coral2
  Plugins for running Cray MPICH, managing the slingshot interconnect,
  and managing :term:`rabbit` storage


*****************************
Overlay Network Configuration
*****************************

Experience siting El Capitan yields these recommendations:

- The system instance should use the management ethernet for communication
  between Flux brokers, while user instances may use the Slingshot network.

- The system overlay network should be configured with a flat topology.

- A small amount of tuning helps performance at this scale and overlay fanout.

The following configuration snippet summarizes the above:

.. code-block:: toml

  [bootstrap]
  curve_cert = "/etc/flux/system/curve.cert"
  default_port = 8050
  default_bind = "tcp://en0:%p"
  default_connect = "tcp://e%h:%p"

  hosts = [
    { host = "elcap1", bind = "tcp://192.168.64.1:%p", connect = "tcp://eelcap1:%p" },
    { host = "elcap[201-896,1001-12136]" },
  ]

  [tbon]
  torpid_max = "5m"
  tcp_user_timeout = "2m"
  zmq_io_threads = 4
  child_rcvhwm = 10

***********************
Slingshot Configuration
***********************

Flux-coral2 supports :term:`VNI` tagging for :term:`RDMA` isolation.
To enable it, ensure that flux-coral2 version 0.28.0 or newer
is installed on the system, and use the following procedure.

Configure VNI Tagging
=====================

First, arrange for the ``cray-slingshot.so`` jobtap plugin to be loaded
on the leader broker (management node):

.. code-block:: toml

  [job-manager]
  plugins = [
    { load "cray-slingshot.so" },
  ]

To avoid a Flux restart, load the plugin manually:

.. code-block:: console

  flux jobtap load cray-slingshot.so

Next, enable the prolog, epilog, and housekeeping scriptlets that manage
:term:`CXI services <CXI service>` on behalf of jobs:

.. code-block:: toml

  [cray-slingshot]
  cxi-enable = true

After modifying the configuration files, execute :option:`flux config reload`
across the cluster.  This ensures that the ``cxi-enable`` flag change is
visible to the scriptlets.

.. code-block:: console

  flux config reload

The ``cray-slingshot`` Flux shell plugin will need to be active.
It is active by default so no action is normally needed.

.. note::

  There was an early bug in the ``cray-slingshot.so`` Flux shell plugin
  that required it to be temporarily disabled in the shell ``initrc.lua``
  file.  That problem was addressed in flux-coral2 0.28.0.  Ensure that
  it is no longer disabled on the target system.

Finally, disable the default CXI service.  It is disabled by default
in recent releases of the Slingshot Host Software.  Ensure that it is not
being re-enabled with the ``disable_default_svc=0`` option on the ``cxi_core``
kernel module.  Changing this will require the SHS module stack to be reloaded
on compute notes.

Testing VNI Tagging
===================

Running :man1:`flux-slingshot` in a job may be helpful to verify that
VNI allocations and CXI service setup is happening.

As a baseline reference, a system that does not have VNI tagging enabled
appears as follows.  Svc 1 is the default CXI service.  Svc 2-4 are system
services.

.. code-block:: console

  $ flux run -q pdebug flux slingshot list
  Name     Svc    UID   VNIs      PTEs  TXQs  TGQs  EQs   CTs   LEs   TLEs  ACs
  cxi[0-3] 1      -     1,10      0     0     0     0     0     0     512   0
  cxi[0-3] 2/sys  0               0     0     0     1     0     0     0     1
  cxi[0-3] 3/sys  0               8     1     1     1     0     660   0     1
  cxi[0-3] 4/sys  0               4     4     4     8     0     520   0     2

A system configured as described above  looks like this:

.. code-block:: console

  $ flux run -q parrypeak flux slingshot list
  Name     Svc    UID   VNIs      PTEs  TXQs  TGQs  EQs   CTs   LEs   TLEs  ACs
  cxi[0-3] 1-     -     1,10      0     0     0     0     0     0     512   0
  cxi[0-3] 2/sys  0               0     0     0     1     0     0     0     1
  cxi[0-3] 3/sys  0               8     1     1     1     0     660   0     1
  cxi[0-3] 4/sys  0               4     4     4     8     0     520   0     2
  cxi[0-3] 5      5588  1061      576   192   96    192   96    1536  96    192

Note the hyphen after the default service indicating that it is disabled.
Svc 5 is the service set up for the job owner (UID 5588)  with a unique
allocated VNI (1061).

The shell plugin ensures that the correct environment variables are set.
This can also be checked

.. code-block:: console

  $ flux run -q parrypeak printenv | grep SLINGSHOT_
  SLINGSHOT_VNIS=1062
  SLINGSHOT_DEVICES=cxi0,cxi1,cxi2,cxi3
  SLINGSHOT_SVC_IDS=5,5,5,5
  SLINGSHOT_TCS=0xa

As a final check, run a cray MPICH hello world job that spans multiple nodes:

.. code-block:: console

  $ flux run -N13 -n1248 -q parrypeak ./hello
  f2yUbiAAGQP: completed MPI_Init in 2.161s.  There are 1248 tasks
  f2yUbiAAGQP: completed first barrier in 0.008s
  f2yUbiAAGQP: completed MPI_Finalize in 0.028s

For more detail refer to :ref:`slingshot_interconnect` and the *Security*
section of the *HPE Slingshot Operations Guide* linked from that document.

*****************
Enabling Cray MPI
*****************

For convenience, the :man1:`flux-shell-cray-pals` plugin should be loaded
in all Flux instances.  Edit ``/etc/flux/shell/initrc.lua`` to contain:

.. code-block:: lua

  if shell.options['pmi'] == nil then
      shell.options['pmi'] = 'cray-pals,simple'
  end

The ``cray-pmi-bootstrap.so`` jobtap plugin, required by the above,
is loaded automatically via ``/etc/flux/rc1.d/01-coral2-rc``.

*******
Rabbits
*******

To configure Flux with rabbits, see :man5:`flux-config-rabbit`.

-----------------
Stuck Rabbit Jobs
-----------------

Rabbit jobs may sometimes become stuck in the ``CLEANUP`` state, while they
wait for kubernetes to report that rabbit file systems have unmounted and
cleaned up.

The first thing to do is always to cancel the job and wait a short while to see
if the job cleans up. There is a chance that a job may be stuck while moving
data, and an exception (such as a `cancel` exception) occurring during the
``CLEANUP`` state will tell the Flux plugins to abandon data movement. However,
if the reason the job is stuck is a hung unmount or a rabbit file system that
won't clean up, canceling the job will not help.

In ``flux-coral2`` version ``0.22.0`` and greater, Flux can be configured to
end the epilog after a timeout (see :man5:`flux-config-rabbit`). To remove the
epilog manually without waiting for the timeout, run
``flux job raise --type=dws-epilog-timeout $JOBID``.

If the rabbit job is still stuck in the ``dws-epilog`` action, or if the version
of ``flux-coral2`` is less than ``0.22.0``,

.. code-block:: bash

    # see what nodes still have mounts, if any, and potentially drain them
    kubectl get clientmounts -A -l "dataworkflowservices.github.io/workflow.name=
      fluxjob-$(flux job id $JOBID)" | grep Mounted
    # see what rabbits still have allocations, if any, and potentially disable
    # them.
    kubectl get servers -A -l "dataworkflowservices.github.io/workflow.name=
      fluxjob-$(flux job id $JOBID)" -o json | jq .status.allocationSets
    # remove the epilog action
    flux post-job-event $JOBID epilog-finish name=dws-epilog

The above assumes you have read access to certain kubernetes resources. On LC
machines, the administrator kubeconfig is usually kept at
``/etc/kubernetes/admin.conf``. To use it,
``export KUBECONFIG=/etc/kubernetes/admin.conf``.
