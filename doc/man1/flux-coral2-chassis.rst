======================
flux-coral2-chassis(1)
======================


SYNOPSIS
========

**flux** **run** **--nodes=N** *--coral2-chassis=COUNT*


DESCRIPTION
===========

:program:`--coral2-chassis` is an optional flag added to
:core:man1:`flux-submit`, :core:man1:`flux-run`, :core:man1:`flux-alloc`,
and :core:man1:`flux-batch`. The flag takes a positive integer, representing
the number of chassis desired; the number of nodes specified via ``-N, --nodes``
will then be split evenly across that number of chassis.

Use of the ``--coral2-chassis`` flag requires that ``-N, --nodes`` be specified.
Also, current limitations require that the number of chassis evenly divide the
number of nodes. For example, five total nodes across three chassis *is not*
supported, but fifteen total nodes across three chassis is supported.

When not specified, the number of chassis chosen is up to the scheduler.


EXAMPLES
========

Request 15 nodes, all on a single chassis:

::

  flux alloc -N15 --coral2-chassis=1 -q myqueue /bin/true

Request 200 nodes split evenly across 20 chassis:

::

  flux alloc -N200 --coral2-chassis=20 -q myqueue /bin/true

