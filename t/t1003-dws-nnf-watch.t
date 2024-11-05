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

test_expect_success 'smoke test to ensure storages are live' '
    kubectl get storages kind-worker2 -ojson | jq -e ".spec.mode == \"Live\"" &&
    kubectl get storages kind-worker3 -ojson | jq -e ".spec.mode == \"Live\""
'

test_expect_success 'job-manager: load alloc-bypass plugin' '
    flux jobtap load alloc-bypass.so
'

test_expect_success 'load Fluxion with rabbit resource graph' '
    echo $PYTHONPATH >&2 &&
    flux python ${FLUX_SOURCE_DIR}/src/cmd/flux-rabbitmapping.py > rabbits.json &&
    flux R encode -l | flux python ${FLUX_SOURCE_DIR}/src/cmd/flux-dws2jgf.py \
        --no-validate rabbits.json | jq . > R.local &&
    flux kvs put resource.R="$(cat R.local)" &&
    flux module remove -f sched-fluxion-qmanager &&
    flux module remove -f sched-fluxion-resource &&
    flux module reload resource &&
    flux module load sched-fluxion-resource &&
    flux module load sched-fluxion-qmanager &&
    JOBID=$(flux submit -n1 hostname) &&
    flux job wait-event -vt 2 -m status=0 ${JOBID} finish
'

test_expect_success 'rabbits default to down and are not allocated' '
    JOBID=$(flux job submit ${DATA_DIR}/rabbit-jobspec.json) &&
    test_must_fail flux job wait-event -vt 3 ${JOBID} alloc &&
    flux cancel $JOBID
'

test_expect_success 'exec Storage watching script' '
    jobid=$(flux submit \
            --setattr=system.alloc-bypass.R="$(flux R encode -r0)" --output=dws1.out --error=dws1.err \
            -o per-resource.type=node flux python ${DWS_MODULE_PATH} -vvv) &&
    flux job wait-event -vt 15 -p guest.exec.eventlog ${jobid} shell.start
'

# This test used to close the race condition between the python process starting
# and the `dws` service being registered.  Once https://github.com/flux-framework/flux-core/issues/3821
# is implemented/closed, this can be replaced with that solution.
test_expect_success 'wait for service to register and send test RPC' '
    flux job wait-event -vt 15 -m "note=dws watchers setup" ${jobid} exception &&
    ${RPC} "dws.watch_test"
'

test_expect_success 'Storages are up' '
    kubectl get storages kind-worker2 -ojson | jq -e ".spec.state == \"Enabled\"" &&
    kubectl get storages kind-worker2 -ojson | jq -e ".status.status == \"Ready\"" &&
    kubectl get storages kind-worker3 -ojson | jq -e ".spec.state == \"Enabled\"" &&
    kubectl get storages kind-worker3 -ojson | jq -e ".status.status == \"Ready\""
'

test_expect_success 'Storage watching script marks rabbits as up' '
    JOBID=$(flux job submit ${DATA_DIR}/rabbit-jobspec.json) &&
    flux job wait-event -vt 3 ${JOBID} alloc &&
    flux job wait-event -vt 3 -m status=0 ${JOBID} finish &&
    flux job attach $JOBID
'

test_expect_success 'update to the Storage status is caught by the watch' '
    kubectl patch storages kind-worker2 \
        --type merge --patch-file ${DATA_DIR}/down.yaml &&
    kubectl get storages kind-worker2 -ojson | jq -e ".spec.state == \"Disabled\"" &&
    sleep 0.2 &&
    kubectl get storages kind-worker2 -ojson | jq -e ".status.status == \"Disabled\"" &&
    kubectl patch storages kind-worker3 \
        --type merge --patch-file ${DATA_DIR}/down.yaml &&
    kubectl get storages kind-worker3 -ojson | jq -e ".spec.state == \"Disabled\"" &&
    sleep 0.2 &&
    kubectl get storages kind-worker3 -ojson | jq -e ".status.status == \"Disabled\"" &&
    sleep 3
'

test_expect_success 'rabbits now marked as down are not allocated' '
    JOBID=$(flux job submit ${DATA_DIR}/rabbit-jobspec.json) &&
    test_must_fail flux job wait-event -vt 3 ${JOBID} alloc &&
    flux cancel $JOBID
'

test_expect_success 'revert the changes to the Storage' '
    kubectl patch storages kind-worker2 \
        --type merge --patch-file ${DATA_DIR}/up.yaml &&
    kubectl get storages kind-worker2 -ojson | jq -e ".spec.state == \"Enabled\"" &&
    sleep 0.2 &&
    kubectl get storages kind-worker2 -ojson | jq -e ".status.status == \"Ready\"" &&
    kubectl patch storages kind-worker3 \
        --type merge --patch-file ${DATA_DIR}/up.yaml &&
    kubectl get storages kind-worker3 -ojson | jq -e ".spec.state == \"Enabled\"" &&
    sleep 0.2 &&
    kubectl get storages kind-worker3 -ojson | jq -e ".status.status == \"Ready\"" &&
    sleep 1
'

test_expect_success 'rabbits now marked as up and can be allocated' '
    JOBID=$(flux job submit ${DATA_DIR}/rabbit-jobspec.json) &&
    flux job wait-event -vt 3 ${JOBID} alloc &&
    flux job wait-event -vt 3 -m status=0 ${JOBID} finish &&
    flux job attach $JOBID
'

