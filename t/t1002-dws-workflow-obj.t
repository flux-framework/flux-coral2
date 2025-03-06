#!/bin/sh

test_description='Test DWS Workflow Objection Creation'

. $(dirname $0)/sharness.sh

if test_have_prereq NO_DWS_K8S; then
    skip_all='skipping DWS workflow tests due to no DWS K8s'
    test_done
fi

flux version | grep -q libflux-security && test_set_prereq FLUX_SECURITY

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

submit_as_alternate_user()
{
    FAKE_USERID=42
    flux run --dry-run "$@" | \
      flux python ${SHARNESS_TEST_SRCDIR}/scripts/sign-as.py $FAKE_USERID \
        >job.signed
    FLUX_HANDLE_USERID=$FAKE_USERID \
      flux job submit --flags=signed job.signed
}

test_expect_success 'job-manager: load dws-jobtap and alloc-bypass plugin' '
	flux jobtap load ${PLUGINPATH}/dws-jobtap.so &&
	flux jobtap load alloc-bypass.so
'

test_expect_success 'exec dws service-providing script with bad arguments' '
    KUBECONFIG=/dev/null test_expect_code 3 flux python ${DWS_MODULE_PATH} \
        -v &&
    echo "
[rabbit]
kubeconfig = \"/dev/null\"
    " | flux config load &&
    test_expect_code 3 flux python ${DWS_MODULE_PATH} -v &&
    test_expect_code 2 flux python ${DWS_MODULE_PATH} \
        -v --foobar
'

test_expect_success 'exec dws service-providing script with bad config' '
    echo "
[rabbit]
foobar = false
    " | flux config load &&
    test_must_fail flux python ${DWS_MODULE_PATH} -v &&
    echo "
[rabbit.policy.maximums]
fake = 1
    " | flux config load &&
    test_must_fail flux python ${DWS_MODULE_PATH} -v
'

test_expect_success 'exec dws service-providing script with fluxion scheduling disabled' '
    flux config reload &&
    R=$(flux R encode -r 0) &&
    DWS_JOBID=$(flux submit \
            --setattr=system.alloc-bypass.R="$R" \
            -o per-resource.type=node --output=dws-fluxion-disabled.out \
            --error=dws-fluxion-disabled.err python ${DWS_MODULE_PATH} \
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
	flux job wait-event -t 5 ${jobid} jobspec-update &&
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

test_expect_success 'dws service script handles restarts while a job is in SCHED with fluxion disabled' '
	flux queue stop --all &&
	jobid=$(flux submit --setattr=system.dw="#DW jobdw capacity=10GiB type=xfs name=project1" \
		-N1 -n1 true) &&
	flux job wait-event -vt 15 -m description=${CREATE_DEP_NAME} \
		${jobid} dependency-add &&
	flux job wait-event -t 15 -m description=${CREATE_DEP_NAME} \
		${jobid} dependency-remove &&
	flux cancel ${DWS_JOBID} &&
	R=$(flux R encode -r 0) &&
	DWS_JOBID=$(flux submit \
		--setattr=system.alloc-bypass.R="$R" \
		-o per-resource.type=node --output=dws-fluxion-disabled2.out \
		--error=dws-fluxion-disabled2.err \
		python ${DWS_MODULE_PATH} -vvv --disable-fluxion) &&
	test_must_fail flux job wait-event -vt 10 -m description=${PROLOG_NAME} \
		${jobid} prolog-start &&
	flux queue start --all &&
	flux job wait-event -vt 15 -m description=${PROLOG_NAME} \
		${jobid} prolog-start
	flux job wait-event -vt 15 -m description=${PROLOG_NAME} \
		${jobid} prolog-finish
	flux job wait-event -vt 5 -m status=0 ${jobid} finish &&
	flux job wait-event -vt 5 -m description=${EPILOG_NAME} \
		${jobid} epilog-start &&
	flux job wait-event -vt 45 -m description=${EPILOG_NAME} \
		${jobid} epilog-finish &&
	flux job wait-event -vt 25 ${jobid} clean
'

test_expect_success 'load fluxion with rabbits' '
    flux cancel ${DWS_JOBID} &&
    flux python ${FLUX_SOURCE_DIR}/src/cmd/flux-rabbitmapping.py > rabbits.json &&
	flux R encode -l | flux python ${FLUX_SOURCE_DIR}/src/cmd/flux-dws2jgf.py \
	--no-validate rabbits.json | jq . > R.local &&
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
	        python ${DWS_MODULE_PATH} -vvv) &&
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
	flux job wait-event -t 5 ${jobid} jobspec-update &&
	flux job wait-event -vt 15 ${jobid} depend &&
	flux job wait-event -vt 15 ${jobid} priority &&
	flux job wait-event -vt 15 -m description=${PROLOG_NAME} \
		${jobid} prolog-start &&
	flux job wait-event -vt 25 -m description=${PROLOG_NAME} \
		${jobid} prolog-finish &&
	flux job wait-event -vt 15 -m status=0 ${jobid} finish &&
	flux job wait-event -t1 -fjson ${jobid} dws_environment > env-event.json &&
	jq -e .context.variables env-event.json &&
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
	flux job info ${jobid} rabbit_teardown_timing &&
	flux job info ${jobid} rabbit_datamovements | jq "length == 0"
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
	flux job wait-event -t 5 ${jobid} jobspec-update &&
	flux job wait-event -vt 15 ${jobid} depend &&
	flux job wait-event -vt 15 ${jobid} priority &&
	flux job wait-event -vt 15 -m description=${PROLOG_NAME} \
		${jobid} prolog-start &&
	flux job wait-event -vt 25 -m description=${PROLOG_NAME} \
		${jobid} prolog-finish &&
	flux job wait-event -vt 15 -m status=0 ${jobid} finish &&
	flux job wait-event -t1 -fjson ${jobid} dws_environment > env-event2.json &&
	jq -e .context.variables env-event2.json &&
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
	flux job info ${jobid} rabbit_teardown_timing &&
	flux job info ${jobid} rabbit_datamovements | jq "length == 0"
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
	flux job wait-event -t 5 ${jobid} jobspec-update &&
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
	flux job wait-event -t 5 ${jobid} jobspec-update &&
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
	flux job wait-event -vt 10 ${jobid} clean
