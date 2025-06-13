Glossary
========

.. glossary::

  APU
    Accelerated Processing Unit.  CPU and GPU are combined on a single chip.

  Cassini
    The HPE 200G Slingshot NIC.

  CORAL
    Collaboration of Oak Ridge, Argonne, and Livermore.  The first CORAL
    procurement was awarded to IBM and brought the Power-9 based pre-exascale
    systems *Sierra* to Livermore and *Summit* to Oak Ridge in 2018.

  CORAL-2
    The second CORAL procurement was awarded to HPE and brought the Cray EX
    based exascale systems *Frontier* to Oak Ridge in 2022, *Aurora* to
    Argonne in 2023, and *El Capitan* to Livermore in 2024.

  CXI
    Cray eXascale Interface.  Another way of referring to the Cassini NIC.

  CXI Service
    An authorization token that grants specific UNIX user and group IDs
    access to a set of Cassini NIC resources: :term:`VNI` numbers,
    :term:`traffic classes <traffic class>`, and NIC hardware entities such
    as transmit and receive queues.

    .. figure:: images/dragonfly.png
      :alt: Dragonfly topology
      :align: right
      :scale: 70 %

      a simplified dragonfly network

  dragonfly
    A two-level interconnect topology that divides switches into groups.
    The switches in each group have some node ports, inter-group ports,
    and intra-group ports.  The intra-group switch ports fully connect
    the switches in the group (level 0), although other topologies are
    permitted.  The inter-group switch ports fully connect the groups
    (level 1).

  fabric manager
    The fabric manager configures, manages, and monitors the :term:`Slingshot`
    network.  It runs on one dedicated server and on the :term:`Rosetta`
    switches.

  MPICH
    The Argonne MPI implementation.  Cray MPICH is a proprietary fork of MPICH.

  PALS
    Parallel Application Launch Service.  The Cray PALS library provides
    placement, interconnect, and debugger information to applications.

  PMI
    Process Management Interface, a quasi-standard bootstrap API and protocol
    for MPI implementations.

  Rabbit
    HPE near-node-local storage product that interfaces with nearby Cray EX
    compute nodes via PCI Express.

  RDMA
    Remote Direct Memory Access.  A low-latency technique that allows a NIC
    to directly access application memory.

  Rosetta
    The HPE 200G, 64-port Slingshot switch.

  traffic class
    A :term:`Cassini` NIC quality of service level.  The classes include
    best effort, bulk data, low latency, and dedicated access.

  Slingshot
    The HPE 200G Ethernet-compliant interconnect.  :term:`CORAL-2` is based
    on Slingshot-11 with :term:`Cassini` NIC and and :term:`Rosetta`
    switch devices configured in a :term:`dragonfly` topology.

  VNI
    Virtual Network Identifier.  An integer packet label used to isolate
    :term:`Slingshot` RDMA traffic.
