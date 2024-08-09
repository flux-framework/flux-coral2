#!/bin/sh

test_description='Test dws_environment shell plugin'

. $(dirname $0)/sharness.sh

test_under_flux 2 job

flux setattr log-stderr-level 1

SHELL_PLUGINPATH=${FLUX_BUILD_DIR}/src/shell/plugins/.libs
USERRC_NAME="dws_environment.lua"


test_expect_success 'shell: create shell initrc for testing' "
	cat >$USERRC_NAME <<-EOT
	plugin.load { file = \"$SHELL_PLUGINPATH/dws_environment.so\", conf = { } }
	EOT
"

test_expect_success 'shell: jobs with no DW attr succeed when plugin loaded' '
	flux run -o userrc=$(pwd)/$USERRC_NAME true
'

test_expect_success 'shell: jobs with DW attr fail when plugin loaded and no eventlog entry' '
	test_must_fail flux run -o userrc=$(pwd)/$USERRC_NAME \
		--setattr=dw="foo" true
'

test_expect_success 'shell: plugin sets env vars properly' '
	depend_job=$(flux submit sleep 10) &&
	jobid=$(flux submit -o userrc=$(pwd)/$USERRC_NAME \
		--setattr=dw="foo" --dependency=afterany:$depend_job env) &&
	kvsdir=$(flux job id --to=kvs $jobid) &&
	flux kvs eventlog append ${kvsdir}.eventlog dws_environment \
		"{\"variables\":{\"DWS_TEST_VAR1\": \"foo\", \"DWS_TEST_VAR2\": \"bar\"}, \
		\"rabbits\":{\"rabbit1\": \"$(hostname)\"}}" &&
	flux cancel $depend_job &&
	environment=$(flux job attach ${jobid}) &&
	echo "$environment" | grep DWS_TEST_VAR1=foo &&
	echo "$environment" | grep DWS_TEST_VAR2=bar &&
	echo "$environment" | grep FLUX_LOCAL_RABBIT=rabbit1
	'

test_expect_success 'shell: plugin sets env vars properly with multiple rabbits' '
	depend_job=$(flux submit sleep 10) &&
	jobid=$(flux submit -o userrc=$(pwd)/$USERRC_NAME \
		--setattr=dw="foo" --dependency=afterany:$depend_job env) &&
	kvsdir=$(flux job id --to=kvs $jobid) &&
	flux kvs eventlog append ${kvsdir}.eventlog dws_environment \
		"{\"variables\":{\"DWS_TEST_VAR1\": \"foo\", \"DWS_TEST_VAR2\": \"bar\"}, \
		\"rabbits\":{\"rabbit96\": \"compute[265-1056]\", \"rabbit7\": \"compute[01-72]\", \
		\"rabbit15\": \"$(hostname)\"}}" &&
	flux cancel $depend_job &&
	environment=$(flux job attach ${jobid}) &&
	echo "$environment" | grep DWS_TEST_VAR1=foo &&
	echo "$environment" | grep DWS_TEST_VAR2=bar &&
	echo "$environment" | grep FLUX_LOCAL_RABBIT=rabbit15
	'

test_done
