#!/bin/sh

test_description='Test DWS Workflow Objection Creation'

. $(dirname $0)/sharness.sh

if test_have_prereq NO_DWS_K8S; then
    skip_all='skipping DWS workflow tests due to no DWS K8s'
    test_done
fi

FLUX_SIZE=2

test_under_flux ${FLUX_SIZE} job

flux setattr log-stderr-level 1

PLUGINPATH=${FLUX_BUILD_DIR}/src/job-manager/plugins/.libs
DWS_MODULE_PATH=${FLUX_SOURCE_DIR}/src/modules/coral2_dws.py
RPC=${FLUX_BUILD_DIR}/t/util/rpc
CREATE_DEP_NAME="dws-create"
PROLOG_NAME="dws-setup"
EPILOG_NAME="dws-epilog"
DATADIR=${SHARNESS_TEST_SRCDIR}/data/workflow-obj

# TODO: load alloc-bypass plugin once it is working again (flux-core #4900)
# test_expect_success 'job-manager: load alloc-bypass plugin' '
# 	flux jobtap load alloc-bypass.so
# '

test_expect_success 'job-manager: load dws-jobtap plugin' '
	flux jobtap load ${PLUGINPATH}/dws-jobtap.so
'

test_expect_success 'exec dws service-providing script' '
	R=$(flux R encode -r 0) &&
	jobid=$(flux submit \
	        --setattr=system.alloc-bypass.R="$R" \
	        -o per-resource.type=node --output=dws.out --error=dws.err \
	        python ${DWS_MODULE_PATH} -e1) &&
	flux job wait-event -vt 15 -p guest.exec.eventlog ${jobid} shell.start
'

# This test used to close the race condition between the python process starting
# and the `dws` service being registered.  Once https://github.com/flux-framework/flux-core/issues/3821
# is implemented/closed, this can be replaced with that solution.
test_expect_success 'wait for service to register and send test RPC' '
	flux job wait-event -vt 15 -m "note=dws watchers setup" ${jobid} exception &&
	${RPC} "dws.create" 
'

test_expect_success 'job submission without DW string works' '
	jobid=$(flux submit -n1 /bin/true) &&
	flux job wait-event -vt 25 ${jobid} finish &&
	test_must_fail flux job wait-event -vt 5 -m description=${CREATE_DEP_NAME} \
		${jobid} dependency-add
'

test_expect_success 'job submission with valid DW string works' '
	jobid=$(flux submit --setattr=system.dw="#DW jobdw capacity=10KiB type=xfs name=project1" \
		-N1 -n1 hostname) &&
	flux job wait-event -vt 10 -m description=${CREATE_DEP_NAME} \
		${jobid} dependency-add &&
	flux job wait-event -t 10 -m description=${CREATE_DEP_NAME} \
		${jobid} dependency-remove &&
	flux job wait-event -vt 5 ${jobid} depend &&
	flux job wait-event -vt 5 ${jobid} priority &&
	flux job wait-event -vt 5 -m description=${PROLOG_NAME} \
		${jobid} prolog-start &&
	flux job wait-event -vt 5 -m description=${PROLOG_NAME} \
		${jobid} prolog-finish &&
	flux job wait-event -vt 5 -m description=${EPILOG_NAME} \
		${jobid} epilog-start &&
	flux job wait-event -vt 5 -m description=${EPILOG_NAME} \
		${jobid} epilog-finish &&
	flux job wait-event -vt 5 ${jobid} clean
'

