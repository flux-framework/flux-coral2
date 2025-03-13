#!/bin/sh

test_description='Test cray_pals jobtap and shell plugins'

JOBTAP_PLUGINPATH=${FLUX_BUILD_DIR}/src/job-manager/plugins/.libs
SHELL_PLUGINPATH=${FLUX_BUILD_DIR}/src/shell/plugins/.libs
USERRC_NAME="cray_pals.lua"

. $(dirname $0)/sharness.sh

test_under_flux 2 job

flux setattr log-stderr-level 1

unset PALS_RANKID PALS_NODEID PMI_CONTROL_PORT PMI_SHARED_SECRET

test_expect_success 'job-manager: load cray_pals_port_distributor plugin with invalid config' '
	test_expect_code 1 flux jobtap load ${JOBTAP_PLUGINPATH}/cray_pals_port_distributor.so \
		port-min=0 port-max=12000 &&
	test_expect_code 1 flux jobtap load ${JOBTAP_PLUGINPATH}/cray_pals_port_distributor.so \
		port-min=11000 port-max=120000 &&
	test_expect_code 1 flux jobtap load ${JOBTAP_PLUGINPATH}/cray_pals_port_distributor.so \
		port-min=11000 port-max=11010
'

test_expect_success 'job-manager: load cray_pals_port_distributor plugin' '
	flux jobtap load ${JOBTAP_PLUGINPATH}/cray_pals_port_distributor.so \
		port-min=11000 port-max=12000 &&
	flux jobtap list -a | grep cray_pals_port_distributor.so
'

test_expect_success 'job-manager: pals port distributor works' '
	jobid=$(flux submit -N2 -n2 true) &&
	flux job wait-event -vt 15 ${jobid} cray_port_distribution &&
	flux job wait-event -mports=[11999,11998] ${jobid} cray_port_distribution &&
	flux job wait-event -vt 5 ${jobid} clean
'

test_expect_success 'job-manager: pals port distributor saves ports for multi-shell jobs' '
	jobid=$(flux submit -n1 true) &&
	test_must_fail flux job wait-event -vt 15 ${jobid} cray_port_distribution
'

# as long as it's only ever one job at a time the ports should be deterministic
test_expect_success 'job-manager: pals port distributor reclaims ports' '
	flux run -N2 -n2 true &&
	jobid=$(flux submit -N2 -n2 true) &&
	flux job wait-event -vt 15 ${jobid} cray_port_distribution &&
	(flux job wait-event -mports=[11999,11998] ${jobid} cray_port_distribution ||
	flux job wait-event -mports=[11998,11999] ${jobid} cray_port_distribution) &&
	flux job wait-event -vt 5 ${jobid} clean
'

