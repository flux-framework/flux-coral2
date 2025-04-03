#!/bin/sh

test_description='Test dws-jobtap plugin with fake coral2_dws.py'

. $(dirname $0)/sharness.sh

test_under_flux 2 job

flux setattr log-stderr-level 1

PLUGINPATH=${FLUX_BUILD_DIR}/src/job-manager/plugins/.libs
DWS_SCRIPT=${SHARNESS_TEST_SRCDIR}/dws-dependencies/coral2_dws.py
DEPENDENCY_NAME="dws-create"
PROLOG_NAME="dws-setup"
EPILOG_NAME="dws-epilog"

test_expect_success 'job-manager: load dws-jobtap plugin' '
	flux jobtap load ${PLUGINPATH}/dws-jobtap.so &&
	flux dmesg | grep "dws: epilog timeout = 0.0" &&
	flux dmesg | grep "dws: failed to unpack config" &&
	flux jobtap remove dws-jobtap.so &&
	flux dmesg --clear &&
	flux jobtap load ${PLUGINPATH}/dws-jobtap.so epilog-timeout=-1.0 &&
	flux dmesg | grep "dws: epilog timeout = -1." &&
	flux dmesg | test_must_fail grep "dws: failed to unpack config"
'

test_expect_success 'job-manager: dws jobtap plugin works when coral2_dws is absent' '
	jobid=$(flux submit --setattr=system.dw="foo" hostname) &&
	flux job wait-event -vt 5 -m description=${DEPENDENCY_NAME} \
		${jobid} dependency-add &&
	flux job wait-event -vt 1 -m severity=0 ${jobid} exception &&
	flux job wait-event -vt 1 ${jobid} clean
'

test_expect_success 'job-manager: dws jobtap plugin works when RPCs succeed' '
	create_jobid=$(flux submit -t 8 --output=dws1.out --error=dws1.out \
		flux python ${DWS_SCRIPT}) &&
	flux job wait-event -vt 15 -p guest.exec.eventlog ${create_jobid} shell.start &&
	jobid=$(flux submit --setattr=system.dw="foo" hostname) &&
	flux job wait-event -vt 5 -m description=${DEPENDENCY_NAME} \
		${jobid} dependency-add &&
	flux job wait-event -t 5 -m description=${DEPENDENCY_NAME} \
		${jobid} dependency-remove &&
	flux job wait-event -vt 5 -m description=${PROLOG_NAME} \
		${jobid} prolog-start &&
	flux job wait-event -vt 5 -m description=${PROLOG_NAME} \
		${jobid} prolog-finish &&
	flux job wait-event -vt 5 -m description=${EPILOG_NAME} \
		${jobid} epilog-start &&
	flux job wait-event -vt 5 -m description=${EPILOG_NAME} \
		${jobid} epilog-finish &&
	flux job wait-event -vt 5 ${jobid} clean &&
	flux job wait-event -vt 1 -m status=0 ${jobid} finish &&
	flux job wait-event -vt 5 ${create_jobid} clean
'

test_expect_success 'job-manager: dws jobtap plugin works when creation RPC fails' '
	create_jobid=$(flux submit -t 8 --output=dws2.out --error=dws2.out \
		flux python ${DWS_SCRIPT} --create-fail) &&
	flux job wait-event -vt 15 -p guest.exec.eventlog ${create_jobid} shell.start &&
	jobid=$(flux submit --setattr=system.dw="foo" hostname) &&
	flux job wait-event -vt 5 -m description=${DEPENDENCY_NAME} \
		${jobid} dependency-add &&
	flux job wait-event -vt 1 ${jobid} exception &&
	flux job wait-event -vt 5 ${jobid} clean &&
	flux job wait-event -vt 5 ${create_jobid} clean
'

