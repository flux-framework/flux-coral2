#!/bin/sh

test_description='Test cray-slingshot jobtap plugin

Test the cray-slingshot jobtap plugin in isolation.
'

. $(dirname $0)/sharness.sh

BROKER_MODPATH=${FLUX_BUILD_DIR}/src/broker-modules/.libs
SHELL_PLUGINPATH=${FLUX_BUILD_DIR}/src/shell/plugins/.libs
JOBTAP_PLUGINPATH=${FLUX_BUILD_DIR}/src/job-manager/plugins/.libs
SSUTIL=${FLUX_BUILD_DIR}/src/cmd/flux-slingshot

# make sure the test environment is clean starting out
unset SLINGSHOT_VNIS
unset SLINGSHOT_DEVICES
unset SLINGSHOT_SVC_IDS
unset SLINGSHOT_TCS

test_under_flux 1

# Usage: flux config get | update_vni_pool idset | flux config load
# Updates cray-slingshot.vni-pool only.
update_vni_pool() {
	jq ".\"cray-slingshot\" += {\"vni-pool\":\"$1\"}"
}

##
#  Default config
##

test_expect_success 'load the cray-slingshot jobtap plugin' '
	flux jobtap load $JOBTAP_PLUGINPATH/cray-slingshot.so &&
	flux jobtap query cray-slingshot.so >nopool.json
'
test_expect_success 'query the cray-slingshot plugin' '
	flux jobtap query cray-slingshot.so >stdpool.json
'
test_expect_success 'vnipool.universe is the default range' '
	jq -e ".vnipool.universe == \"1024-65535\"" <stdpool.json
'
test_expect_success 'vnipool.free is the default range' '
	jq -e ".vnipool.free == \"1024-65535\"" <stdpool.json
'
test_expect_success 'vnipool.jobs is empty' '
	jq -e ".vnipool.jobs == {}" <stdpool.json
'
test_expect_success 'vnis-per-job = 1' '
	jq -e ".[\"vnis-per-job\"] == 1" <stdpool.json
'
test_expect_success 'vni-reserve-fatal = true' '
	jq -e ".[\"vni-reserve-fatal\"] == true" <stdpool.json
'
test_expect_success 'run a job and fetch the cray-slingshot event' '
	flux run true &&
	flux job wait-event -t 30s --format=json \
	    $(flux job last) cray-slingshot >event2.json
'
test_expect_success 'the first VNI was reserved' '
	jq -e ".context.vnis == [1024]" <event2.json
'
test_expect_success 'submit a sleep job and fetch the cray-slingshot event' '
	flux submit sleep inf &&
	flux job wait-event -t 30s --format=json \
	    $(flux job last) cray-slingshot >event3.json
'
test_expect_success 'the next VNI was reserved' '
	jq -e ".context.vnis == [1025]" <event3.json
'
test_expect_success 'query the plugin with one job running' '
	flux jobtap query cray-slingshot.so >onejob.json
'
test_expect_success 'vnipool.free reflects the one allocated VNI ' '
	jq -e ".vnipool.free == \"1024,1026-65535\"" <onejob.json
'
test_expect_success 'vnipool.jobs shows the job allocation' '
	jobid=$(flux job id --to=f58plain $(flux job last)) &&
	jq ".vnipool.jobs.$jobid == [1025]" < onejob.json
'
test_expect_success 'cancel job and wait for it to finish' '
	jobid=$(flux job last) &&
	flux cancel $jobid &&
	flux job wait-event -t 30s $jobid clean
'
test_expect_success 'query the plugin' '
	flux jobtap query cray-slingshot.so >cancel.json
'
test_expect_success 'vnipool.free is the configured range' '
	jq -e ".vnipool.free == \"1024-65535\"" <cancel.json
'
test_expect_success 'vnipool.jobs is empty' '
	jq -e ".vnipool.jobs == {}" <cancel.json
'
test_expect_success 'run a job with -o cray-slingshot.vnicount=4' '
	flux run -o cray-slingshot.vnicount=4 true &&
	flux job wait-event -t 30s --format=json \
	    $(flux job last) cray-slingshot >fourvnis.json
'
test_expect_success 'the next 4 VNIs were reserved' '
	jq -e ".context.vnis == [1026,1027,1028,1029]" <fourvnis.json
'
# N.B. if the pool were destroyed and re-created, next alloc would be 1024
test_expect_success 'reconfigure without pool change does not reset round-robin' '
	flux config get | flux config load &&
	flux run true &&
	flux job wait-event -t 30s --format=json \
	    $(flux job last) cray-slingshot >rrcheck.json &&
	jq -e ".context.vnis == [1030]" <rrcheck.json
'
test_expect_success 'run a job with -o cray-slingshot=off' '
	flux run -o cray-slingshot=off true &&
	flux job wait-event -t 30s --format=json \
	    $(flux job last) cray-slingshot >off.json
