/************************************************************\
 * Copyright 2021 Lawrence Livermore National Security, LLC
 * (c.f. AUTHORS, NOTICE.LLNS, COPYING)
 *
 * This file is part of the Flux resource manager framework.
 * For details, see https://github.com/flux-framework.
 *
 * SPDX-License-Identifier: LGPL-3.0
\************************************************************/

#ifndef _LIBAPINFO_APINFO1_H
#define _LIBAPINFO_APINFO1_H

/* Application file format version */
#define PALS_APINFO_VERSION 1

/* File header structure */
typedef struct {
    int version;               // Set to PALS_APINFO_VERSION
    size_t total_size;         // Size of the whole file in bytes
    size_t comm_profile_size;  // sizeof(pals_comm_profile_t)
    // offset from beginning of file to the first comm_profile_t
    size_t comm_profile_offset;
    // number of comm_profile_t (not used yet, set to 0)
    int ncomm_profiles;
    size_t cmd_size;  // sizeof(pals_cmd_t)
    // offset from beginning of file to the first pals_cmd_t
    size_t cmd_offset;
    int ncmds;       // number of commands (MPMD programs)
    size_t pe_size;  // sizeof(pals_pe_t)
    // offset from beginning of file to the first pals_pe_t
    size_t pe_offset;
    int npes;          // number of PEs (processes/ranks)
    size_t node_size;  // sizeof(pals_node_t)
    // offset from beginning of file to the first pals_node_t
    size_t node_offset;
    int nnodes;       // number of nodes
    size_t nic_size;  // sizeof(pals_nic_t)
    // offset from beginning of file to the first pals_nic_t
    size_t nic_offset;
    int nnics;  // number of NICs (not used yet, set to 0)
} pals_header_t;

/* Network communication profile structure */
typedef struct {
    char tokenid[40];    /* Token UUID */
    int vni;             /* VNI associated with this token */
    int vlan;            /* VLAN associated with this token */
    int traffic_classes; /* Bitmap of allowed traffic classes */
} pals_comm_profile_t;

/* MPMD command information structure */
typedef struct {
    int npes;         /* Number of tasks in this command */
    int pes_per_node; /* Number of tasks per node */
    int cpus_per_pe;  /* Number of CPUs per task */
} pals_cmd_t;

/* PE (i.e. task) information structure */
typedef struct {
    int localidx; /* Node-local PE index */
    int cmdidx;   /* Command index for this PE */
    int nodeidx;  /* Node index this PE is running on */
} pals_pe_t;

/* Node information structure */
typedef struct {
    int nid;           /* Node ID */
    char hostname[64]; /* Node hostname */
} pals_node_t;

/* NIC address type */
typedef enum { PALS_ADDR_IPV4, PALS_ADDR_IPV6, PALS_ADDR_MAC } pals_address_type_t;

/* NIC information structure */
typedef struct {
    int nodeidx;                      /* Node index this NIC belongs to */
    pals_address_type_t address_type; /* Address type for this NIC */
    char address[40];                 /* Address of this NIC */
} pals_nic_t;

#endif  // !_LIBAPINFO_APINFO1_H

// vi:ts=4 sw=4 expandtab
