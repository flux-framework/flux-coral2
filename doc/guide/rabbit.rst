.. _rabbit:

=================
Flux with Rabbits
=================


How to Allocate Rabbit Storage
------------------------------

Request rabbit storage allocations for a job
by setting the ``.attributes.system.dw`` field in a jobspec to
a string containing one or more
`DW directives <https://nearnodeflash.github.io/latest/guides/user-interactions/readme/>`_.
A JSON list of DW directives is also accepted, but cannot be provided on the
command line. (It is however possible when constructing jobspecs with Flux's
Python bindings, or when creating jobspecs directly.)

On the command line, set the ``.attributes.system.dw`` field by passing flags
like ``-S dw="my_string"`` or ``--setattr=dw="my_string"``.

The simplest way to use rabbits is to use preset DW strings that
administrators may have configured on a system. For more flexibility,
it may be desirable to write custom DW strings.


Preset DW Directives
--------------------

Running

.. code-block:: bash

	flux config get rabbit.presets | jq .

will display a mapping of the presets that have been configured on the
current system. The keys of the mapping are the strings that you can
pass to ``-S dw=...``, the values of the mapping are the actual DW directives
the strings correspond to.


Preset Example
~~~~~~~~~~~~~~

Suppose ``flux config get rabbit.presets | jq .`` returns the following:

.. code-block:: json

	{
		"xfs_small": "#DW jobdw type=xfs capacity=256GiB name=xfssmall",
		"xfs_large": "#DW jobdw type=xfs capacity=1TiB name=xfslarge",
		"lustre_large": "#DW jobdw type=lustre capacity=10TiB name=lustrelarge",
	}

Then you should be able to add the flag ``-S dw=lustre_large`` to
``flux run/batch/alloc/submit`` and have 10 Terabytes of lustre storage
accessible to your job at a path given by the ``$DW_JOB_lustrelarge``
environment variable. Similarly, ``-S dw=xfs_small`` and ``-S dw=xfs_large``
would give your job 256 gigabytes and 1 terabyte of XFS storage at
``$DW_JOB_xfssmall`` and ``$DW_JOB_xfslarge``, respectively.


Custom DW Directives
--------------------

Writing custom DW directives instead of using preset strings allows for much
greater flexibility.

DW directives are strings that start with ``#DW``. Directives
that begin with ``#DW jobdw`` are for requesting storage that
lasts the lifetime of the associated flux job. Directives that
begin with ``#DW copy_in`` and ``#DW copy_out`` are for
describing data movement to and from the rabbits, respectively.

Full documentation of the DW directives and their arguments is available
`here <https://nearnodeflash.github.io/latest/guides/user-interactions/readme/>`_.

The usage with Flux is most easily understood by example.


Examples of custom jobdw directives
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Requesting a 10 gigabyte XFS file system per compute node on the
command line:

.. code-block:: console

	$ flux alloc -N2 -S dw="#DW jobdw type=xfs capacity=10GiB name=project1"

Requesting both XFS and lustre file systems in a batch script:

.. code-block:: bash

	#!/bin/bash

	#FLUX: -N 2
	#FLUX: -q pdebug
	#FLUX: -S dw="""
	#FLUX: #DW jobdw type=xfs capacity=1TiB name=xfsproject
	#FLUX: #DW jobdw type=lustre capacity=10GiB name=lustreproject
	#FLUX: """

	echo "Hello World!" > $DW_JOB_lustreproject/world.txt

	flux submit -N2 -n2 /bin/bash -c "echo 'Hello World!' > $DW_JOB_xfsproject/world.txt"


Data Movement Examples
~~~~~~~~~~~~~~~~~~~~~~

.. warning::

	When writing ``copy_in`` and ``copy_out`` directives *on the command line*,
	be careful to always escape the ``$`` character when writing ``DW_JOB_[name]``
	variables. Otherwise your shell will expand them. This warning does not apply
	to batch scripts.

Requesting a 10 gigabyte XFS file system per compute node on the command
line with data movement both to and from the rabbits (the source directory
is assumed to exist):

.. code-block:: console

	$ flux alloc -N2 -S dw="#DW jobdw type=xfs capacity=10GiB name=project1
	#DW copy_in source=/p/lustre1/$USER/dir_in destination=\$DW_JOB_project1/
	#DW copy_out source=\$DW_JOB_project1/ destination=/p/lustre1/$USER/dir_out/"

Requesting a lustre file system, with data movement out from the rabbits,
in a batch script:

.. code-block:: bash

	#!/bin/bash

	#FLUX: -N 2
	#FLUX: -q pdebug
	#FLUX: -S dw="""
	#FLUX: #DW jobdw type=lustre capacity=100GiB name=lustreproject
	#FLUX: #DW copy_out source=$DW_JOB_lustreproject destination=/p/lustre1/$USER/lustreproject_results
	#FLUX: """

	echo "Hello World!" > $DW_JOB_lustreproject/world.txt


