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

test_expect_success 'job-manager: load dws-jobtap and alloc-bypass plugin' '
	flux jobtap load ${PLUGINPATH}/dws-jobtap.so &&
	flux jobtap load alloc-bypass.so
'

test_expect_success 'exec dws service-providing script with bad arguments' '
    KUBECONFIG=/dev/null test_expect_code 3 flux python ${DWS_MODULE_PATH} \
        -e1 -v -rR.local &&
    unset KUBECONFIG &&
    test_expect_code 3 flux python ${DWS_MODULE_PATH} -e1 -v -rR.local \
        --kubeconfig /dev/null &&
    test_expect_code 2 flux python ${DWS_MODULE_PATH} \
        -e1 -v -rR.local --foobar
'

test_expect_success 'exec dws service-providing script with fluxion scheduling disabled' '
    R=$(flux R encode -r 0) &&
    DWS_JOBID=$(flux submit \
            --setattr=system.alloc-bypass.R="$R" \
            -o per-resource.type=node --output=dws-fluxion-disabled.out \
            --error=dws-fluxion-disabled.err python ${DWS_MODULE_PATH} -e1 \
            -vvv --disable-fluxion) &&
    flux job wait-event -vt 15 -p guest.exec.eventlog ${DWS_JOBID} shell.start &&
    flux job wait-event -vt 15 -m "note=dws watchers setup" ${DWS_JOBID} exception &&
    ${RPC} "dws.create"
'

test_expect_success 'job submission without DW string works with fluxion-rabbit scheduling disabled' '
    jobid=$(flux submit -n1 /bin/true) &&
    flux job wait-event -vt 25 -m status=0 ${jobid} finish &&
    test_must_fail flux job wait-event -vt 5 -m description=${CREATE_DEP_NAME} \
        ${jobid} dependency-add
'

test_expect_success 'job submission with valid DW string works with fluxion-rabbit scheduling disabled' '
    jobid=$(flux submit --setattr=system.dw="#DW jobdw capacity=10GiB type=xfs name=project1" \
        -N1 -n1 hostname) &&
    flux job wait-event -vt 10 -m description=${CREATE_DEP_NAME} \
        ${jobid} dependency-add &&
    flux job wait-event -t 10 -m description=${CREATE_DEP_NAME} \
        ${jobid} dependency-remove &&
    flux job wait-event -t 10 -m rabbit_workflow=fluxjob-$(flux job id ${jobid}) \
        ${jobid} memo &&
    flux job wait-event -vt 15 ${jobid} depend &&
    flux job wait-event -vt 15 ${jobid} priority &&
    flux job wait-event -vt 15 -m description=${PROLOG_NAME} \
        ${jobid} prolog-start &&
    flux job wait-event -vt 25 -m description=${PROLOG_NAME} \
        ${jobid} prolog-finish &&
    flux job wait-event -vt 15 -m status=0 ${jobid} finish &&
    flux job wait-event -vt 15 -m description=${EPILOG_NAME} \
        ${jobid} epilog-start &&
    flux job wait-event -vt 30 -m description=${EPILOG_NAME} \
        ${jobid} epilog-finish &&
    flux job wait-event -vt 15 ${jobid} clean
'

test_expect_success 'load fluxion with rabbits' '
    flux cancel ${DWS_JOBID} &&
	flux R encode -l | flux python ${FLUX_SOURCE_DIR}/src/cmd/flux-dws2jgf.py \
	--no-validate | jq . > R.local &&
	flux kvs put resource.R="$(cat R.local)" &&
	flux module remove -f sched-fluxion-qmanager &&
	flux module remove -f sched-fluxion-resource &&
	flux module reload resource &&
	flux module load sched-fluxion-resource &&
	flux module load sched-fluxion-qmanager
'

test_expect_success 'exec dws service-providing script' '
	R=$(flux R encode -r 0) &&
	DWS_JOBID=$(flux submit \
	        --setattr=system.alloc-bypass.R="$R" \
	        -o per-resource.type=node --output=dws1.out --error=dws1.err \
	        python ${DWS_MODULE_PATH} -e1 -vvv -rR.local) &&
	flux job wait-event -vt 15 -p guest.exec.eventlog ${DWS_JOBID} shell.start
'