test_expect_success 'test that flux drains Offline compute nodes' '
    kubectl patch storage kind-worker2 --type=json \
        -p "[{\"op\":\"replace\", \"path\":\"/spec/mode\", \"value\": \"Testing\"}]" &&
    kubectl get storages kind-worker2 -ojson | jq -e ".spec.mode == \"Testing\"" &&
    kubectl patch storage kind-worker2 --subresource=status --type=json \
        -p "[{\"op\":\"replace\", \"path\":\"/status/access/computes/0/status\", \"value\": \"Disabled\"}]" &&
    kubectl get storages kind-worker2 -ojson | jq -e ".status.access.computes[0].status == \"Disabled\"" &&
    sleep 4 && flux resource drain | grep compute-01 &&
    flux resource undrain compute-01 &&
    test_must_fail bash -c "flux resource drain | grep compute-01"
'

test_expect_success 'exec Storage watching script with draining disabled' '
    flux cancel ${jobid} &&
    echo "
[rabbit]
drain_compute_nodes = false
    " | flux config load &&
    jobid=$(flux submit \
            --setattr=system.alloc-bypass.R="$(flux R encode -r0)" --output=dws2.out --error=dws2.err \
            -o per-resource.type=node flux python ${DWS_MODULE_PATH} -vvv) &&
    flux job wait-event -vt 15 -p guest.exec.eventlog ${jobid} shell.start
'

test_expect_success 'test that flux does not drain Offline compute nodes with draining disabled' '
    kubectl get storages kind-worker2 -ojson | jq -e ".spec.mode == \"Testing\"" &&
    kubectl patch storage kind-worker2 --subresource=status --type=json \
        -p "[{\"op\":\"replace\", \"path\":\"/status/access/computes/0/status\", \"value\": \"Ready\"}]" &&
    kubectl get storages kind-worker2 -ojson | jq -e ".status.access.computes[0].status == \"Ready\"" &&
    test_must_fail bash -c "flux resource drain | grep compute-01" &&
    kubectl patch storage kind-worker2 --subresource=status --type=json \
        -p "[{\"op\":\"replace\", \"path\":\"/status/access/computes/0/status\", \"value\": \"Disabled\"}]" &&
    kubectl get storages kind-worker2 -ojson | jq -e ".status.access.computes[0].status == \"Disabled\"" &&
    sleep 5 &&
    test_must_fail bash -c "flux resource drain | grep compute-01" &&
    test_must_fail flux job wait-event -vt 1 ${jobid} finish
'

test_expect_success 'return the storage resource to Live mode' '
    kubectl patch storage kind-worker2 --type=json \
        -p "[{\"op\":\"replace\", \"path\":\"/spec/mode\", \"value\": \"Live\"}]" &&
    kubectl get storages kind-worker2 -ojson | jq -e ".spec.mode == \"Live\"" &&
    kubectl get storages kind-worker2 -ojson | jq -e ".status.access.computes[0].status == \"Ready\""
'

test_expect_success 'exec Storage watching script with invalid --drain-queues arg' '
    flux cancel ${jobid} &&
    jobid=$(flux submit \
            --setattr=system.alloc-bypass.R="$(flux R encode -r0)" --output=dws3.out --error=dws3.err \
            -o per-resource.type=node flux python ${DWS_MODULE_PATH} -vvv \
            --drain-queues notaqueue alsonotaqueue) &&
    flux job wait-event -vt 5 ${jobid} finish &&
    test_must_fail flux job attach ${jobid}
'

test_expect_success 'configure flux with queues' '
    flux R encode -l | jq ".execution.properties.debug = \"0\"" | \
    flux python ${FLUX_SOURCE_DIR}/src/cmd/flux-dws2jgf.py \
        --no-validate rabbits.json | jq . > R.local.queues &&
    flux kvs put resource.R="$(cat R.local.queues)" &&
    flux module remove -f sched-fluxion-qmanager &&
    flux module remove -f sched-fluxion-resource &&
    flux module reload resource &&
    flux module load sched-fluxion-resource &&
    flux module load sched-fluxion-qmanager
'

test_expect_success 'exec Storage watching script with --drain-queues' '
    flux config reload &&
    jobid=$(flux submit \
            --setattr=system.alloc-bypass.R="$(flux R encode -r0)" --output=dws4.out --error=dws4.err \
            -o per-resource.type=node flux python ${DWS_MODULE_PATH} -vvv --drain-queues debug) &&
    kubectl patch storage kind-worker2 --type=json \
        -p "[{\"op\":\"replace\", \"path\":\"/spec/mode\", \"value\": \"Testing\"}]" &&
    kubectl get storages kind-worker2 -ojson | jq -e ".spec.mode == \"Testing\"" &&
    kubectl patch storage kind-worker2 --subresource=status --type=json \
        -p "[{\"op\":\"replace\", \"path\":\"/status/access/computes/0/status\", \"value\": \"Disabled\"}]" &&
    kubectl get storages kind-worker2 -ojson | jq -e ".status.access.computes[0].status == \"Disabled\"" &&
    sleep 5 && flux resource drain | grep compute-01 &&
    flux resource undrain compute-01 &&
    test_must_fail bash -c "flux resource drain | grep compute-01"
'

test_expect_success 'return the storage resource to Live mode' '
    kubectl patch storage kind-worker2 --type=json \
        -p "[{\"op\":\"replace\", \"path\":\"/spec/mode\", \"value\": \"Live\"}]" &&
    kubectl get storages kind-worker2 -ojson | jq -e ".spec.mode == \"Live\"" &&
    kubectl get storages kind-worker2 -ojson | jq -e ".status.access.computes[0].status == \"Ready\""
'

test_expect_success 'unload fluxion' '
    flux cancel ${jobid}; flux module remove sched-fluxion-qmanager &&
    flux module remove sched-fluxion-resource
'

test_done
