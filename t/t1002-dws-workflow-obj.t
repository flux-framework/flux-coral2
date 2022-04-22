#!/bin/sh

test_description='Test DWS Workflow Objection Creation'

. $(dirname $0)/sharness.sh

if test_have_prereq NO_HPE_VM; then
    skip_all='skipping DWS workflow tests due to no HPE VM'
    test_done
fi

FLUX_SIZE=2

test_under_flux ${FLUX_SIZE} job

flux setattr log-stderr-level 1

PLUGINPATH=${FLUX_BUILD_DIR}/src/job-manager/plugins/.libs
DWS_MODULE_PATH=${FLUX_BUILD_DIR}/src/modules/dws.py
RPC=${FLUX_BUILD_DIR}/t/util/rpc
CREATE_DEP_NAME="dws-create"

test_expect_success 'job-manager: load alloc-bypass plugin' '
	flux jobtap load alloc-bypass.so
'

test_expect_success 'job-manager: load dws-jobtap plugin' '
	flux jobtap load ${PLUGINPATH}/dws-jobtap.so
'

test_expect_success 'exec dws service-providing script' '
	R=$(flux R encode -r 0) &&
	jobid=$(flux mini submit \
	        --setattr=system.alloc-bypass.R="$R" \
	        -o per-resource.type=node flux python ${DWS_MODULE_PATH}) &&
	flux job wait-event -vt 15 -p guest.exec.eventlog ${jobid} shell.start
'

# This test used to close the race condition between the python process starting
# and the `dws` service being registered.  Once https://github.com/flux-framework/flux-core/issues/3821
# is implemented/closed, this can be replaced with that solution.
test_expect_success 'wait for service to register and send test RPC' '
	flux job wait-event -vt 15 -m "note=dws watchers setup" ${jobid} exception &&
	${RPC} "dws.create" 
'

test_expect_success 'job submission with valid DW string works' '
	jobid=$(flux mini submit --setattr=system.dw="#DW jobdw capacity=10KiB type=xfs name=project1" hostname) &&
	flux job wait-event -vt 5 -m description=${CREATE_DEP_NAME} \
		${jobid} dependency-add &&
	flux job wait-event -t 25 -m description=${CREATE_DEP_NAME} \
		${jobid} dependency-remove &&
	flux job wait-event -vt 5 ${jobid} clean
'

test_expect_success 'job-manager: dependency plugin works when validation fails' '
	jobid=$(flux mini submit --setattr=system.dw="foo" hostname) &&
	flux job wait-event -vt 5 -m description=${CREATE_DEP_NAME} \
		${jobid} dependency-add &&
	flux job wait-event -vt 10 ${jobid} exception
'

test_done