# This test used to close the race condition between the python process starting
# and the `dws` service being registered.  Once https://github.com/flux-framework/flux-core/issues/3821
# is implemented/closed, this can be replaced with that solution.
test_expect_success 'wait for service to register and send test RPC' '
	flux job wait-event -vt 15 -m "note=dws watchers setup" ${DWS_JOBID} exception &&
	${RPC} "dws.create" 
'

test_expect_success 'job submission without DW string works' '
	jobid=$(flux submit -n1 /bin/true) &&
	flux job wait-event -vt 25 -m status=0 ${jobid} finish &&
	test_must_fail flux job wait-event -vt 5 -m description=${CREATE_DEP_NAME} \
		${jobid} dependency-add
'

test_expect_success 'job submission with valid DW string works' '
	jobid=$(flux submit --setattr=system.dw="#DW jobdw capacity=10GiB type=xfs name=project1" \
		-N1 -n1 hostname) &&
	flux job wait-event -vt 10 -m description=${CREATE_DEP_NAME} \
		${jobid} dependency-add &&
	flux job wait-event -t 10 -m description=${CREATE_DEP_NAME} \
		${jobid} dependency-remove &&
	flux job wait-event -t 10 -m rabbit_workflow=fluxjob-$(flux job id ${jobid}) \
		${jobid} memo &&
	flux job wait-event -vt 15 ${jobid} depend &&
	flux job wait-event -vt 15 ${jobid} priority &&
	flux job wait-event -vt 15 -m description=${PROLOG_NAME} \
		${jobid} prolog-start &&
	flux job wait-event -vt 25 -m description=${PROLOG_NAME} \
		${jobid} prolog-finish &&
	flux job wait-event -vt 15 -m status=0 ${jobid} finish &&
	flux job wait-event -t1 -fjson ${jobid} dws_environment > env-event.json &&
	jq -e .context.variables env-event.json && jq -e .context.rabbits env-event.json &&
	jq -e ".context.copy_offload == false" env-event.json &&
	flux job wait-event -vt 15 -m description=${EPILOG_NAME} \
		${jobid} epilog-start &&
	flux job wait-event -vt 30 -m description=${EPILOG_NAME} \
		${jobid} epilog-finish &&
	flux job wait-event -vt 15 ${jobid} clean &&
	flux jobs -n ${jobid} -o "{user.rabbits}" | flux hostlist -q - &&
	flux job info ${jobid} rabbit_workflow &&
	flux job info ${jobid} rabbit_workflow | \
		jq -e ".metadata.name == \"fluxjob-$(flux job id ${jobid})\"" &&
	flux job info ${jobid} rabbit_workflow | jq -e ".spec.wlmID == \"flux\"" &&
	flux job info ${jobid} rabbit_workflow | jq -e ".kind == \"Workflow\"" &&
	flux job info ${jobid} rabbit_proposal_timing &&
	flux job info ${jobid} rabbit_setup_timing &&
	flux job info ${jobid} rabbit_datain_timing &&
	flux job info ${jobid} rabbit_prerun_timing &&
	flux job info ${jobid} rabbit_postrun_timing &&
	flux job info ${jobid} rabbit_dataout_timing &&
	flux job info ${jobid} rabbit_teardown_timing
'