test_expect_success 'job-manager: dws jobtap plugin works when setup RPC fails' '
	create_jobid=$(flux submit -t 8 --output=dws3.out --error=dws3.out \
		flux python ${DWS_SCRIPT} --setup-fail) &&
	flux job wait-event -vt 15 -p guest.exec.eventlog ${create_jobid} shell.start &&
	jobid=$(flux submit --setattr=system.dw="foo" hostname) &&
	flux job wait-event -vt 5 -m description=${PROLOG_NAME} \
		${jobid} prolog-start &&
	flux job wait-event -vt 5 -m description=${PROLOG_NAME} -m status=1 \
		${jobid} prolog-finish &&
	flux job wait-event -vt 1 ${jobid} exception &&
	flux job wait-event -vt 5 ${jobid} clean &&
	flux job wait-event -vt 5 ${create_jobid} clean
'

test_expect_success 'job-manager: dws jobtap plugin works when post_run RPC fails' '
	create_jobid=$(flux submit -t 8 --output=dws3.out --error=dws3.out \
		flux python ${DWS_SCRIPT} --post-run-fail) &&
	flux job wait-event -vt 15 -p guest.exec.eventlog ${create_jobid} shell.start &&
	jobid=$(flux submit --setattr=system.dw="foo" hostname) &&
	flux job wait-event -vt 5 -m description=${EPILOG_NAME} \
		${jobid} epilog-start &&
	flux job wait-event -vt 5 -m description=${EPILOG_NAME} -m status=1 \
		${jobid} epilog-finish &&
	flux job wait-event -vt 1 ${jobid} exception &&
	flux job wait-event -vt 5 ${jobid} clean &&
	flux job wait-event -vt 5 ${create_jobid} clean
'

test_expect_success 'job-manager: dws jobtap plugin works when job hits exception during prolog' '
	create_jobid=$(flux submit -t 8 --output=dws4.out --error=dws4.out \
		flux python ${DWS_SCRIPT} --setup-hang) &&
	flux job wait-event -vt 15 -p guest.exec.eventlog ${create_jobid} shell.start &&
	jobid=$(flux submit --setattr=system.dw="foo" hostname) &&
	flux job wait-event -vt 5 -m description=${PROLOG_NAME} \
		${jobid} prolog-start &&
	flux cancel $jobid
	flux job wait-event -vt 1 ${jobid} exception &&
	flux job wait-event -vt 5 -m description=${PROLOG_NAME} -m status=1 \
		${jobid} prolog-finish &&
	flux job wait-event -vt 5 -m description=${EPILOG_NAME} \
		${jobid} epilog-start &&
	flux job wait-event -vt 5 -m description=${EPILOG_NAME} \
		${jobid} epilog-finish &&
	flux job wait-event -vt 5 ${jobid} clean &&
	flux job wait-event -vt 5 ${create_jobid} clean
'

test_expect_success 'job-manager: dws jobtap plugin works when job hits exception during epilog' '
	create_jobid=$(flux submit -t 8 --output=dws5.out --error=dws5.out \
		flux python ${DWS_SCRIPT} --teardown-hang) &&
	flux job wait-event -vt 15 -p guest.exec.eventlog ${create_jobid} shell.start &&
	jobid=$(flux submit --setattr=system.dw="foo" hostname) &&
	flux job wait-event -vt 5 -m description=${EPILOG_NAME} \
		${jobid} epilog-start &&
	flux cancel $jobid &&
	flux job wait-event -vt 1 ${jobid} exception &&
	flux job wait-event -vt 5 -m description=${EPILOG_NAME} -m status=0 \
		${jobid} epilog-finish &&
	flux job wait-event -vt 5 ${jobid} clean &&
	flux job wait-event -vt 5 ${create_jobid} clean &&
	test_must_fail flux job attach ${jobid}
'

