#!/bin/sh

test_description='Test rabbit-orphan-scan command against a live fluxion graph'

. $(dirname $0)/sharness.sh

FLUX_SIZE=2

# The "job" personality loads sched-simple; this test needs the real rc
# scripts so that sched-fluxion-resource is the scheduler.
test_under_flux ${FLUX_SIZE} full -Slog-stderr-level=1

CMD=${FLUX_SOURCE_DIR}/src/cmd/flux-rabbit-orphan-scan.py
ALLOC=${SHARNESS_TEST_SRCDIR}/scripts/fluxion_alloc.py

# This test needs no DWS K8s cluster: it drives the resource module only.
if ! test_have_prereq FLUXION; then
    skip_all='skipping orphan scan tests since fluxion is not installed'
    test_done
fi

# Each allocation made out of band keeps its resources until it is
# cancelled, so every test that makes one must undo it before the next.
cancel_alloc() {
	flux ion-resource cancel "$1" >/dev/null 2>&1 || true
}

classes() {
	jq -S -c ".summary.classes" "$1.json"
}

test_expect_success 'fluxion resource module is loaded' '
	flux module list | grep sched-fluxion-resource
'

test_expect_success 'scan of an idle instance reports nothing orphaned' '
	flux python ${CMD} -q -o idle &&
	test -s idle.json &&
	test -s idle.txt &&
	jq -e ".summary.orphaned_vertices | length == 0" idle.json &&
	jq -e ".summary.classes | length == 0" idle.json &&
	jq -e ".graph.allocated.n_vertices == 0" idle.json &&
	jq -e ".meta.housekeeping_error == null" idle.json
'

test_expect_success 'a completed job is inactive-and-clean' '
	flux submit --wait -N1 hostname &&
	flux python ${CMD} -q --settle 0 -o clean &&
	test "$(classes clean)" = "{\"inactive-and-clean\":1}" &&
	jq -e ".summary.orphaned_vertices | length == 0" clean.json &&
	jq -e ".summary.n_jobs_failed == 0" clean.json
'

test_expect_success 'a running job is classed running and left out of the table' '
	jobid=$(flux submit -N1 sleep 300) &&
	flux job wait-event -t 30 ${jobid} start &&
	flux python ${CMD} -q --settle 0 -o running &&
	jq -e ".summary.classes[\"running\"] == 1" running.json &&
	jq -e ".summary.n_running == 1" running.json &&
	jq -e ".graph.allocated.n_vertices > 0" running.json &&
	jq -e ".summary.orphaned_vertices | length == 0" running.json &&
	jq -e ".summary.allocated_unexplained_by_scanned_jobs.n_vertices == 0" \
		running.json &&
	test_must_fail grep "^ *${jobid} " running.txt &&
	flux cancel ${jobid} &&
	flux job wait-event -t 30 ${jobid} clean
'

test_expect_success 'state left for a completed job is reported as orphaned' '
	jobid=$(flux submit --wait -N1 hostname) &&
	test "$(flux python ${ALLOC} ${jobid})" = "ALLOCATED" &&
	flux python ${CMD} -q --settle 0 -o orphan &&
	jq -e ".summary.classes[\"orphan-module-still-allocated\"] == 1" orphan.json &&
	jq -e ".summary.orphaned_leaf_by_type == {\"core\": 1}" orphan.json &&
	jq -e ".summary.n_jobs_failed == 0" orphan.json &&
	grep "orphan-module-still-allocated" orphan.txt | grep -q "${jobid}" &&
	test_must_fail grep "scan incomplete" orphan.txt
'

test_expect_success 'the same state is excused while within --settle' '
	flux python ${CMD} -q --settle 3600 -o settle &&
	jq -e ".summary.classes[\"recent-orphan-module-still-allocated\"] == 1" \
		settle.json &&
	jq -e ".summary.orphaned_vertices | length == 0" settle.json
'

test_expect_success 'cleanup the orphaned allocation' '
	cancel_alloc $(flux job id --to=dec ${jobid}) &&
	flux python ${CMD} -q --settle 0 -o cleaned &&
	jq -e ".graph.allocated.n_vertices == 0" cleaned.json
'

