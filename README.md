
*NOTE: The plugins and scripts in flux-coral2 are being actively developed
and are not yet stable.* The github issue tracker is the primary way to
communicate with the developers.

## Flux CORAL2

Welcome to Flux-specific plugins and scripts for the
DOE [CORAL2](https://procurement.ornl.gov/rfp/CORAL2/) systems.

Flux CORAL2 consists of several plugins, including:
- A Fluxion resource match plugin to make performant selections of compute and [storage nodes](https://www.hpcwire.com/2021/02/18/livermores-el-capitan-supercomputer-hpe-rabbit-storage-nodes/)
- `job-shell` plugin to support Cray MPI bootstrap via libpals
- `job-manager` jobtap plugin to insert a job dependency on `#DW` string validation and translation
- Script to validate `#DW` strings via the Data Workflow Services (DWS) K8s API and then insert translated rules into user's submitted jobspec
- Script to generate a Fluxion JGF file from DWS inventory API
- `job-exec` plugin to transition jobs through the DWS job lifecycle and passthrough `DW_*` env vars to job environment
- flux-core `resource` module plugin to track inventory status changes via the DWS API

### Building Flux CORAL2

Flux CORAL2 requires an installed flux-core and flux-sched package.  Instructions
for building/accessing these packages can be found in
[Flux's documentation](https://flux-framework.readthedocs.io/en/latest/quickstart.html#building-the-code).

### Building Data Workflow Services (DWS)

Flux CORAL2 requires a K8s server with the DWS CRDs and the NNF objects contained in `./k8s`.

When developing locally, the best way to achieve this is to use the NNF team's [nnf-deploy](github.com/NearNodeFlash/nnf-deploy) tool. Follow the instructions in the readme to build the tool and to [deploy it to a kind cluster](github.com/NearNodeFlash/nnf-deploy#kind-cluster). You will need to have [go](https://go.dev/) and [kind](https://kind.sigs.k8s.io/) installed.

The next step is to add the objects to your cluster with `kubectl apply -f ./k8s`.

### Running Flux CORAL2

Once you have a k8s server up and running and the proper credentials in your `~/.kube/config` file, you can launch a container that runs the full testsuite with `./src/test/docker/docker-run-checks.sh --`.  This script not only builds a test container on top of the flux-sched image and running the testsuite, but it also handles mounting and tweaking the k8s credentials on your host to work within the container.  You can also use the container interactively by passing the `-I` flag to `docker-run-checks.sh`.

Note: Some of the tests interact with a single, shared K8s cluster.  While the tests as a whole are designed to be idempotent, their interactions with K8s are not atomic. Thus it is advised that the testsuite be run serially (e.g., `make check`) as opposed to in parallel (e.g., `make -j check`) to avoid tests conflicting with one another's expected K8s state.
