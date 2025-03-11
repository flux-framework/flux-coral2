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

*****************
Enabling Cray MPI
*****************

For convenience, the :man1:`flux-shell-cray-pals` plugin should be loaded
in all Flux instances.  Edit ``/etc/flux/shell/initrc.lua`` to contain:

.. code-block:: lua

  if shell.options['pmi'] == nil then
      shell.options['pmi'] = 'cray-pals,simple'
  end

The ``cray_pals_port_distributor.so`` jobtap plugin, required by the above,
is loaded automatically via ``/etc/flux/rc1.d/01-coral2-rc``.

