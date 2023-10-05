flux-coral2 0.8.0 - 2023-10-04
------------------------------

### Fixes

 * dws: update group of k8s crds (#101)
 * rc: use posix shell (#98)

### Testsuite

 * testsuite: remove usage of 'flux mini' (#102)
 * testsuite: load content module in rc scripts (#96)

flux-coral2 0.7.0 - 2023-08-30
------------------------------

### New Features

 * dws: build a resource graph with rabbits (#88, #90)
 * dws: schedule rabbits through Fluxion (#92)
 * dws: provide memo listing rabbits associated with job (#92
 * pals: set PMI_SHARED_SECRET (#84)
 * dws: update error handling to distinguish fatal errors (#93)

### Fixes

 * pals: sanitize environment variables (#84)
 * pals: add debug information (#85)
 * dws: improve error message when service is down (#87)

### Testsuite

 * testsuite: add tests for scheduling rabbits through fluxion (#92)

flux-coral2 0.6.0 - 2023-07-20
------------------------------

### New Features

 * dws: handle service crashes (#81)
 * build: add `make deb` target for test packaging (#80)
 * dws: handle persistent allocations (#78)

### Testsuite

 * testsuite: add tests for persistent allocations (#78)

flux-coral2 0.5.0 - 2023-06-09
------------------------------

### New Features

 * dws: set string job IDs in workflows (#74)
 * dws: add workflow name memo to jobs (#73)
 * dws: install shell plugin to main dir (#60)
 * dws: kubeconfig command-line option (#71)
 * dws: split directives by DW token (#63)

### Fixes

 * dws: increase the log level of some messages (#73)
 * dws: change systemd service Requires to BindTo (#61)
 * pals: unset PALS_ variables by default in shell plugin (#68)

### Testsuite

 * testsuite: fix test timeout (#73)


flux-coral2 0.4.0 - 2023-04-07
------------------------------

### New Features

 * dws: Rabbits are chosen based on compute nodes (#53)
 * dws: Workflows in 'Error' state too long are now killed (#49)
 * dws: hold jobs in epilog for data movement (#46)
 * dws: support multiple DW directives in a single string (#54)
 * dws: package coral2_dws.py as a systemd unit (#47)
 * pals: support for `-o pmi=cray-pals` (#58)
 * pals: added an rc script for loading port distributor in all Flux instances (#58)

### Fixes

 * dws: shorten workflow names to prevent DWS overflow errors (#39)
 * build: add missing header file (#38)
 * dws: improve error messages (#54)

### Testsuite

 * testsuite: update uses of `flux mini CMD` (#50)
 * testsuite: add tests for jobtap prolog exceptions (#51)
 * github: add 'make distcheck' to CI (#48)


flux-coral2 0.3.0 - 2023-01-31
------------------------------

Initial release of DWS/Rabbit plugins.


flux-coral2 0.2.0 - 2022-10-12
------------------------------

Fixes for Cray MPI plugins



flux-coral2 0.1.0 - 2022-08-18
------------------------------

Initial release of Cray MPI plugins


flux-coral2 0.0.0 - 2021-04-14
------------------------------

Inital release - for building and testing only