'

test_expect_success 'exec dws service-providing script with custom config path' '
	flux cancel ${DWS_JOBID} &&
	cp $REAL_HOME/.kube/config ./kubeconfig
	R=$(flux R encode -r 0) &&
    echo "
[rabbit]
kubeconfig = \"$PWD/kubeconfig\"
    " | flux config load &&
	DWS_JOBID=$(flux submit \
		--setattr=system.alloc-bypass.R="$R" \
		-o per-resource.type=node --output=dws2.out --error=dws2.err \
		python ${DWS_MODULE_PATH} -vvv) &&
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

test_expect_success FLUX_SECURITY 'job submission with persistent DW string and non-owner UID fails' '
	jobid=$(submit_as_alternate_user \
		--setattr=system.dw="#DW create_persistent capacity=10GiB type=lustre name=project1" \
		-N1 -n1 -c1 --setattr=exec.test.run_duration=1s \
		hostname) &&
	flux job wait-event -vt 10 ${jobid} exception &&
	flux job wait-event -vt 15 ${jobid} clean &&
	flux job wait-event -t 1 ${jobid} exception | grep "only the instance owner"
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
		python ${DWS_MODULE_PATH} -vvv) &&
	flux job wait-event -vt 5 -m status=0 ${jobid} finish &&
	flux job wait-event -vt 5 -m description=${EPILOG_NAME} \
		${jobid} epilog-start &&
	flux job wait-event -vt 45 -m description=${EPILOG_NAME} \
		${jobid} epilog-finish &&
	flux job wait-event -vt 25 ${jobid} clean
'