test_expect_success 'job requesting copy-offload in DW string works' '
	jobid=$(flux submit --setattr=system.dw="#DW jobdw capacity=10GiB type=xfs name=project1
			requires=copy-offload" \
		-N1 -n1 hostname) &&
	flux job wait-event -vt 10 -m description=${CREATE_DEP_NAME} \
		${jobid} dependency-add &&
	flux job wait-event -t 10 -m description=${CREATE_DEP_NAME} \
		${jobid} dependency-remove &&
	flux job wait-event -t 10 -m rabbit_workflow=fluxjob-$(flux job id ${jobid}) \
		${jobid} memo &&
	flux job wait-event -vt 15 ${jobid} depend &&
	flux job wait-event -vt 15 ${jobid} priority &&
	flux job wait-event -vt 15 -m description=${PROLOG_NAME} \
		${jobid} prolog-start &&
	flux job wait-event -vt 25 -m description=${PROLOG_NAME} \
		${jobid} prolog-finish &&
	flux job wait-event -vt 15 -m status=0 ${jobid} finish &&
	flux job wait-event -t1 -fjson ${jobid} dws_environment > env-event2.json &&
	jq -e .context.variables env-event2.json && jq -e .context.rabbits env-event2.json &&
	jq -e ".context.copy_offload == true" env-event2.json &&
	flux job wait-event -vt 15 -m description=${EPILOG_NAME} \
		${jobid} epilog-start &&
	flux job wait-event -vt 30 -m description=${EPILOG_NAME} \
		${jobid} epilog-finish &&
	flux job wait-event -vt 15 ${jobid} clean &&
	flux job info ${jobid} rabbit_workflow &&
	flux job info ${jobid} rabbit_workflow | \
		jq -e ".metadata.name == \"fluxjob-$(flux job id ${jobid})\"" &&
	flux job info ${jobid} rabbit_workflow | jq -e ".spec.wlmID == \"flux\"" &&
	flux job info ${jobid} rabbit_workflow | jq -e ".kind == \"Workflow\"" &&
	flux job info ${jobid} rabbit_proposal_timing &&
	flux job info ${jobid} rabbit_setup_timing &&
	flux job info ${jobid} rabbit_datain_timing &&
	flux job info ${jobid} rabbit_prerun_timing &&
	flux job info ${jobid} rabbit_postrun_timing &&
	flux job info ${jobid} rabbit_dataout_timing &&
	flux job info ${jobid} rabbit_teardown_timing
'

test_expect_success 'job requesting too much storage is rejected' '
	jobid=$(flux submit --setattr=system.dw="#DW jobdw capacity=1000TiB type=xfs name=project1" \
		-N1 -n1 hostname) &&
	flux job wait-event -vt 10 -m description=${CREATE_DEP_NAME} \
		${jobid} dependency-add &&
	flux job wait-event -t 10 -m description=${CREATE_DEP_NAME} \
		${jobid} dependency-remove &&
	sleep 60 && flux job eventlog ${jobid} &&
	flux job wait-event -t 10 ${jobid} exception &&
	flux job wait-event -vt 5 ${jobid} clean
'

test_expect_success 'job submission with multiple valid DW strings on different lines works' '
	jobid=$(flux submit --setattr=system.dw="
											 #DW jobdw capacity=10GiB type=xfs name=project1

											 #DW jobdw capacity=20GiB type=gfs2 name=project2" \
		    -N1 -n1 hostname) &&
	flux job wait-event -vt 10 -m description=${CREATE_DEP_NAME} \
		${jobid} dependency-add &&
	flux job wait-event -t 10 -m description=${CREATE_DEP_NAME} \
		${jobid} dependency-remove &&
	flux job wait-event -t 10 -m rabbit_workflow=fluxjob-$(flux job id ${jobid}) \
		${jobid} memo &&
	flux job wait-event -vt 15 ${jobid} depend &&
	flux job wait-event -vt 15 ${jobid} priority &&
	flux job wait-event -vt 15 -m description=${PROLOG_NAME} \
		${jobid} prolog-start &&
	flux job wait-event -vt 25 -m description=${PROLOG_NAME} \
		${jobid} prolog-finish &&
	flux job wait-event -vt 15 -m status=0 ${jobid} finish &&
	flux job wait-event -vt 15 -m description=${EPILOG_NAME} \
		${jobid} epilog-start &&
	flux job wait-event -vt 45 -m description=${EPILOG_NAME} \
		${jobid} epilog-finish &&
	flux job wait-event -vt 15 ${jobid} clean &&
	flux jobs -n ${jobid} -o "{user.rabbits}" | flux hostlist -q -
'

test_expect_success 'job submission with multiple valid DW strings on the same line works' '
	jobid=$(flux submit --setattr=system.dw="#DW jobdw capacity=10GiB type=xfs name=project1 \
			#DW jobdw capacity=20GiB type=gfs2 name=project2" \
		-N1 -n1 hostname) &&
	flux job wait-event -vt 10 -m description=${CREATE_DEP_NAME} \
		${jobid} dependency-add &&
	flux job wait-event -t 10 -m description=${CREATE_DEP_NAME} \
		${jobid} dependency-remove &&
	flux job wait-event -vt 15 ${jobid} depend &&
	flux job wait-event -vt 15 ${jobid} priority &&
	flux job wait-event -vt 15 -m description=${PROLOG_NAME} \
		${jobid} prolog-start &&
	flux job wait-event -vt 25 -m description=${PROLOG_NAME} \
		${jobid} prolog-finish &&
	flux job wait-event -vt 15 -m status=0 ${jobid} finish &&
	flux job wait-event -vt 15 -m description=${EPILOG_NAME} \
		${jobid} epilog-start &&
	flux job wait-event -vt 45 -m description=${EPILOG_NAME} \
		${jobid} epilog-finish &&
	flux job wait-event -vt 15 ${jobid} clean
'

test_expect_success 'job submission with multiple valid DW strings in a JSON file works' '
	jobid=$(flux submit --setattr=^system.dw="${DATADIR}/two_directives.json" \
		    -N1 -n1 hostname) &&
	flux job wait-event -vt 10 -m description=${CREATE_DEP_NAME} \
		${jobid} dependency-add &&
	flux job wait-event -t 10 -m description=${CREATE_DEP_NAME} \
		${jobid} dependency-remove &&
	flux job wait-event -vt 15 ${jobid} depend &&
	flux job wait-event -vt 15 ${jobid} priority &&
	flux job wait-event -t 10 -m rabbit_workflow=fluxjob-$(flux job id ${jobid}) \
		${jobid} memo &&
	flux job wait-event -vt 15 -m description=${PROLOG_NAME} \
		${jobid} prolog-start &&
	flux job wait-event -vt 45 -m description=${PROLOG_NAME} \
		${jobid} prolog-finish &&
	flux job wait-event -vt 15 -m status=0 ${jobid} finish &&
	flux job wait-event -vt 15 -m description=${EPILOG_NAME} \
		${jobid} epilog-start &&
	flux job wait-event -vt 65 -m description=${EPILOG_NAME} \
		${jobid} epilog-finish &&
	flux job wait-event -vt 15 ${jobid} clean
'

test_expect_success 'job submission with invalid copy_in DW directive fails' '
	jobid=$(flux submit --setattr=system.dw="#DW jobdw capacity=10GiB type=lustre name=project2 \
			#DW copy_in source=/some/fake/dir destination=\$DW_JOB_project2/" \
		-N1 -n1 hostname) &&
	flux job wait-event -vt 10 -m description=${CREATE_DEP_NAME} \
		${jobid} dependency-add &&
	flux job wait-event -vt 15 ${jobid} exception &&
	flux job wait-event -vt 15 ${jobid} clean
'

test_expect_success 'job submission with invalid copy_out DW directive fails' '
	jobid=$(flux submit --setattr=system.dw="#DW jobdw capacity=10GiB type=lustre name=project3 \
			#DW copy_out source=\$DW_JOB_project3/ destination=/some/fake/dir" \
		-N1 -n1 hostname) &&
	flux job wait-event -vt 10 -m description=${CREATE_DEP_NAME} \
		${jobid} dependency-add &&
	flux job wait-event -vt 15 ${jobid} exception &&
	flux job wait-event -vt 15 ${jobid} clean
'

test_expect_success 'job-manager: dependency plugin works when validation fails' '
	jobid=$(flux submit --setattr=system.dw="foo" hostname) &&
	flux job wait-event -vt 5 -m description=${CREATE_DEP_NAME} \
		${jobid} dependency-add &&
	flux job wait-event -vt 10 ${jobid} exception
'

test_expect_success 'dws service kills workflows in Error properly' '
	jobid=$(flux submit --setattr=system.dw="#DW jobdw capacity=10GiB type=xfs name=project1
		#DW copy_in source=/some/fake/dir destination=$DW_JOB_project1/" \
		-N1 -n1 hostname) &&
	flux job wait-event -vt 10 -m description=${CREATE_DEP_NAME} \
		${jobid} dependency-add &&
	flux job wait-event -t 10 ${jobid} exception &&
	flux job wait-event -vt 5 ${jobid} clean
'

test_expect_success 'exec dws service-providing script with custom config path' '
	flux cancel ${DWS_JOBID} &&
	cp $REAL_HOME/.kube/config ./kubeconfig
	R=$(flux R encode -r 0) &&
	DWS_JOBID=$(flux submit \
		--setattr=system.alloc-bypass.R="$R" \
		-o per-resource.type=node --output=dws2.out --error=dws2.err \
		python ${DWS_MODULE_PATH} -e1 --kubeconfig $PWD/kubeconfig -vvv -rR.local) &&
	flux job wait-event -vt 15 -m "note=dws watchers setup" ${DWS_JOBID} exception &&
	${RPC} "dws.create"
'

test_expect_success 'job submission with valid DW string works after config change' '
	jobid=$(flux submit --setattr=system.dw="#DW jobdw capacity=10GiB type=xfs name=project1" \
		-N1 -n1 hostname) &&
	flux job wait-event -vt 15 -m description=${CREATE_DEP_NAME} \
		${jobid} dependency-add &&
	flux job wait-event -vt 15 -m description=${PROLOG_NAME} \
		${jobid} prolog-start &&
	flux job wait-event -vt 30 -m status=0 ${jobid} finish &&
	flux job wait-event -vt 5 -m description=${EPILOG_NAME} \
		${jobid} epilog-start &&
	flux job wait-event -vt 25 ${jobid} clean
'

test_expect_success 'job submission with persistent DW string works' '
	flux run --setattr=system.dw="#DW create_persistent capacity=10GiB type=lustre name=project1" \
		-N1 -n1 -c1 hostname &&
	jobid=$(flux submit --setattr=system.dw="#DW persistentdw name=project1" \
		-N1 -n1 hostname) &&
	flux job wait-event -vt 30 -m description=${PROLOG_NAME} \
		${jobid} prolog-start &&
	flux job wait-event -vt 30 -m status=0 ${jobid} finish &&
	flux job wait-event -vt 30 -m description=${EPILOG_NAME} \
		${jobid} epilog-start &&
	flux job wait-event -vt 30 ${jobid} clean &&
	jobid=$(flux submit --setattr=system.dw="#DW persistentdw name=project1" \
		-N1 -n1 hostname) &&
	flux job wait-event -vt 30 -m description=${PROLOG_NAME} \
		${jobid} prolog-start &&
	flux job wait-event -vt 30 -m status=0 ${jobid} finish &&
	flux job wait-event -vt 30 -m description=${EPILOG_NAME} \
		${jobid} epilog-start &&
	flux job wait-event -vt 30 ${jobid} clean &&
	jobid=$(flux submit --setattr=system.dw="#DW destroy_persistent name=project1" \
		-N1 -n1 -c1 hostname) &&
	flux job wait-event -vt 30 -m description=${EPILOG_NAME} \
		${jobid} epilog-start &&
	flux job wait-event -vt 30 ${jobid} clean
'

test_expect_success 'job submission with standalone MGT persistent DW string works' '
	(kubectl delete nnfstorageprofiles -nnnf-system mypoolprofile || true) &&
	kubectl get nnfstorageprofiles -nnnf-system default -ojson | \
		jq ".data.lustreStorage.standaloneMgtPoolName = \"mypool\" |
		.metadata.name = \"mypoolprofile\" | .data.default = false |
		.data.lustreStorage.combinedMgtMdt = false" \
		| kubectl apply -f - &&
	flux run --setattr=system.dw="#DW create_persistent type=lustre name=mgtpooltest profile=mypoolprofile" \
		-N1 -n1 -c1 hostname &&
	jobid=$(flux submit --setattr=system.dw="#DW destroy_persistent name=mgtpooltest" \
		-N1 -n1 -c1 hostname) &&
	flux job wait-event -vt 30 -m description=${EPILOG_NAME} \
		${jobid} epilog-start &&
	flux job wait-event -vt 30 ${jobid} clean &&
	kubectl delete nnfstorageprofiles -nnnf-system mypoolprofile
'

test_expect_success 'dws service script handles restarts while a job is running' '
	jobid=$(flux submit --setattr=system.dw="#DW jobdw capacity=10GiB type=xfs name=project1" \
		-N1 -n1 sleep 5) &&
	flux job wait-event -vt 15 -m description=${CREATE_DEP_NAME} \
		${jobid} dependency-add &&
	flux job wait-event -vt 15 -m description=${PROLOG_NAME} \
		${jobid} prolog-start &&
	flux job wait-event -vt 30 ${jobid} start &&
	flux cancel ${DWS_JOBID} &&
	R=$(flux R encode -r 0) &&
	DWS_JOBID=$(flux submit \
		--setattr=system.alloc-bypass.R="$R" \
		-o per-resource.type=node --output=dws3.out --error=dws3.err \
		python ${DWS_MODULE_PATH} -e1 --kubeconfig $PWD/kubeconfig -vvv -rR.local) &&
	flux job wait-event -vt 5 -m status=0 ${jobid} finish &&
	flux job wait-event -vt 5 -m description=${EPILOG_NAME} \
		${jobid} epilog-start &&
	flux job wait-event -vt 45 -m description=${EPILOG_NAME} \
		${jobid} epilog-finish &&
	flux job wait-event -vt 25 ${jobid} clean
'

test_expect_success 'launch service with storage maximum arguments' '
	flux job cancel $DWS_JOBID &&
	DWS_JOBID=$(flux submit \
		--setattr=system.alloc-bypass.R="$R" \
		-o per-resource.type=node --output=dws4.out --error=dws4.err \
		python ${DWS_MODULE_PATH} -e1 --kubeconfig $PWD/kubeconfig -vvv -rR.local \
		--max-xfs 500 --max-lustre 100 --max-gfs2 200 --max-raw 300) &&
	flux job wait-event -vt 15 -m "note=dws watchers setup" ${DWS_JOBID} exception &&
	${RPC} "dws.create"
'

test_expect_success 'job submission with storage within max works' '
	jobid=$(flux submit --setattr=system.dw="#DW jobdw capacity=500GiB type=xfs name=project1
		#DW jobdw capacity=200GiB type=gfs2 name=project2
		#DW jobdw capacity=300GiB type=raw name=project3
		#DW jobdw capacity=100GiB type=lustre name=project4" \
		-N1 -n1 hostname) &&
	flux job wait-event -vt 10 -m description=${CREATE_DEP_NAME} \
		${jobid} dependency-add &&
	flux job wait-event -t 10 -m description=${CREATE_DEP_NAME} \
		${jobid} dependency-remove &&
	flux job wait-event -t 10 -m rabbit_workflow=fluxjob-$(flux job id ${jobid}) \
		${jobid} memo &&
	flux job wait-event -vt 15 ${jobid} depend &&
	flux job wait-event -vt 15 ${jobid} priority &&
	flux job wait-event -vt 15 -m description=${PROLOG_NAME} \
		${jobid} prolog-start &&
	flux job wait-event -vt 25 -m description=${PROLOG_NAME} \
		${jobid} prolog-finish &&
	flux job wait-event -vt 15 -m status=0 ${jobid} finish &&
	flux job wait-event -vt 15 -m description=${EPILOG_NAME} \
		${jobid} epilog-start &&
	flux job wait-event -vt 45 -m description=${EPILOG_NAME} \
		${jobid} epilog-finish &&
	flux job wait-event -vt 15 ${jobid} clean
'

test_expect_success 'job submission with xfs storage beyond max fails' '
	jobid=$(flux submit --setattr=system.dw="#DW jobdw capacity=600GiB type=xfs name=project1" \
		-N1 -n1 hostname) &&
	flux job wait-event -vt 10 -m description=${CREATE_DEP_NAME} \
		${jobid} dependency-add &&
	flux job wait-event -vt 10 ${jobid} exception &&
	flux job wait-event -vt 15 ${jobid} clean &&
	flux job wait-event -t 1 ${jobid} exception | grep "max is 500 GiB per node"
'

test_expect_success 'job submission with combined gfs2 storage beyond max fails' '
	jobid=$(flux submit --setattr=system.dw="#DW jobdw capacity=150GiB type=gfs2 name=project1 \
		#DW jobdw capacity=150GiB type=gfs2 name=project2" -N1 -n1 hostname) &&
	flux job wait-event -vt 10 -m description=${CREATE_DEP_NAME} \
		${jobid} dependency-add &&
	flux job wait-event -vt 10 ${jobid} exception &&
	flux job wait-event -vt 15 ${jobid} clean &&
	flux job wait-event -t 1 ${jobid} exception | grep "max is 200 GiB per node"
'

test_expect_success 'job submission with lustre storage beyond max fails' '
	jobid=$(flux submit --setattr=system.dw="#DW jobdw capacity=120GiB type=lustre name=project1" \
		-N1 -n1 hostname) &&
	flux job wait-event -vt 10 -m description=${CREATE_DEP_NAME} \
		${jobid} dependency-add &&
	flux job wait-event -vt 20 ${jobid} exception &&
	flux job wait-event -vt 15 ${jobid} clean &&
	flux job wait-event -t 1 ${jobid} exception | grep "max is 100 GiB per node"
'

test_expect_success 'cleanup: unload fluxion' '
	# all jobs must be canceled before unloading fluxion or a hang will occur during
	# shutdown, unless another scheduler is loaded afterwards
	flux cancel $DWS_JOBID && flux queue drain &&
	flux module remove sched-fluxion-qmanager &&
	flux module remove sched-fluxion-resource &&
	flux module load sched-simple
'

test_done