test_expect_success 'job submission with multiple valid DW strings on different lines works' '
	jobid=$(flux submit --setattr=system.dw="
											 #DW jobdw capacity=10KiB type=xfs name=project1

											 #DW jobdw capacity=20KiB type=gfs2 name=project2" \
		    -N1 -n1 hostname) &&
	flux job wait-event -vt 10 -m description=${CREATE_DEP_NAME} \
		${jobid} dependency-add &&
	flux job wait-event -t 10 -m description=${CREATE_DEP_NAME} \
		${jobid} dependency-remove &&
	flux job wait-event -vt 5 ${jobid} depend &&
	flux job wait-event -vt 5 ${jobid} priority &&
	flux job wait-event -vt 5 -m description=${PROLOG_NAME} \
		${jobid} prolog-start &&
	flux job wait-event -vt 5 -m description=${PROLOG_NAME} \
		${jobid} prolog-finish &&
	flux job wait-event -vt 5 -m description=${EPILOG_NAME} \
		${jobid} epilog-start &&
	flux job wait-event -vt 5 -m description=${EPILOG_NAME} \
		${jobid} epilog-finish &&
	flux job wait-event -vt 5 ${jobid} clean
'

test_expect_success 'job submission with multiple valid DW strings on the same line works' '
	jobid=$(flux submit --setattr=system.dw="#DW jobdw capacity=10KiB type=xfs name=project1 \
			#DW jobdw capacity=20KiB type=gfs2 name=project2" \
		-N1 -n1 hostname) &&
	flux job wait-event -vt 10 -m description=${CREATE_DEP_NAME} \
		${jobid} dependency-add &&
	flux job wait-event -t 10 -m description=${CREATE_DEP_NAME} \
		${jobid} dependency-remove &&
	flux job wait-event -vt 5 ${jobid} depend &&
	flux job wait-event -vt 5 ${jobid} priority &&
	flux job wait-event -vt 5 -m description=${PROLOG_NAME} \
		${jobid} prolog-start &&
	flux job wait-event -vt 5 -m description=${PROLOG_NAME} \
		${jobid} prolog-finish &&
	flux job wait-event -vt 5 -m description=${EPILOG_NAME} \
		${jobid} epilog-start &&
	flux job wait-event -vt 5 -m description=${EPILOG_NAME} \
		${jobid} epilog-finish &&
	flux job wait-event -vt 5 ${jobid} clean
'

test_expect_success 'job submission with multiple valid DW strings in a JSON file works' '
	jobid=$(flux submit --setattr=^system.dw="${DATADIR}/two_directives.json" \
		    -N1 -n1 hostname) &&
	flux job wait-event -vt 10 -m description=${CREATE_DEP_NAME} \
		${jobid} dependency-add &&
	flux job wait-event -t 10 -m description=${CREATE_DEP_NAME} \
		${jobid} dependency-remove &&
	flux job wait-event -vt 5 ${jobid} depend &&
	flux job wait-event -vt 5 ${jobid} priority &&
	flux job wait-event -vt 5 -m description=${PROLOG_NAME} \
		${jobid} prolog-start &&
	flux job wait-event -vt 5 -m description=${PROLOG_NAME} \
		${jobid} prolog-finish &&
	flux job wait-event -vt 5 -m description=${EPILOG_NAME} \
		${jobid} epilog-start &&
	flux job wait-event -vt 5 -m description=${EPILOG_NAME} \
		${jobid} epilog-finish &&
	flux job wait-event -vt 5 ${jobid} clean
'

test_expect_success 'job-manager: dependency plugin works when validation fails' '
	jobid=$(flux submit --setattr=system.dw="foo" hostname) &&
	flux job wait-event -vt 5 -m description=${CREATE_DEP_NAME} \
		${jobid} dependency-add &&
	flux job wait-event -vt 10 ${jobid} exception
'

test_expect_success 'workflows in Error are killed properly' '
	jobid=$(flux submit --setattr=system.dw="#DW jobdw capacity=10KiB type=xfs name=project1
		#DW copy_in source=/some/fake/dir destination=$DW_JOB_project1/" \
		-N1 -n1 hostname) &&
	flux job wait-event -vt 10 -m description=${CREATE_DEP_NAME} \
		${jobid} dependency-add &&
	flux job wait-event -t 10 ${jobid} exception &&
	flux job wait-event -vt 5 ${jobid} clean
'

test_done