test_expect_success 'job-manager: dws jobtap plugin works when reloaded' '
	create_jobid=$(flux submit -t 8 --output=dws6.out --error=dws6.out \
		flux python ${DWS_SCRIPT}) &&
	flux job wait-event -vt 15 -p guest.exec.eventlog ${create_jobid} shell.start &&
	flux queue stop --all &&
	jobid=$(flux submit --setattr=system.dw="foo" hostname) &&
	flux job wait-event -vt 5 -m description=${DEPENDENCY_NAME} \
		${jobid} dependency-add &&
	flux job wait-event -t 5 -m description=${DEPENDENCY_NAME} \
		${jobid} dependency-remove &&
	test_must_fail flux job wait-event -vt 2 -m description=${PROLOG_NAME} \
		${jobid} prolog-start &&
	flux jobtap remove dws-jobtap.so &&
	flux jobtap load ${PLUGINPATH}/dws-jobtap.so &&
	flux queue start --all &&
	flux job wait-event -vt 5 -m description=${PROLOG_NAME} \
		${jobid} prolog-start &&
	flux job wait-event -vt 5 -m description=${PROLOG_NAME} \
		${jobid} prolog-finish &&
	flux job wait-event -vt 5 -m description=${EPILOG_NAME} \
		${jobid} epilog-start &&
	flux job wait-event -vt 5 -m description=${EPILOG_NAME} \
		${jobid} epilog-finish &&
	flux job wait-event -vt 1 -m status=0 ${jobid} finish &&
	flux job wait-event -vt 5 ${jobid} clean &&
	flux job wait-event -vt 5 ${create_jobid} clean
'

test_expect_success 'job-manager: dws jobtap plugin adds new constraints when not present' '
	create_jobid=$(flux submit -t 8 --output=dws7.out --error=dws7.out \
		flux python ${DWS_SCRIPT} --exclude=foobar) &&
	flux job wait-event -vt 15 -p guest.exec.eventlog ${create_jobid} shell.start &&
	jobid=$(flux submit --setattr=system.dw="foo" hostname) &&
	flux job wait-event -vt 5 -m description=${DEPENDENCY_NAME} \
		${jobid} dependency-add &&
	flux job wait-event -t 5 -m description=${DEPENDENCY_NAME} \
		${jobid} dependency-remove &&
	flux job wait-event -t 5 -fjson ${jobid} jobspec-update | \
		jq -e ".context.\"attributes.system.constraints\".not" &&
	flux job wait-event -vt 5 -m description=${PROLOG_NAME} \
		${jobid} prolog-start &&
	flux job wait-event -vt 5 -m description=${PROLOG_NAME} \
		${jobid} prolog-finish &&
	flux job wait-event -vt 5 -m description=${EPILOG_NAME} \
		${jobid} epilog-start &&
	flux job wait-event -vt 5 -m description=${EPILOG_NAME} \
		${jobid} epilog-finish &&
	flux job wait-event -vt 5 ${jobid} clean &&
	flux job wait-event -vt 1 -m status=0 ${jobid} finish &&
	flux job wait-event -vt 5 ${create_jobid} clean
'

test_expect_success 'job-manager: dws jobtap plugin updates existing constraints' '
	create_jobid=$(flux submit -t 8 --output=dws8.out --error=dws8.out \
		flux python ${DWS_SCRIPT} --exclude=badrabbit) &&
	flux job wait-event -vt 15 -p guest.exec.eventlog ${create_jobid} shell.start &&
	jobid=$(flux submit --setattr=system.dw="foo" \
		--requires="-foo and hosts:$(hostname)" hostname) &&
	flux job wait-event -vt 5 -m description=${DEPENDENCY_NAME} \
		${jobid} dependency-add &&
	flux job wait-event -t 5 -m description=${DEPENDENCY_NAME} \
		${jobid} dependency-remove &&
	flux job wait-event -t 5 -fjson ${jobid} jobspec-update | \
		jq -e ".context.\"attributes.system.constraints\".and" &&
	flux job wait-event -vt 5 -m description=${PROLOG_NAME} \
		${jobid} prolog-start &&
	flux job wait-event -vt 5 -m description=${PROLOG_NAME} \
		${jobid} prolog-finish &&
	flux job wait-event -vt 5 -m description=${EPILOG_NAME} \
		${jobid} epilog-start &&
	flux job wait-event -vt 5 -m description=${EPILOG_NAME} \
		${jobid} epilog-finish &&
	flux job wait-event -vt 5 ${jobid} clean &&
	flux job wait-event -vt 1 -m status=0 ${jobid} finish &&
	flux job wait-event -vt 5 ${create_jobid} clean
'