test_expect_success 'back-to-back job submissions with 10TiB file systems works' '
	jobid1=$(flux submit --setattr=system.dw="#DW jobdw capacity=10TiB type=xfs name=project1" \
		-N1 -n1 hostname) &&
	jobid2=$(flux submit --setattr=system.dw="#DW jobdw capacity=10TiB type=lustre name=project2" \
		-N1 -n1 hostname) &&
	jobid3=$(flux submit --setattr=system.dw="#DW jobdw capacity=10TiB type=xfs name=project3" \
		-N1 -n1 hostname) &&
	flux job wait-event -vt 15 -m description=${CREATE_DEP_NAME} \
		${jobid1} dependency-add &&
	flux job wait-event -vt 15 -m description=${CREATE_DEP_NAME} \
		${jobid2} dependency-add &&
	flux job wait-event -vt 15 -m description=${CREATE_DEP_NAME} \
		${jobid3} dependency-add &&
	flux job wait-event -t 35 -m description=${CREATE_DEP_NAME} \
		${jobid1} dependency-remove &&
	flux job wait-event -t 35 -m description=${CREATE_DEP_NAME} \
		${jobid2} dependency-remove &&
	flux job wait-event -t 35 -m description=${CREATE_DEP_NAME} \
		${jobid3} dependency-remove &&
	flux job wait-event -vt 35 -m description=${PROLOG_NAME} \
		${jobid1} prolog-start &&
	flux job wait-event -vt 35 -m description=${PROLOG_NAME} \
		${jobid1} prolog-finish &&
	flux job wait-event -vt 35 -m description=${PROLOG_NAME} \
		${jobid2} prolog-start &&
	flux job wait-event -vt 35 -m description=${PROLOG_NAME} \
		${jobid2} prolog-finish &&
	flux job wait-event -vt 35 -m description=${PROLOG_NAME} \
		${jobid3} prolog-finish &&
	flux job wait-event -vt 15 -m status=0 ${jobid1} finish &&
	flux job wait-event -vt 15 -m status=0 ${jobid2} finish &&
	flux job wait-event -vt 15 -m status=0 ${jobid3} finish &&
	flux job wait-event -vt 15 -m description=${EPILOG_NAME} \
		${jobid} epilog-start &&
	flux job wait-event -vt 45 -m description=${EPILOG_NAME} \
		${jobid1} epilog-finish &&
	flux job wait-event -vt 45 -m description=${EPILOG_NAME} \
		${jobid2} epilog-finish &&
	flux job wait-event -vt 15 ${jobid1} clean &&
	flux job wait-event -vt 15 ${jobid2} clean &&
	flux job wait-event -vt 15 ${jobid3} clean
'

test_expect_success 'launch service with storage maximums and presets' '
	flux cancel $DWS_JOBID &&
	flux config load ${DATADIR}/maximums &&
	DWS_JOBID=$(flux submit \
		--setattr=system.alloc-bypass.R="$R" \
		-o per-resource.type=node --output=dws4.out --error=dws4.err \
		python ${DWS_MODULE_PATH} -vvv) &&
	flux job wait-event -vt 15 -m "note=dws watchers setup" ${DWS_JOBID} exception &&
	${RPC} "dws.create"
'

test_expect_success 'job submission with storage within max works' '
	jobid=$(flux submit --setattr=system.dw="#DW jobdw capacity=50GiB type=xfs name=project1
		#DW jobdw capacity=20GiB type=gfs2 name=project2
		#DW jobdw capacity=30GiB type=raw name=project3
		#DW jobdw capacity=10GiB type=lustre name=project4" \
		-N1 -n1 hostname) &&
	flux job wait-event -vt 10 -m description=${CREATE_DEP_NAME} \
		${jobid} dependency-add &&
	flux job wait-event -t 10 -m description=${CREATE_DEP_NAME} \
		${jobid} dependency-remove &&
	flux job wait-event -t 10 -m rabbit_workflow=fluxjob-$(flux job id ${jobid}) \
		${jobid} memo &&
	flux job wait-event -t 5 ${jobid} jobspec-update &&
	flux job wait-event -vt 15 ${jobid} depend &&
	flux job wait-event -vt 15 ${jobid} priority &&
	flux job wait-event -vt 15 -m description=${PROLOG_NAME} \
		${jobid} prolog-start &&
	flux job wait-event -vt 25 -m description=${PROLOG_NAME} \
		${jobid} prolog-finish &&
	flux job wait-event -vt 15 -m status=0 ${jobid} finish &&
	flux job wait-event -vt 15 -m description=${EPILOG_NAME} \
		${jobid} epilog-start &&
	flux job wait-event -vt 55 -m description=${EPILOG_NAME} \
		${jobid} epilog-finish &&
	flux job wait-event -vt 15 ${jobid} clean
'

test_expect_success 'job submission with presets works' '
	jobid=$(flux submit -S dw=xfs_justright -N1 -n1 hostname) &&
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
	flux job wait-event -vt 55 -m description=${EPILOG_NAME} \
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

test_expect_success 'job submission with preset gfs2 storage beyond max fails' '
	jobid=$(flux submit -S dw=gfs2_toobig -N1 -n1 hostname) &&
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

test_expect_success 'job submission with preset lustre storage beyond max fails' '
	jobid=$(flux submit -S dw=lustre_toobig -N1 -n1 hostname) &&
	flux job wait-event -vt 10 -m description=${CREATE_DEP_NAME} \
		${jobid} dependency-add &&
	flux job wait-event -vt 10 ${jobid} exception &&
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