test_expect_success 'shell: create shell initrc for testing' "
	cat >$USERRC_NAME <<-EOT
	if shell.options['pmi'] == nil then
	    shell.options['pmi'] = 'cray-pals'
	end
	plugin.load { file = \"$SHELL_PLUGINPATH/cray_pals.so\", conf = { } }
	EOT
"

test_expect_success 'shell: cray-pals is active when userrc is loaded' '
	flux run -o userrc=$(pwd)/$USERRC_NAME \
	    printenv PALS_RANKID
'
test_expect_success 'shell: cray-pals is inactive with -opmi=off' '
	test_must_fail flux run -o userrc=$(pwd)/$USERRC_NAME -o pmi=off \
	    printenv PALS_RANKID
'
test_expect_success 'shell: cray-pals is active with -opmi=cray-pals' '
	flux run -o userrc=$(pwd)/$USERRC_NAME -o pmi=cray-pals \
	    printenv PALS_RANKID
'
test_expect_success 'shell: cray-pals is active with -opmi includes cray-pals' '
	flux run -o userrc=$(pwd)/$USERRC_NAME -o pmi=simple,cray-pals \
	    printenv PALS_RANKID &&
	flux run -o userrc=$(pwd)/$USERRC_NAME -o pmi=cray-pals,simple \
	    printenv PALS_RANKID
'
test_expect_success 'shell: cray-pals unsets PALS variables when inactive' '
	(export PALS_RANKID=0 PMI_CONTROL_PORT=6 PALS_NODEID=1 PMI_SHARED_SECRET=1 &&
	test_must_fail flux run -o userrc=$(pwd)/$USERRC_NAME -o pmi=none \
		printenv PALS_RANKID &&
	test_must_fail flux run -o userrc=$(pwd)/$USERRC_NAME -o pmi=none \
		printenv PALS_NODEID &&
	test_must_fail flux run -o userrc=$(pwd)/$USERRC_NAME -o pmi=none \
		printenv PMI_SHARED_SECRET &&
	test_must_fail flux run -o userrc=$(pwd)/$USERRC_NAME -o pmi=none \
		printenv PMI_CONTROL_PORT)
'
test_expect_success 'shell: cray-pals edits LD_LIBRARY_PATH=pmidir:/noexist:pmidir' '
	pmidir=$(dirname $(flux config builtin pmi_library_path)) &&
	flux run -o pmi=cray-pals -o userrc=$(pwd)/$USERRC_NAME \
	    --env=LD_LIBRARY_PATH=$pmidir:/noexist:$pmidir \
	    printenv LD_LIBRARY_PATH >libedit.out &&
	cat >libedit.exp <<-EOT &&
	/noexist
	EOT
	test_cmp libedit.exp libedit.out
'
test_expect_success 'shell: cray-pals removes LD_LIBRARY_PATH=pmidir' '
	pmidir=$(dirname $(flux config builtin pmi_library_path)) &&
	test_must_fail flux run -o pmi=cray-pals \
	    -o userrc=$(pwd)/$USERRC_NAME --env=LD_LIBRARY_PATH=$pmidir \
	    printenv LD_LIBRARY_PATH
'
# In anticipation of flux-framework/flux-core#5714
test_expect_success 'shell: cray-pals removes LD_LIBRARY_PATH=pmidir if added by simple pmi' '
	test_must_fail flux run -o pmi=simple,cray-pals \
	    -o userrc=$(pwd)/$USERRC_NAME --env=-LD_LIBRARY_PATH \
	    printenv LD_LIBRARY_PATH
'
test_expect_success 'shell: cray-pals ignores LD_LIBRARY_PATH=/noexist' '
	flux run -o pmi=cray-pals -o userrc=$(pwd)/$USERRC_NAME \
	    --env=LD_LIBRARY_PATH=/noexist \
	    printenv LD_LIBRARY_PATH >libedit2.out &&
	cat >libedit2.exp <<-EOT &&
	/noexist
	EOT
	test_cmp libedit2.exp libedit2.out
'
test_expect_success 'shell: the -o cray-pals=no-edit-env shell option works' '
	pmidir=$(dirname $(flux config builtin pmi_library_path)) &&
	flux run -o pmi=cray-pals -o cray-pals.no-edit-env \
	    -o userrc=$(pwd)/$USERRC_NAME --env=LD_LIBRARY_PATH=$pmidir \
	    printenv LD_LIBRARY_PATH >libedit3.out &&
	echo $pmidir >libedit3.exp &&
	test_cmp libedit3.exp libedit3.out
'

test_expect_success 'shell: pals shell plugin hates unknown options' '
	test_must_fail_or_be_terminated flux run -o cray-pals.xyz=1 \
	    -o userrc=$(pwd)/$USERRC_NAME true
'
test_expect_success 'shell: pals shell plugin timeout can be set' '
	flux run -o cray-pals.timeout=2 \
	    -o userrc=$(pwd)/$USERRC_NAME true
'
test_expect_success 'shell: pals shell plugin timeout must be a number' '
	test_must_fail_or_be_terminated flux run -o cray-pals.timeout=42s \
	    -o userrc=$(pwd)/$USERRC_NAME true
'
test_expect_success 'shell: pals shell plugin sets environment' '
	environment=$(flux run -o userrc=$(pwd)/$USERRC_NAME -N1 -n1 env) &&
	echo "$environment" | grep PALS_NODEID=0 &&
	echo "$environment" | grep PALS_RANKID=0 &&
	echo "$environment" | grep PALS_APID &&
	echo "$environment" | grep PALS_SPOOL_DIR &&
	echo "$environment" | grep PALS_APINFO &&
	echo "$environment" | test_must_fail grep PMI_CONTROL_PORT &&
	echo "$environment" | test_must_fail grep PMI_SHARED_SECRET
'

test_expect_success 'shell: pals shell plugin sets CONTROL_PORT and SHARED_SECRET' '
	environment=$(flux run -o userrc=$(pwd)/$USERRC_NAME -N2 -n4 env) &&
	(echo "$environment" | grep PMI_CONTROL_PORT=11999,11998 ||
	echo "$environment" | grep PMI_CONTROL_PORT=11998,11999) &&
	echo "$environment" | grep PMI_SHARED_SECRET &&
	echo "$environment" | grep PALS_NODEID=0 &&
	echo "$environment" | grep PALS_RANKID=0 &&
	echo "$environment" | grep PALS_RANKID=1 &&
	echo "$environment" | grep PALS_RANKID=2 &&
	echo "$environment" | grep PALS_RANKID=3
'

test_expect_success 'shell: pals shell plugin creates apinfo file' '
	flux run -o userrc=$(pwd)/$USERRC_NAME -N1 -n1 /bin/bash -c \
	"test ! -z \$PALS_SPOOL_DIR && test -d \$PALS_SPOOL_DIR \
	&& test ! -z \$PALS_APINFO && test -f \$PALS_APINFO"
'

test_expect_success 'shell: apinfo version 1 can be selected' '
	apinfo=$(flux run -o userrc=$(pwd)/$USERRC_NAME -o cray-pals.apinfo-version=1 -N1 -n1 ${PYTHON:-python3} \
	${SHARNESS_TEST_SRCDIR}/scripts/apinfo_checker.py) &&
	echo "$apinfo" | jq -e ".version == 1"
'

test_expect_success 'shell: apinfo file contents are valid for one task' '
	apinfo=$(flux run -o userrc=$(pwd)/$USERRC_NAME -N1 -n1 ${PYTHON:-python3} \
	${SHARNESS_TEST_SRCDIR}/scripts/apinfo_checker.py) &&
	echo "$apinfo" | jq -e ".version == 5" &&
	echo "$apinfo" | jq -e ".cmds[0].npes == 1" &&
	echo "$apinfo" | jq -e ".pes[0].localidx == 0" &&
	echo "$apinfo" | jq -e ".pes[0].cmdidx == 0" &&
	echo "$apinfo" | jq -e ".pes[0].nodeidx == 0" &&
	echo "$apinfo" | jq -e ".nodes[0].id == 0" &&
	test $(hostname) = $(echo "$apinfo" | jq -r .nodes[0].hostname) &&
	echo "$apinfo" | jq ".nics | length == 0" &&
	echo "$apinfo" | jq ".comm_profiles | length == 0" &&
	echo "$apinfo" | jq -e ".nodes | length == 1" &&
	echo "$apinfo" | jq -e ".cmds | length == 1" &&
	echo "$apinfo" | jq -e ".pes | length == 1"
'

test_expect_success 'shell: apinfo file contents are valid for multiple tasks' '
	apinfo=$(flux run -o userrc=$(pwd)/$USERRC_NAME -N1 -n2 --label-io \
	${PYTHON:-python3} ${SHARNESS_TEST_SRCDIR}/scripts/apinfo_checker.py \
	| sed -n "s/^1: //p") &&
	echo "$apinfo" | jq -e ".cmds[0].npes == 2" &&
	echo "$apinfo" | jq -e ".cmds[0].pes_per_node == 2" &&
	echo "$apinfo" | jq -e ".pes[0].localidx == 0" &&
	echo "$apinfo" | jq -e ".pes[1].localidx == 1" &&
	echo "$apinfo" | jq -e ".pes[0].cmdidx == 0" &&
	echo "$apinfo" | jq -e ".pes[1].cmdidx == 0" &&
	echo "$apinfo" | jq -e ".pes[0].nodeidx == 0" &&
	echo "$apinfo" | jq -e ".pes[1].nodeidx == 0" &&
	echo "$apinfo" | jq -e ".nics | length == 0" &&
	echo "$apinfo" | jq -e ".comm_profiles | length == 0" &&
	echo "$apinfo" | jq -e ".nodes | length ==1" &&
	echo "$apinfo" | jq -e ".cmds | length == 1" &&
	echo "$apinfo" | jq -e ".pes | length == 2"
'

test_expect_success 'shell: apinfo file contents are valid for multiple nodes' '
    apinfo=$(flux run -o userrc=$(pwd)/$USERRC_NAME -N2 -n4 --label-io \
    ${PYTHON:-python3} ${SHARNESS_TEST_SRCDIR}/scripts/apinfo_checker.py \
    | sed -n "s/^1: //p") &&
    echo "$apinfo" | jq -e ".cmds[0].npes == 4" &&
    echo "$apinfo" | jq -e ".cmds[0].pes_per_node == 2" &&
    echo "$apinfo" | jq -e ".pes[0].localidx == 0" &&
    echo "$apinfo" | jq -e ".pes[1].localidx == 1" &&
    echo "$apinfo" | jq -e ".pes[2].localidx == 0" &&
    echo "$apinfo" | jq -e ".pes[3].localidx == 1" &&
    echo "$apinfo" | jq -e ".pes[0].cmdidx == 0" &&
    echo "$apinfo" | jq -e ".pes[1].cmdidx == 0" &&
    echo "$apinfo" | jq -e ".pes[0].nodeidx == 0" &&
    echo "$apinfo" | jq -e ".pes[1].nodeidx == 0" &&
    echo "$apinfo" | jq -e ".pes[2].nodeidx == 1" &&
    echo "$apinfo" | jq -e ".pes[3].nodeidx == 1" &&
    echo "$apinfo" | jq -e ".nics | length == 0" &&
    echo "$apinfo" | jq -e ".comm_profiles | length == 0" &&
    echo "$apinfo" | jq -e ".nodes | length == 2" &&
    echo "$apinfo" | jq -e ".cmds | length == 1" &&
    echo "$apinfo" | jq -e ".pes | length == 4"
'

test_expect_success 'shell: apinfo file contents are valid with cyclic task placement' '
    apinfo=$(flux run -o userrc=$(pwd)/$USERRC_NAME -N2 -n4 --label-io --taskmap=cyclic \
    ${PYTHON:-python3} ${SHARNESS_TEST_SRCDIR}/scripts/apinfo_checker.py \
    | sed -n "s/^1: //p") &&
    echo "$apinfo" | jq -e ".cmds[0].npes == 4" &&
    echo "$apinfo" | jq -e ".cmds[0].pes_per_node == 2" &&
    echo "$apinfo" &&
    echo "$apinfo" | jq -e ".pes[0].localidx == 0" &&
    echo "$apinfo" | jq -e ".pes[1].localidx == 0" &&
    echo "$apinfo" | jq -e ".pes[2].localidx == 1" &&
    echo "$apinfo" | jq -e ".pes[3].localidx == 1" &&
    echo "$apinfo" | jq -e ".pes[0].cmdidx == 0" &&
    echo "$apinfo" | jq -e ".pes[1].cmdidx == 0" &&
    echo "$apinfo" | jq -e ".pes[2].cmdidx == 0" &&
    echo "$apinfo" | jq -e ".pes[3].cmdidx == 0" &&
    echo "$apinfo" | jq -e ".pes[0].nodeidx == 0" &&
    echo "$apinfo" | jq -e ".pes[1].nodeidx == 1" &&
    echo "$apinfo" | jq -e ".pes[2].nodeidx == 0" &&
    echo "$apinfo" | jq -e ".pes[3].nodeidx == 1" &&
    echo "$apinfo" | jq -e ".nics | length == 0" &&
    echo "$apinfo" | jq -e ".comm_profiles | length == 0" &&
    echo "$apinfo" | jq -e ".nodes | length == 2" &&
    echo "$apinfo" | jq -e ".cmds | length == 1" &&
    echo "$apinfo" | jq -e ".pes | length == 4"
'

test_expect_success 'shell: apinfo file contents are valid with manual task placement' '
    apinfo=$(flux run -o userrc=$(pwd)/$USERRC_NAME -N2 -n4 --label-io \
    --taskmap="manual:[[1,1,2,1],[0,1,2,1]]" \
    ${PYTHON:-python3} ${SHARNESS_TEST_SRCDIR}/scripts/apinfo_checker.py \
    | sed -n "s/^1: //p") &&
    echo "$apinfo" | jq -e ".cmds[0].npes == 4" &&
    echo "$apinfo" | jq -e ".cmds[0].pes_per_node == 2" &&
    echo "$apinfo" | jq -e ".pes[0].localidx == 0" &&
    echo "$apinfo" | jq -e ".pes[1].localidx == 1" &&
    echo "$apinfo" | jq -e ".pes[2].localidx == 0" &&
    echo "$apinfo" | jq -e ".pes[3].localidx == 1" &&
    echo "$apinfo" | jq -e ".pes[0].cmdidx == 0" &&
    echo "$apinfo" | jq -e ".pes[1].cmdidx == 0" &&
    echo "$apinfo" | jq -e ".pes[2].cmdidx == 0" &&
    echo "$apinfo" | jq -e ".pes[3].cmdidx == 0" &&
    echo "$apinfo" | jq -e ".pes[0].nodeidx == 1" &&
    echo "$apinfo" | jq -e ".pes[1].nodeidx == 1" &&
    echo "$apinfo" | jq -e ".pes[2].nodeidx == 0" &&
    echo "$apinfo" | jq -e ".pes[3].nodeidx == 0" &&
    echo "$apinfo" | jq -e ".nics | length == 0" &&
    echo "$apinfo" | jq -e ".comm_profiles | length == 0" &&
    echo "$apinfo" | jq -e ".nodes | length == 2" &&
    echo "$apinfo" | jq -e ".cmds | length == 1" &&
    echo "$apinfo" | jq -e ".pes | length == 4"
'

test_expect_success 'shell: pals shell plugin handles resource oversubscription' '
	flux run -o userrc=$(pwd)/$USERRC_NAME -N1 -n2 -oper-resource.type=core -oper-resource.count=2 \
	env | grep PALS_RANKID=3 &&
	flux run -o userrc=$(pwd)/$USERRC_NAME -N1 -n1 -oper-resource.type=node -oper-resource.count=6 \
	env | grep PALS_RANKID=5
'

test_expect_success 'shell: pals shell plugin ignores missing jobtap plugin' '
	flux jobtap remove cray_pals_port_distributor.so &&
	flux run -o verbose -o userrc=$(pwd)/$USERRC_NAME \
		-N2 -n2 hostname > no-jobtap.log 2>&1 &&
	test_debug "cat no-jobtap.log" &&
	grep "jobtap plugin is not loaded" no-jobtap.log
'

test_done
