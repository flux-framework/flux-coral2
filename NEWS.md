flux-coral2 0.28.1 - 2025-10-14
-------------------------------

### New Features
 * dws: directivebreakdown chassis support (#428)
 * dws: chassis cli plugin (#427)
 * etc: add clientmount prolog/epilog scripts (#426)

 ### Documentation
 * doc: move rabbit config guide to man5 page (#425)


flux-coral2 0.28.0 - 2025-10-09
-------------------------------

### New Features
 * dws: rename `rack` vertices to `chassis` (#406)
 * flux-slingshot: improve list subcommand (#416)
 * set SLINGSHOT_TCS in job environment (#418)

### Fixes
 * fix slingshot CXI service resource request and improve error messages
   (#408)
 * coral2_dws: add missing return statement (#405)
 * flux-slingshot clean: fall back to default pool config (#421)

### Build/Testsuite/Cleanup
 * mergify: disable temporary PR branches (#422)
 * ci: add libcxi to one of the docker builds (#415)
 * docker: run scripts from ${top_srcdir}/scripts (#417)

### Documentation
 * doc: add slingshot man pages (#419)


flux-coral2 0.27.0 - 2025-09-05
-------------------------------

### New Features
 * add flux-slingshot utility (#397)
 * add cray-slingshot shell plugin for VNI/CXI environment setup (#396)
 * add support for modprobe based startup and shutdown (#383)
 * add cray-slingshot jobtap plugin for VNI reservation (#393)

### Fixes
 * dws: stop prerun timer once state completes (#392)
 * rc: avoid unportable bashism (#398)
 * dws: upgrade to dws api v1alpha6 (#388)

### Build/Testsuite/Cleanup
 * github: update crate-ci typos version (#394)
 * testsuite: don't load deprecated barrier module (#391)
 * shell: use eventlog_wait_for in dws_environment.c (#403)


flux-coral2 0.26.0 - 2025-08-12
-------------------------------

### New Features
 * dws: `dw_failure_tolerance` attribute (#382)
 * dws: allow jobs to tolerate lost nodes and/or rabbits (#385)
 * dws: add rc1 script to drain nodes with rabbit failures (#387)

### Fixes
 * dws: exceptions raised while fetching pod logs are lost (#381)
 * dws: jobtap event resubscribe (#380)
 * dws: fix typo in systemd unit file (#378)

### Cleanup
 * dws: cleanup, drop global variable (#384)

### Build/Testsuite/Documentation
 * docs: add rabbit references (#377)
 * update slingshot doc to reflect design progress (#376)


flux-coral2 0.25.0 - 2025-06-30
-------------------------------

### New Features

 * dws: use systemd watchdog (#374)
 * dws: save pod logs to KVS (#373)
 * dws: version update (#371)
 * pmi: simplify and rename port allocator (#370)

### Build/Testsuite/Documentation
 * test: workflow tests refactor (#372)
 * doc: add design document for slingshot VNI + hw collectives (#369)


flux-coral2 0.24.0 - 2025-06-10
-------------------------------

### New Features
 * dws: drop copy offload (#361)
 * dws: status rpc (#360)
 * dws: heartbeat and profile data (#359)

### Fixes
 * cmd: fix help messages (#366)
 * dws: remove python 3.7 feature (#363)

### Documentation
 * doc: fix link and style (#362)
 * doc: document double cancellation behavior (#343)


flux-coral2 0.23.1 - 2025-05-13
-------------------------------

### New Features
 * dws: teardown timeout (#354)
 * dws: postrun timeout (#358)

### Fixes
 * dws: fix memory leak in callback (#353)
 * dws: rabbit presets fixes (#357)


flux-coral2 0.23.0 - 2025-04-29
-------------------------------

### New Features
 * dws: update dws systemstatus resource (#351)
 * dws: secret token for copy-offload (#347)

### Fixes
 * dws: reduce fluxion 'resource not found' warnings (#350)
 * dws: catch remove-finalizer exception and retry (#346)
 * dws: fix missing argument to `log_rpc_response` (#345)
 * dws: fix storage log message (#339)

### Build/Testsuite/Documentation
 * doc: `dws2jgf` man page (#349)
 * docs: rabbit man pages (#348)
 * docs: rabbit administration (#340)


flux-coral2 0.22.0 - 2025-04-04
-------------------------------

### New Features
 * cray_pals: use apinfo v5 (#310)
 * cray_pals: add libapinfo convenience library (#303)
 * dws: update to use v1alpha3 (#328)
 * dws: epilog timeout (#336)
 * dws: mark nodes with `badrabbit` property if mount fails (#338)

### Fixes
 * dws: fix add-constraint logic (#327)
 * dws: fix teardown cb (#326)
 * testsuite: fix `python` command not found (#325)
 * cray-pals: refactor and add test options (#324)
 * dws2jgf: fix properties on nodes not in DWS (#312)
 * dws: fix error logging for invalid directives (#309)
 * readthedocs: fix imghdr not found error (#315)
 * directivebreakdown: condense allocationCount (#333)

### Build/Testsuite/Documentation
 * modernize autotools usage and ensure required headers and libraries
   are found (#305)
 * github: run workflow on push to any branch (#318)
 * doc: add man pages (#314)
 * doc: add admin guide and glossary (#316)
 * doc: add references, system list (#319)
 * doc: add a rabbit ref, and improve cray-pals man page (#322)
 * doc: add references, system list (#319)
 * typos: fix typos (#334)
 * ci: generate matrix (#331)


flux-coral2 0.21.0 - 2025-03-06
-------------------------------

### New Features
 * dws: add jobid to jobtap error messages (#284)

### Fixes
 * dws: fix nnfdatamovement keyerror (#293)
 * dws: stop casting k8s resourceVersion to int (#288)
 * dws-jobtap: avoid setting aux too early (#286)
 * dws-jobtap: rpc responses (#302)
 * dws: remove create callback jobtap aux (#300)
 * dws: fix dependency error (#304)

### Cleanup
 * Cleanup: refactor workflow representation (#291)
 * `coral2_dws`: refactor badrabbit property (#281)
 * dws: drop unnecessary log messages (#298)
 * dws: storage refactor (#299)

### Build/Testsuite
 * libtap: add unit testing framework (#283)


flux-coral2 0.20.1 - 2025-02-18
-------------------------------

### New Features
 * `getrabbit`: fetch by jobid (#272)

### Fixes
 * `getrabbit`: check system config (#277)
 * dws: linting, fix undefined variable (#270)
 * dws: remove-property fix (#269)
 * `getrabbit`: jobid memo lookups (#279)

### Build/Testsuite
 * ci: updates, add lint and format checks (#273)


flux-coral2 0.20.0 - 2025-02-10
-------------------------------

### New Features
 * dws: make `exception` event interrupt data movement (#263)
 * dws: add option to tag compute nodes instead of draining (#266)
 * dws: change exclusion constraint to a property (#265)
 * `getrabbit`: list all rabbits (#264)

### Fixes
 * dws: make config error a warning (#260)
 * dws: add 'mapping' to accepted config keys (#259)


flux-coral2 0.19.1 - 2025-01-28
-------------------------------

### New Features
 * pals: make eventlog timeout configurable (#254)
 * dws: drop rabbits from dws_environment eventlog entry context (#253)
 * dws: add negative requires hostlist for down rabbits (#252)


flux-coral2 0.19.0 - 2025-01-15
-------------------------------

### New Features
 * dws: increase nnfdatamovement version to v1alpha4 (#240)
 * dws: rabbit resources jobspec update (#250)

### Fixes
 * dws2jgf: fix broken error message (#242)
 * dws: fix NameError in cleanup.py (#241)
 * Watch resourceversion fix (#248)
 * dws: fix error messages (#249)

### Build/Testsuite
 * ci(mergify): upgrade configuration to current format (#239)
 * test: container image updates (#251)


flux-coral2 0.18.0 - 2024-11-08
-------------------------------

### New Features
 * dws: rabbit preset dw strings (#235)
 * dws: rabbit config file support (#234)
 * dws: use systemconfiguration for rabbit mapping (#233)
 * dws: retry k8s failures while cleaning up workflows (#237)

### Fixes
 * dws2jgf: remove python 3.7+ feature (#232)

### Build/Testsuite
 * testsuite: add a test for big rabbit jobs (#208)


flux-coral2 0.17.1 - 2024-10-01
-------------------------------

### New Features
 * dws2jgf: drop defaults for JGF simplification

### Fixes
 * dws: fix datamovement `limit` argument


flux-coral2 0.17.0 - 2024-09-20
-------------------------------

### New Features
 * dws: saving nnfdatamovements (#216)
 * Enforce size constraints (#202)
 * dws: only allow owner to create persistent FS (#215)
 * dws: use static rabbit layout mapping for JGF (#204)
 * dws: increase nnfdatamovement version (#214)

### Fixes
 * dws: ignore bad jobids in workflows (#217)
 * dws: ignore nonexistent rabbit status field (#213)
 * dws: add error-handling cycle for kubernetes (#199)
 * dws: event watch cancel (#196)
 * dws: increase timeout of shell plugin (#194)

### Build/Testsuite
 * CI: update from el8 to el9 (#211)
 * testsuite: update expected jgf (#207)
 * testsuite: sharness sync (#206)


flux-coral2 0.16.0 - 2024-08-05
-------------------------------

### New Features
 * dws: KVS workflow timings (#187)
 * dws: handling for Lustre MGTs (#189)
 * dws: save workflow teardown timings to KVS (#191)

### Fixes
 * dws: Fix NnfDataMovement logging (#185)


flux-coral2 0.15.0 - 2024-07-17
-------------------------------

### New Features

 * dws: change rabbit memo to hostlist (#182)
 * dws: crudely enforce mdt count constraints (#181)
 * dws: add marker for prolog to enable the nnf-dm daemon (#179)
 * dws: dump datamovements to logs (#178)
 * dws: Exception log improvements (#177)
 * dws: dump workflows when killing jobs (#176)
 * dws: save workflows to KVS (#183)


flux-coral2 0.14.0 - 2024-07-04
-------------------------------

### New Features
 * dws: queue-specific draining (#173)
 * dws: enforce k8s finalizer removal (#168)
 * dws2jgf: change cluster-name logic (#164)

### Fixes
 * dws: fix Postrun workflow error hang (#169)
 * dws: change exception import path (#163)


flux-coral2 0.13.0 - 2024-05-13
-------------------------------

### New Features

 * dws: rack-parent ssds (#157)
 * dws: add option to disable Fluxion scheduling (#160)

### Fixes

 * dws: handle rabbits with no computes (#150)
 * dws: fix rabbit name manipulation logic (#151)
 * dws: k8s watch exception logic (#152)

### Testsuite

 * docker: change container hostname (#155)


flux-coral2 0.12.0 - 2024-04-10
-------------------------------

### New Features

 * dws: add support for draining Offline nodes (#140)
 * dws: add option to disable draining of Offline nodes (#149)
 * dws: k8s special exitcode (#146)
 * dws: add flux finalizer to k8s workflow resources (#141)

### Fixes

 * dws-jobtap: fix race conditions with exception-raising (#142)
 * dws: fix floating-point truncation (#143)

### Testsuite

 * test: update expected JGF after fluxion update (#147)

flux-coral2 0.11.0 - 2024-03-05
-------------------------------

### New Features

 * shell: update cray_pals to edit LD_LIBRARY_PATH when under a source
   tree (#127)
 * dws: enforce minimum rabbit allocation size (#132)
 * dws2jgf: rabbits as compute nodes (#133)
 * Non-block task placement in the cray-pals shell plugin (#128)

### Fixes
 * configure: downgrade required kubernetes version (#124)
 * dws2jgf: fix node attributes (#135)

### Testsuite
 * test: request too much rabbit storage (#130)
 * test: fix rabbit watch test failures (#134)

flux-coral2 0.10.0 - 2024-02-06
-------------------------------

### New Features

 * cray-pals: edit LD_LIBRARY_PATH to avoid Flux libpmi2.so (#122)

flux-coral2 0.9.0 - 2024-01-05
------------------------------

### New Features

 * dws: send RPCs to Fluxion to mark rabbits as up or down (#117)
 * dws2jgf: initialize Fluxion with rabbits marked as down (#120)

### Fixes

 * README: fix broken links (#116)

flux-coral2 0.8.1 - 2023-11-30
------------------------------

### New Features

 * dws: export FLUX_LOCAL_RABBIT environment variable (#105)
 * dws: disable fluxion scheduling, to be reverted in next release (#114)

### Fixes

 * build: formalize libsodium dependency (#110)
 * docker: fix kubernetes install (#113)

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

Initial release - for building and testing only