Enabling Rabbit Fault Tolerance
-------------------------------

Imagine you submit a ten-thousand-node Flux job that requests a rabbit file
system. The job sits in the queue for a long time while your job is scheduled.
Finally your job is assigned resources, but then a single node fails to mount
its file system, and the job fails before it even starts running. You might
wish that Flux had just ignored the single node failure and proceeded with the
remaining 9,999 nodes.

The ``.attributes.system.dw_failure_tolerance`` field in a jobspec can help you
in cases like the one just described. Set the field to a positive integer **N**,
and Flux will allow up to **N** nodes in your job to fail to create or to access
rabbit file systems. For example, ``flux alloc [OPTIONS] -S dw_failure_tolerance=16``
would allow the loss of up to 16 nodes from your job due to rabbit-related failures.

Unlike XFS and GFS2 rabbit file systems, ephemeral Lustre rabbit file systems cannot
tolerate the failed creation of file systems. If any rabbits fail to create their
Lustre targets, the whole job will fail. However, ephemeral Lustre rabbit jobs can
still tolerate failed mounts.

If this attribute is set, and a job proceeds through some rabbit failures, the nodes
that are missing file systems will be drained when the allocation is granted. The
nodes may still be undrained and used at the user's discretion.


Fetching Rabbit Information
---------------------------

The :man1:`flux-getrabbit` command can be used to look up the rabbits used by
a job, as well as what rabbits have PCIe links to which compute nodes and vice
versa.

For example, to list the rabbits used by a job:

::

  $ flux getrabbit -j $JOBID
  rabbit[1001,1003]


Additional Attributes of Rabbit Jobs
------------------------------------

All rabbit jobs have some extra data stored on them to help with debugging and to
help account for time spent on various stages.

Timing Attributes
~~~~~~~~~~~~~~~~~

The timing attributes a rabbit job may have are, in order:

#. ``rabbit_proposal_timing``: time it takes for DWS to process the job's #DW strings
   and provide a breakdown of the resources required to Flux.
#. ``rabbit_setup_timing``: time it takes to create the job's file systems on
   the rabbits chosen by Flux.
#. ``rabbit_datain_timing``: time it takes to move data from Lustre to the rabbits. If
   no ``copy_in`` directives were provided, this state should be very fast.
#. ``rabbit_prerun_timing``: time it takes to mount rabbit file systems on compute
   nodes.
#. ``rabbit_postrun_timing``: time it takes to unmount rabbit file systems from
   compute nodes.
#. ``rabbit_dataout_timing``: time it takes to move data from the rabbits to Lustre,
   should be very fast if no ``copy_out`` directives were provided.
#. ``rabbit_teardown_timing``: time it takes to destroy the rabbit file system and clean
   up.

A job may skip to ``teardown`` if an exception occurs, e.g. a job may only have
``proposal``, ``setup``, ``datain``, and ``teardown`` timings if the rabbit file systems fail
to mount on the compute nodes. Fetch the timing for a state by running, e.g. for
``prerun``,

.. code-block:: bash

	flux job info ${jobid} rabbit_prerun_timing

If the job does not have the timing for a state, for instance because it has not
completed the state yet, expect to see an error like ``flux-job: No such file or directory``.

Debugging Attributes
~~~~~~~~~~~~~~~~~~~~

All rabbit jobs also have a ``rabbit_workflow`` attribute that stores high-level but
technical information about the status of the rabbit job. Fetch the data (which is
in JSON format) with ``flux job info ${jobid} rabbit_workflow``, potentially
piping it to `jq` in order to pretty-print it.

It may be useful to check whether there is an error message set on the workflow, which
can be singled out with

.. code-block:: bash

	flux job info ${jobid} rabbit_workflow | jq .status.message

If that is still unhelpful, try displaying more information:

.. code-block:: bash

	flux job info ${jobid} rabbit_workflow | jq .status

In addition, rabbit jobs *may* have an attribute storing a small collection of
information about data movement. Fetch it with

.. code-block:: bash

	flux job info ${jobid} rabbit_datamovements | jq .

Container Attributes
~~~~~~~~~~~~~~~~~~~~

If a job launched a
`rabbit container <https://nearnodeflash.github.io/latest/guides/user-containers/readme/>`_
with a ``#DW container`` directive, once the job
is complete it will have an additional attribute ``rabbit_container_log`` storing
the tail of the logs of one of the containers. Unfortunately, due to size limitations
of Flux's KVS, the complete logs cannot be stored.

.. code-block:: bash

	flux job info ${jobid} rabbit_container_log | less

Node Distribution
~~~~~~~~~~~~~~~~~

Rabbit systems have one rabbit per chassis. The :man1:`flux-coral2-chassis` flag
may therefore be useful in controlling the allocation of rabbits, especially
for node-local file systems like XFS.