'
test_expect_success 'no VNIs were reserved' '
	jq -e ".context.vnis == []" <off.json
'
test_expect_success 'empty-reason was set' '
	jq -e ".context[\"empty-reason\"] == \"disabled by user request\"" <off.json
'
test_expect_success '-o cray-slingshot.vnicount=0 works' '
	flux run -o cray-slingshot.vnicount=0 true &&
	flux job wait-event -t 30s --format=json \
	    $(flux job last) cray-slingshot >zero.json
'
test_expect_success 'no VNIs were reserved' '
	jq -e ".context.vnis == []" <zero.json
'
test_expect_success '-o cray-slingshot.vnicount=42 fails' '
	test_must_fail flux run -o cray-slingshot.vnicount=42 true 2>max.err &&
	grep "VNI count must be within" max.err
'
test_expect_success '-o cray-slingshot.vnicount=bad fails' '
	test_must_fail flux run -o cray-slingshot.vnicount=bad true 2>opt.err &&
	grep "Expected integer, got string" opt.err
'
test_expect_success 'unknown cray-slingshot options may pass thru to shell' '
	flux run -o cray-slingshot.unknown true
'

##
#  Try vnis-per-job=0 and vni-reserve-fatal=false
##

test_expect_success 'configure vnis-per-job=0 vni-reserve-fatal=false pool=2' '
	flux config load <<-EOT
	[cray-slingshot]
	vni-pool = "1024-1025"
	vnis-per-job = 0
	vni-reserve-fatal = false
	EOT
'
test_expect_success 'run a job' '
	flux run true &&
	flux job wait-event -t 30s --format=json \
	    $(flux job last) cray-slingshot >defzero.json
'
test_expect_success 'no VNIs were reserved' '
	jq -e ".context.vnis == []" <defzero.json
'
test_expect_success 'empty-reason was set' '
	jq -e ".context[\"empty-reason\"] == \"none requested\"" <defzero.json
'
test_expect_success 'run a job with -o cray-slingshot.vnicount=3' '
	flux run -o cray-slingshot.vnicount=3 true &&
	flux job wait-event -t 30s --format=json \
	    $(flux job last) cray-slingshot >nonfatal.json
'
test_expect_success 'no VNIs were reserved' '
	jq -e ".context.vnis == []" <nonfatal.json
'
test_expect_success 'empty-reason was set' '
	jq -e ".context[\"empty-reason\"] == \"failed to reserve 3 VNIs (2 available)\"" <nonfatal.json
'

##
#  Reduce pool to only 2 VNIs with a job running that overlaps old/new pools
##

test_expect_success 'restore the default config' '
	flux config load </dev/null
'
test_expect_success 'submit a sleep job with -o cray-slingshot.vnicount=2' '
	flux submit -o cray-slingshot.vnicount=2 sleep inf &&
	flux job wait-event -t 30s --format=json \
	    $(flux job last) cray-slingshot >twovnis.json
'
test_expect_success '1024-1025 were reserved' '
	jq -e ".context.vnis == [1024,1025]" <twovnis.json
'
test_expect_success 'reconfig the pool to 1025-1026' '
	flux config get | update_vni_pool 1025-1026 | flux config load &&
	flux jobtap query cray-slingshot.so >tinypool.json
'
test_expect_success 'vnipool.universe is 1025-1026' '
	jq -e ".vnipool.universe == \"1025-1026\"" <tinypool.json
'
test_expect_success 'vnipool.free shows 1026' '
	jq -e ".vnipool.free == \"1026\"" <tinypool.json
'
test_expect_success 'vnipool.jobs shows job with 1024-1025' '
	jobid=$(flux job id --to=f58plain $(flux job last)) &&
	jq -e ".vnipool.jobs.$jobid == [1024,1025]" < tinypool.json
'
test_expect_success 'cancel job and wait for it to finish' '
	jobid=$(flux job last) &&
	flux cancel $jobid &&
	flux job wait-event -t 30s $jobid clean
'
test_expect_success 'vnipool.free shows 1025-1026' '
	flux jobtap query cray-slingshot.so >tinypool2.json &&
	jq -e ".vnipool.free == \"1025-1026\"" <tinypool2.json
'
test_expect_success 'vnipool.jobs is empty' '
	jq -e ".vnipool.jobs == {}" <tinypool2.json
'
test_expect_success '-o cray-slingshot.vnicount=2 with 2 available works' '
	flux run -o cray-slingshot.vnicount=2 true
'
test_expect_success '-o cray-slingshot.vnicount=4 with 2 available fails' '
	test_must_fail flux run -o cray-slingshot.vnicount=4 true 2>vout.err &&
	grep "failed to reserve 4 VNIs (2 available)" vout.err
'

##
#  pool is reduced to only 2 with a job running that overlaps old/new pools
##

test_done