test_expect_success 'an allocation owned by no job is reported unexplained' '
	test "$(flux python ${ALLOC} 12345)" = "ALLOCATED" &&
	flux python ${CMD} -q --settle 0 -o unexplained &&
	jq -e ".summary.allocated_unexplained_by_scanned_jobs.n_vertices > 0" \
		unexplained.json &&
	jq -e ".summary.orphaned_vertices | length == 0" unexplained.json &&
	grep -q "rerun with a larger --count" unexplained.txt &&
	test_must_fail grep "scan incomplete" unexplained.txt &&
	cancel_alloc 12345
'

test_expect_success 'a reservation for a completed job is classed reservation' '
	jobid=$(flux submit --wait -N1 hostname) &&
	# Exhaust both nodes regardless of their core counts.  The second
	# match can only come back RESERVED if the first one took every
	# node, so no separate check that the instance is full is needed:
	# flux-resource(1) reports the job manager'\''s view of the resource
	# set, which an out-of-band match never touches.
	test "$(flux python ${ALLOC} 777 --nodes ${FLUX_SIZE} --exclusive)" = "ALLOCATED" &&
	status=$(flux python ${ALLOC} ${jobid} --nodes ${FLUX_SIZE} --exclusive \
		--cmd allocate_orelse_reserve) &&
	test "${status}" = "RESERVED" &&
	flux python ${CMD} -q --settle 0 -o reserved &&
	jq -e ".summary.classes[\"reservation\"] == 1" reserved.json &&
	jq -e ".graph.reserved.n_vertices > 0" reserved.json &&
	cancel_alloc $(flux job id --to=dec ${jobid}) &&
	cancel_alloc 777
'

test_expect_success 'aggregate filters are reported with their used counts' '
	jobid=$(flux submit -N1 -n1 sleep 300) &&
	flux job wait-event -t 30 ${jobid} start &&
	flux python ${CMD} -q --settle 0 -o agfilter &&
	jq -e ".agfilter.n_filter_vertices > 0" agfilter.json &&
	jq -e ".agfilter.n_with_nonzero_used > 0" agfilter.json &&
	jq -e "[.agfilter.nonzero[] | .agfilter.core.used] | add > 0" agfilter.json &&
	grep -q "aggregate (pruning) filters" agfilter.txt &&
	flux cancel ${jobid} &&
	flux job wait-event -t 30 ${jobid} clean
'

test_expect_success '--only-with-R skips a job that never ran' '
	jobid=$(flux submit --urgency=0 -N1 hostname) &&
	flux cancel ${jobid} &&
	flux job wait-event -t 30 ${jobid} clean &&
	flux python ${CMD} -q --settle 0 -o withr &&
	flux python ${CMD} -q --settle 0 --only-with-R -o onlyr &&
	test $(jq ".summary.n_jobs_scanned" onlyr.json) \
		-lt $(jq ".summary.n_jobs_scanned" withr.json)
'

test_expect_success '--count bounds the number of inactive jobs scanned' '
	flux python ${CMD} -q --settle 0 -n 1 -o count1 &&
	jq -e ".summary.n_inactive == 1" count1.json &&
	jq -e ".meta.scanned_inactive_jobs == 1" count1.json
'

test_expect_success '--eventlog-all reads the eventlog of every job' '
	flux python ${CMD} -q --settle 0 -n 1 --eventlog-all -o evall &&
	jq -e "[.jobs[] | select(.eventlog != null)] | length > 0" evall.json
'

test_expect_success 'a scan that cannot reach the module exits 2, not 1' '
	test_expect_code 2 flux python ${CMD} -q --timeout 0.000001 -o tmo \
		2>tmo.err &&
	test_must_fail test -e tmo.json &&
	test_must_fail test -e tmo.txt &&
	grep -q "scan failed" tmo.err &&
	test_must_fail grep "Traceback" tmo.err
'

test_expect_success 'the default output prefix is used when -o is omitted' '
	flux python ${CMD} -q --settle 0 -n 1 &&
	ls flux-rabbit-orphan-scan.*.json >/dev/null &&
	ls flux-rabbit-orphan-scan.*.txt >/dev/null
'

test_expect_success 'without -q the summary is echoed to stderr' '
	flux python ${CMD} --settle 0 -n 1 -o verbose 2>verbose.err &&
	grep -q "fluxion orphan scan" verbose.err &&
	grep -q "job classification" verbose.err
'

test_done
