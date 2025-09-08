#!/bin/sh

test_description='Test dws2jgf command'

. $(dirname $0)/sharness.sh

FLUX_SIZE=2

test_under_flux ${FLUX_SIZE} job

flux setattr log-stderr-level 1

CMD=${FLUX_SOURCE_DIR}/src/cmd/flux-dws2jgf.py
DATADIR=${SHARNESS_TEST_SRCDIR}/data/dws2jgf

export FLUX_PYCLI_LOGLEVEL=10
# Have to set so kubernetes can automatically detect the ~/.kube/config
export KUBECONFIG=${REAL_HOME}/.kube/config

if test_have_prereq NO_DWS_K8S; then
    skip_all='skipping DWS workflow tests due to no DWS K8s'
    test_done
fi
if ! test_have_prereq FLUXION; then
    skip_all='skipping tests since fluxion is not installed'
    test_done
fi

test_expect_success 'smoke test to ensure the storage resources are expected' '
	test $(kubectl get storages | wc -l) -eq 3 &&
	kubectl get storages kind-worker2 -ojson | jq -e ".status.access.computes | length == 3" &&
	kubectl get storages kind-worker2 -ojson | jq -e ".status.access.computes[0].name == \"compute-01\"" &&
	kubectl get storages kind-worker2 -ojson | jq -e ".status.access.computes[1].name == \"compute-02\"" &&
	kubectl get storages kind-worker2 -ojson | jq -e ".status.access.computes[2].name == \"compute-03\"" &&
	kubectl get storages kind-worker3 -ojson | jq -e ".status.access.computes | length == 1" &&
	kubectl get storages kind-worker3 -ojson | jq -e ".status.access.computes[0].name == \"compute-04\"" &&
	test $(hostname) = compute-01
'

test_expect_success 'flux-rabbitmapping outputs expected mapping' '
	flux python ${FLUX_SOURCE_DIR}/src/cmd/flux-rabbitmapping.py -i2 > rabbits.json
	test_cmp ${DATADIR}/rabbits.json rabbits.json
'

test_expect_success 'flux-dws2jgf.py outputs expected JGF for single compute node' '
	flux R encode -Hcompute-01 | flux python ${CMD} --no-validate --cluster-name=ElCapitan \
		rabbits.json | jq . > actual-compute-01.jgf &&
	test_cmp ${DATADIR}/expected-compute-01.jgf actual-compute-01.jgf
'

test_expect_success 'flux-dws2jgf.py outputs expected JGF for multiple compute nodes' '
	flux R encode -Hcompute-[01-04] -c0-4 | flux python ${CMD} --no-validate --cluster-name=ElCapitan \
		rabbits.json | jq . > actual-compute-01-04.jgf &&
	test_cmp ${DATADIR}/expected-compute-01-04.jgf actual-compute-01-04.jgf
'

test_expect_success 'flux-dws2jgf.py outputs expected JGF for compute nodes not in DWS' '
	flux R encode -Hcompute-[01-04],nodws[0-5] -c0-4 | \
	flux python ${CMD} --no-validate rabbits.json | jq . > actual-compute-01-nodws.jgf &&
	test_cmp ${DATADIR}/expected-compute-01-nodws.jgf actual-compute-01-nodws.jgf
'

test_expect_success 'flux-dws2jgf.py handles properties correctly' '
	cat ${DATADIR}/R-properties | \
	flux python ${CMD} --no-validate rabbits.json | jq . > actual-properties.jgf &&
	test_cmp ${DATADIR}/expected-properties.jgf actual-properties.jgf
'

test_expect_success 'flux-dws2jgf.py can read from a config file' '
	cat >resourceconf.toml <<-EOT &&
	[[resource.config]]
	hosts = "compute-01"
	cores = "0-4"
	EOT
	flux python ${CMD} --no-validate --from-config resourceconf.toml rabbits.json | jq . > actual-configfile.jgf &&
	test_cmp ${DATADIR}/expected-configfile.jgf actual-configfile.jgf
'

test_expect_success 'flux-dws2jgf.py reading from config file is same as parse-config' '
	flux R parse-config resourceconf.toml | \
	flux python ${CMD} --no-validate rabbits.json | jq . > actual-configfile-parseconfig.jgf &&
	test_cmp ${DATADIR}/expected-configfile.jgf actual-configfile-parseconfig.jgf
'

test_expect_success 'fluxion rejects a chassis/rabbit job when no rabbits are recognized' '
	flux module remove -f sched-fluxion-qmanager &&
	flux module remove -f sched-fluxion-resource &&
	flux module reload resource &&
	flux module load sched-fluxion-resource &&
	flux module load sched-fluxion-qmanager &&
	JOBID=$(flux job submit ${DATADIR}/rabbit-jobspec.json) &&
	test_must_fail flux job attach $JOBID &&
	flux job wait-event -vt 2 ${JOBID} exception
'

test_expect_success 'fluxion can be loaded with output of dws2jgf' '
	flux run -n1 hostname &&
	flux R encode -l | flux python ${CMD} --no-validate --cluster-name=ElCapitan rabbits.json \
		| jq . > R.local &&
	flux kvs put resource.R="$(cat R.local)" &&
	flux module list &&
	flux module remove -f sched-fluxion-qmanager &&
	flux module remove -f sched-fluxion-resource &&
	flux module reload resource &&
	flux module load sched-fluxion-resource &&
	flux module load sched-fluxion-qmanager &&
	JOBID=$(flux submit -n1 hostname) &&
	flux job wait-event -vt 2 -m status=0 ${JOBID} finish
'

test_expect_success 'fluxion does not allocate a chassis/rabbit job after adding down rabbits' '
	JOBID=$(flux job submit ${DATADIR}/rabbit-jobspec.json) &&
	test_must_fail flux job wait-event -vt 2 ${JOBID} alloc &&
	flux cancel $JOBID
'

test_expect_success 'fluxion allocates a chassis/rabbit job when rabbit is up' '
	${SHARNESS_TEST_SRCDIR}/scripts/set_status.py /ElCapitan/chassis0/ssd0 up &&
	JOBID=$(flux job submit ${DATADIR}/rabbit-jobspec.json) &&
	flux job wait-event -vt 2 -m status=0 ${JOBID} finish &&
	flux job attach $JOBID &&
	flux module remove sched-fluxion-qmanager &&
	flux module remove sched-fluxion-resource
'

test_done
