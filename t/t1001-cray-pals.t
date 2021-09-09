#!/bin/sh

test_description='Test cray_pals jobtap and shell plugins'

JOBTAP_PLUGINPATH=${FLUX_BUILD_DIR}/src/job-manager/plugins/.libs
SHELL_PLUGINPATH=${FLUX_BUILD_DIR}/src/shell/plugins/.libs
USERRC_NAME="cray_pals.lua"

. $(dirname $0)/sharness.sh

test_under_flux 2 job

flux setattr log-stderr-level 1

test_expect_success 'job-manager: load cray_pals_port_distributor plugin' '
	flux jobtap load ${JOBTAP_PLUGINPATH}/cray_pals_port_distributor.so \
	    port-min=11000 port-max=12000 &&
	flux jobtap list -a | grep cray_pals_port_distributor.so
'

test_expect_success 'job-manager: pals port distributor works' '
	jobid=$(flux mini submit -N2 -n2 true) &&
	flux job wait-event -vt 15 ${jobid} cray_port_distribution &&
	flux job wait-event -mports=[11999,11998] ${jobid} cray_port_distribution &&
	flux job wait-event -vt 5 ${jobid} clean
'

test_expect_success 'job-manager: pals port distributor saves ports for multi-shell jobs' '
	jobid=$(flux mini submit -n1 true) &&
	test_must_fail flux job wait-event -vt 15 ${jobid} cray_port_distribution
'

# as long as it's only ever one job at a time the ports should be deterministic
test_expect_success 'job-manager: pals port distributor reclaims ports' '
	flux mini run -N2 -n2 true &&
	jobid=$(flux mini submit -N2 -n2 true) &&
	flux job wait-event -vt 15 ${jobid} cray_port_distribution &&
	(flux job wait-event -mports=[11999,11998] ${jobid} cray_port_distribution ||
	flux job wait-event -mports=[11998,11999] ${jobid} cray_port_distribution) &&
	flux job wait-event -vt 5 ${jobid} clean
'

test_expect_success 'shell: pals shell plugin sets environment' '
	echo "
	plugin.load { file = \"$SHELL_PLUGINPATH/cray_pals.so\", conf = { } }
	" > $USERRC_NAME &&
	environment=$(flux mini run -o userrc=$(pwd)/$USERRC_NAME -N1 -n1 env) &&
	echo "$environment" | grep PALS_NODEID=0 &&
	echo "$environment" | grep PALS_RANKID=0 &&
	echo "$environment" | grep PALS_APID &&
	echo "$environment" | grep PALS_SPOOL_DIR &&
	echo "$environment" | grep PALS_APINFO &&
	echo "$environment" | test_must_fail grep PMI_CONTROL_PORT
'

test_expect_success 'shell: pals shell plugin sets PMI_CONTROL_PORT' '
	environment=$(flux mini run -o userrc=$(pwd)/$USERRC_NAME -N2 -n4 env) &&
	(echo "$environment" | grep PMI_CONTROL_PORT=11999,11998 ||
	echo "$environment" | grep PMI_CONTROL_PORT=11998,11999) &&
	echo "$environment" | grep PALS_NODEID=0 &&
	echo "$environment" | grep PALS_RANKID=0 &&
	echo "$environment" | grep PALS_RANKID=1 &&
	echo "$environment" | grep PALS_RANKID=2 &&
	echo "$environment" | grep PALS_RANKID=3
'

test_expect_success 'shell: pals shell plugin creates apinfo file' '
	flux mini run -o userrc=$(pwd)/$USERRC_NAME -N1 -n1 /bin/bash -c \
	"test ! -z \$PALS_SPOOL_DIR && test -d \$PALS_SPOOL_DIR \
	&& test ! -z \$PALS_APINFO && test -f \$PALS_APINFO"
'

test_done
