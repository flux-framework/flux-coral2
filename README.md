
*NOTE: The plugins and scripts in flux-coral2 are being actively developed
and are not yet stable.* The github issue tracker is the primary way to
communicate with the developers.

## Flux CORAL2

Welcome to Flux-specific plugins and scripts for the
DOE [CORAL2](https://procurement.ornl.gov/rfp/CORAL2/) systems.

Flux CORAL2 consists (or will consist) of several plugins, including:
- A Fluxion resource match plugin to make performant selections of compute and [storage nodes](https://www.hpcwire.com/2021/02/18/livermores-el-capitan-supercomputer-hpe-rabbit-storage-nodes/)
- `job-shell` plugin to support Cray MPI bootstrap via libpals
- `job-manager` jobtap plugin to insert a job dependency on `#DW` string validation and translation
- Script to validate `#DW` strings via the DataWarp Services (DWS) K8s API and then insert translated rules into user's submitted jobspec
- Script to generate a Fluxion JGF file from DWS inventory API
- `job-exec` plugin to transition jobs through the DWS job lifecycle and passthrough `DW_*` env vars to job environment
- flux-core `resource` module plugin to track inventory status changes via the DWS API

### Building Flux CORAL2

Flux CORAL2 requires an installed flux-core and flux-sched package.  Instructions
for building/accessing these packages can be found in
[Flux's documentation](https://flux-framework.readthedocs.io/en/latest/quickstart.html#building-the-code).
