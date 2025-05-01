==================
flux-jobtap-dws(1)
==================


SYNOPSIS
========

**flux** **jobtap** **load** *dws-jobtap.so* [*epilog-timeout=N*]


DESCRIPTION
===========

``dws-jobtap.so`` is a :core:man1:`flux-jobtap` plugin for holding jobs in various
states while rabbit work is being done.

When a rabbit job is first submitted, a dependency is placed on it while the
rabbit resource requirements are worked out.

After a rabbit job is allocated resources, the ``dws-jobtap`` plugin holds the job
in a prolog action while the rabbit file systems are created and mounted, and data
movement (if requested) is performed.

After a rabbit job finishes, and as it enters the cleanup state, the ``dws-jobtap``
plugin holds the job in an epilog action while compute nodes unmount the rabbit file
system and data is moved off of the job's rabbits.


OPTIONS
=======

.. option:: epilog-timeout=N

  A floating-point number giving the maximum number of seconds that the epilog
  action should be allowed to run. If the timeout expires with the epilog
  action still active, an exception will be raised and the following actions
  are taken:

  #. Any nodes in the job that have not unmounted their file systems will be drained.
  #. Any rabbits used by the job that have not cleaned up their file systems will be marked as ``Disabled`` and will not be used by Flux until they are manually returned to service.


  If ``epilog-timeout`` is 0 or negative, no timeout is set.



SEE ALSO
========

:core:man1:`flux-jobtap`, :core:man7:`flux-jobtap-plugins`
