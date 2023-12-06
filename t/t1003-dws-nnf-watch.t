#!/bin/sh

test_description='Test Watching Storages in K8s'

. $(dirname $0)/sharness.sh

FLUX_SIZE=2

test_under_flux ${FLUX_SIZE} job

flux setattr log-stderr-level 1

DATA_DIR=${SHARNESS_TEST_SRCDIR}/data/nnf-watch/
DWS_MODULE_PATH=${FLUX_SOURCE_DIR}/src/modules/coral2_dws.py
RPC=${FLUX_BUILD_DIR}/t/util/rpc

if test_have_prereq NO_DWS_K8S; then
    skip_all='skipping DWS workflow tests due to no DWS K8s'
    test_done
fi

test_expect_success 'job-manager: load alloc-bypass plugin' '
	flux jobtap load alloc-bypass.so
'

test_expect_success 'exec Storage watching script' '
	echo $PYTHONPATH >&2 &&
	flux R encode -l | flux python ${FLUX_SOURCE_DIR}/src/cmd/flux-dws2jgf.py \
	--no-validate | jq . > R.local &&
	jobid=$(flux submit \
	        --setattr=system.alloc-bypass.R="$(cat R.local)" --output=dws.out --error=dws.err \
	        -o per-resource.type=node flux python ${DWS_MODULE_PATH} -vvv -rR.local) &&
	flux job wait-event -vt 15 -p guest.exec.eventlog ${jobid} shell.start
'

# This test used to close the race condition between the python process starting
# and the `dws` service being registered.  Once https://github.com/flux-framework/flux-core/issues/3821
# is implemented/closed, this can be replaced with that solution.
test_expect_success 'wait for service to register and send test RPC' '
	flux job wait-event -vt 15 -m "note=dws watchers setup" ${jobid} exception &&
	${RPC} "dws.watch_test"
'

test_expect_success 'updating the Storage status is caught by the watch' '
	kubectl patch storages kind-worker2 \
		--type merge --patch-file ${DATA_DIR}/down.yaml &&
	kubectl get storages kind-worker2 -ojson | jq -e ".spec.state == \"Disabled\"" &&
	kubectl get storages kind-worker2 -ojson | jq -e ".status.status == \"Disabled\"" &&
	sleep 2 &&
	grep "kind-worker2 as down, status is Disabled" dws.err
'

test_expect_success 'revert the changes to the Storage' '
	kubectl patch storages kind-worker2 \
		--type merge --patch-file ${DATA_DIR}/up.yaml &&
	kubectl get storages kind-worker2 -ojson | jq -e ".spec.state == \"Enabled\"" &&
	kubectl get storages kind-worker2 -ojson | jq -e ".status.status == \"Ready\"" &&
	sleep 2 &&
	flux cancel $jobid &&
	tail -n1 dws.err | grep "kind-worker2 as up"
'

test_done
