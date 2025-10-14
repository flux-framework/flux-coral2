#!/bin/sh

test_description='Test chassis command line plugin'

. $(dirname $0)/sharness.sh

export FLUX_CLI_PLUGINPATH=${FLUX_SOURCE_DIR}/etc/cli/plugins

test_under_flux 4 job

LOAD_FLUXION="flux module remove -f sched-simple &&
  flux module remove -f sched-fluxion-qmanager &&
  flux module remove -f sched-fluxion-resource &&
  flux module reload resource &&
  flux module load sched-fluxion-resource &&
  flux module load sched-fluxion-qmanager"

test_expect_success 'flux-run: base --help message includes plugin options' '
  flux run --help | grep -e "Options provided by plugins:" -e "--coral2-chassis"
'

test_expect_success 'flux-alloc: a job that does not provide --chassis can run' '
  flux alloc -N1 hostname
'

test_expect_success 'flux-alloc: job with --chassis=0/abc is rejected' '
  test_must_fail flux alloc --coral2-chassis=0 -N1 echo hello 2> err.out &&
  grep -e "flux-alloc: ERROR:" -e "invalid positive_integer" err.out &&
  test_must_fail flux alloc --coral2-chassis=abc -N1 echo hello 2> err.out &&
  grep -e "flux-alloc: ERROR:" -e "invalid positive_integer" err.out
'

test_expect_success 'flux-run: without JGF, job with --chassis is rejected' '
  test_must_fail flux run --coral2-chassis=1 -N1 echo hello 2> err2.out &&
  grep "flux-run: ERROR: Flux scheduler not configured to support" err2.out
'

test_expect_success 'flux-alloc: job with invalid nodecount is rejected' '
  echo {} > jgf &&
  flux R encode --local > R
  echo "
[resource]
path = \"$(pwd)/R\"
scheduling = \"$(pwd)/jgf\"
"   | flux config load &&
  test_must_fail flux alloc --coral2-chassis=1 -n1 echo hello 2> err3.out &&
  grep "flux-alloc: ERROR: --coral2-chassis option requires -N,--nodes" err3.out &&
  test_must_fail flux alloc --coral2-chassis=3 -N1 echo hello 2> err3.out &&
  grep "flux-alloc: ERROR: Nodecount (1) must be evenly divisible" err3.out
'

test_expect_success DWS_K8S 'generate actual JGF' '
  flux python ${FLUX_SOURCE_DIR}/src/cmd/flux-rabbitmapping.py > rabbits.json &&
  flux R encode -l | flux python ${FLUX_SOURCE_DIR}/src/cmd/flux-dws2jgf.py \
    --no-validate rabbits.json --only-sched | jq . > jgf2 &&
  echo "
[resource]
path = \"$(pwd)/R\"
scheduling = \"$(pwd)/jgf2\"
" | flux config load
'

test_expect_success DWS_K8S 'flux-alloc --dry: 2 chassis are divided as expected' '
  flux alloc -N6 --coral2-chassis=2 --dry hostname > jobspec &&
  jq -e ".resources[0].count == 2" jobspec &&
  jq -e ".resources[0].with[0].count == 3" jobspec
'

test_expect_success DWS_K8S 'flux-alloc --dry: 1 chassis is divided as expected' '
  flux alloc -N5 --coral2-chassis=1 --dry hostname > jobspec2 &&
  jq -e ".resources[0].count == 1" jobspec2 &&
  jq -e ".resources[0].with[0].count == 5" jobspec2
'

test_expect_success DWS_K8S 'flux-alloc: a job that provides --chassis can run' '
  flux alloc -N1 --coral2-chassis=1 hostname
'

test_expect_success DWS_K8S 'with rv1_nosched match format, --chassis fails in subinstance' '
  echo "
[resource]
path = \"$(pwd)/R\"
scheduling = \"$(pwd)/jgf2\"

[sched-fluxion-resource]
match-format = \"rv1_nosched\"
" | flux config load &&
  eval $LOAD_FLUXION &&
  test_must_fail flux alloc -N1 --coral2-chassis=1 \
    bash -c "$LOAD_FLUXION && flux run -N1 --coral2-chassis=1 true" 2> subinstance.err &&
  grep "must be a resource type known to fluxion" subinstance.err
'

test_expect_success DWS_K8S 'with rv1 match format, --chassis works in subinstance' '
  echo "
[resource]
path = \"$(pwd)/R\"
scheduling = \"$(pwd)/jgf2\"

[sched-fluxion-resource]
match-format = \"rv1\"
" | flux config load &&
  eval $LOAD_FLUXION &&
  flux alloc -N1 flux module list &&
  flux alloc -N1 --coral2-chassis=1 \
    bash -c "$LOAD_FLUXION && flux run -N1 --coral2-chassis=1 true"
'

test_expect_success DWS_K8S 'remove fluxion' '
  flux module remove -f sched-fluxion-qmanager &&
  flux module remove -f sched-fluxion-resource
'

test_done
