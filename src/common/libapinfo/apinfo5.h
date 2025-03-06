/************************************************************\
 * Copyright 2025 Lawrence Livermore National Security, LLC
 * (c.f. AUTHORS, NOTICE.LLNS, COPYING)
 *
 * This file is part of the Flux resource manager framework.
 * For details, see https://github.com/flux-framework.
 *
 * SPDX-License-Identifier: LGPL-3.0
\************************************************************/

#ifndef _LIBAPINFO_APINFO5_H
#define _LIBAPINFO_APINFO5_H

/* Application file format version */
#define PALS_APINFO_VERSION 5

typedef struct {
    int version;
    size_t total_size;
    size_t comm_profile_size;
    size_t comm_profile_offset;
    int ncomm_profiles;
    size_t cmd_size;
    size_t cmd_offset;
    int ncmds;
    size_t pe_size;
    size_t pe_offset;
    int npes;
    size_t node_size;
    size_t node_offset;
    int nnodes;
    size_t nic_size;
    size_t nic_offset;
    int nnics;
    size_t status_offset;
    size_t dist_size;
    size_t dist_offset;
} pals_header_t;

/* Network communication profile structure */
typedef struct {
    uint32_t svc_id;          /**< CXI service ID */
    uint32_t traffic_classes; /**< Bitmap of allowed traffic classes */
    uint16_t vnis[4];         /**< VNIs for this service */
    uint8_t nvnis;            /**< Number of VNIs */
    char device_name[16];     /**< NIC device for this profile */
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
    int nodeidx;                      /**< Node index this NIC belongs to */
    pals_address_type_t address_type; /**< Address type for this NIC */
    char address[64];                 /**< Address of this NIC */
    short numa_node;                  /**< NUMA node it is in */
    char device_name[16];             /**< Device name */
    long _unused[2];
} pals_hsn_nic_t;

/* Distance to NIC information structure */
typedef struct {
    uint8_t num_nic_distances;     /**< Number of CPU->NIC distances on current node */
    uint8_t accelerator_distances; /**< Accel distances too? (bool). Set to 0, not used. */
    uint8_t distances[0];          /* < One for each NIC, two if using accelerators */
} pals_distance_t;

#endif  // !_LIBAPINFO_APINFO5_H

// vi:ts=4 sw=4 expandtab
