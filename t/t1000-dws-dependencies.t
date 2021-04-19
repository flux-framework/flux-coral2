#!/bin/sh

test_description='Test job dependencies'

. $(dirname $0)/sharness.sh

test_under_flux 2 job

flux setattr log-stderr-level 1

PLUGINPATH=${FLUX_BUILD_DIR}/src/job-manager/plugins/.libs
VALIDATE_SCRIPT=${SHARNESS_TEST_SRCDIR}/dws-dependencies/dep-validate.py

test_expect_success 'job-manager: load dws-jobtap plugin' '
	flux jobtap load ${PLUGINPATH}/dws-jobtap.so
'
test_expect_success 'job-manager: dependency plugin works when validation succeeds' '
	validate_jobid=$(flux mini submit -t 8 flux python ${VALIDATE_SCRIPT}) &&
	flux job wait-event -vt 15 -p guest.exec.eventlog ${validate_jobid} shell.start &&
	jobid=$(flux mini submit --setattr=system.dw="foo" hostname) &&
	flux job wait-event -vt 5 -m description=dws-test \
		${jobid} dependency-add &&
	flux job wait-event -t 5 -m description=dws-test \
		${jobid} dependency-remove &&
	flux job wait-event -vt 15 ${jobid} clean &&
	flux job wait-event -vt 5 ${validate_jobid} clean
'

test_expect_success 'job-manager: dependency plugin works when validation fails' '
	validate_jobid=$(flux mini submit -t 8 flux python ${VALIDATE_SCRIPT} --fail) &&
	flux job wait-event -vt 15 -p guest.exec.eventlog ${validate_jobid} shell.start &&
	jobid=$(flux mini submit --setattr=system.dw="foo" hostname) &&
	flux job wait-event -vt 5 -m description=dws-test \
		${jobid} dependency-add &&
	flux job wait-event -vt 1 ${jobid} exception &&
	flux job wait-event -vt 5 ${validate_jobid} clean
'

test_done