test_expect_success 'job-manager: dws jobtap plugin handles --requires=^property' '
	create_jobid=$(flux submit -t 8 --output=dws9.out --error=dws9.out \
		flux python ${DWS_SCRIPT} --exclude=foobar) &&
	flux job wait-event -vt 15 -p guest.exec.eventlog ${create_jobid} shell.start &&
	jobid=$(flux submit --setattr=system.dw="foo" --requires=^barbaz hostname) &&
	flux job wait-event -vt 5 -m description=${DEPENDENCY_NAME} \
		${jobid} dependency-add &&
	flux job wait-event -t 5 -m description=${DEPENDENCY_NAME} \
		${jobid} dependency-remove &&
	flux job wait-event -t 5 -fjson ${jobid} jobspec-update | \
		jq -e ".context.\"attributes.system.constraints\".and" &&
	flux job wait-event -vt 5 -m description=${PROLOG_NAME} \
		${jobid} prolog-start &&
	flux job wait-event -vt 5 -m description=${PROLOG_NAME} \
		${jobid} prolog-finish &&
	flux job wait-event -vt 5 -m description=${EPILOG_NAME} \
		${jobid} epilog-start &&
	flux job wait-event -vt 5 -m description=${EPILOG_NAME} \
		${jobid} epilog-finish &&
	flux job wait-event -vt 5 ${jobid} clean &&
	flux job wait-event -vt 1 -m status=0 ${jobid} finish &&
	flux job wait-event -vt 5 ${create_jobid} clean
'

test_expect_success 'job-manager: dws jobtap plugin works if epilog timeout error is posted manually' '
	create_jobid=$(flux submit -t 8 --output=dws10.out --error=dws10.out \
		flux python ${DWS_SCRIPT} --teardown-hang) &&
	flux job wait-event -vt 15 -p guest.exec.eventlog ${create_jobid} shell.start &&
	jobid=$(flux submit --setattr=system.dw="foo" hostname) &&
	flux job wait-event -vt 5 -m description=${EPILOG_NAME} \
		${jobid} epilog-start &&
	flux post-job-event $jobid exception type=dws-epilog-timeout severity=0 &&
	flux job wait-event -vt 5 -m type=dws-epilog-timeout ${jobid} exception &&
	flux job wait-event -vt 5 -m description=${EPILOG_NAME} -m status=1 \
		${jobid} epilog-finish &&
	flux job wait-event -vt 5 ${jobid} clean &&
	flux job wait-event -vt 5 ${create_jobid} clean &&
	grep "Received dws.abort RPC" dws10.out &&
	test_must_fail flux job attach ${jobid}
'

test_expect_success 'job-manager: load dws-jobtap plugin with epilog timeout > 0' '
	flux jobtap remove dws-jobtap.so &&
	flux dmesg --clear &&
	flux jobtap load ${PLUGINPATH}/dws-jobtap.so epilog-timeout=0.1 &&
	flux dmesg | grep "dws: epilog timeout = 0.1" &&
	flux dmesg | test_must_fail grep "dws: failed to unpack config"
'

test_expect_success 'job-manager: dws jobtap plugin works when job hits epilog timeout' '
	create_jobid=$(flux submit -t 8 --output=dws11.out --error=dws11.out \
		flux python ${DWS_SCRIPT} --teardown-hang) &&
	flux job wait-event -vt 15 -p guest.exec.eventlog ${create_jobid} shell.start &&
	jobid=$(flux submit --setattr=system.dw="foo" hostname) &&
	flux job wait-event -vt 5 -m description=${EPILOG_NAME} \
		${jobid} epilog-start &&
	flux job wait-event -vt 5 -m type=dws-epilog-timeout ${jobid} exception &&
	flux job wait-event -vt 5 -m description=${EPILOG_NAME} -m status=1 \
		${jobid} epilog-finish &&
	flux job wait-event -vt 5 ${jobid} clean &&
	flux job wait-event -vt 5 ${create_jobid} clean &&
	grep "Received dws.abort RPC" dws11.out &&
	test_must_fail flux job attach ${jobid}
'

test_done
