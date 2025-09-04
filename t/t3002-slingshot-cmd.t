#!/bin/sh

test_description='Test flux-slingshot command'

. $(dirname $0)/sharness.sh

SHELL_PLUGINPATH=${FLUX_BUILD_DIR}/src/shell/plugins/.libs
JOBTAP_PLUGINPATH=${FLUX_BUILD_DIR}/src/job-manager/plugins/.libs
SLINGSHOT_CMD=${FLUX_BUILD_DIR}/src/cmd/flux-slingshot

# make sure the test environment is clean starting out
unset SLINGSHOT_VNIS
unset SLINGSHOT_DEVICES
unset SLINGSHOT_SVC_IDS
unset SLINGSHOT_TCS

test_under_flux 1

test_expect_success 'load the cray-slingshot jobtap plugin' '
	flux jobtap load $JOBTAP_PLUGINPATH/cray-slingshot.so
'
test_expect_success 'override site shell initrc to load devel cray-slingshot' '
	cat >testrc.lua <<-EOT &&
	plugin.load {
	    file = "$SHELL_PLUGINPATH/cray-slingshot.so",
	    conf = { }
	}
	EOT
	flux setattr conf.shell_initrc testrc.lua
'

test_expect_success 'flux-slingshot list works' '
	$SLINGSHOT_CMD list
'
test_expect_success 'flux-slingshot list --no-header works' '
	$SLINGSHOT_CMD list --no-header >listnh.out &&
	test_must_fail grep Name listnh.out
'
test_expect_success 'flux-slingshot jobinfo works' '
	flux run $SLINGSHOT_CMD jobinfo >jobinfo.json
'
test_expect_success 'job has vni 1024 reserved' '
	jq -e ".vnis == [1024]" <jobinfo.json
'
test_expect_success 'flux-slingshot jobinfo --jobid works' '
	$SLINGSHOT_CMD jobinfo --jobid=$(flux job last) >jobinfo2.json &&
	jq -e ".vnis == [1024]" <jobinfo2.json
'
test_expect_success 'flux-slingshot prolog --dry-run works' '
	flux run -n1 \
	    $SLINGSHOT_CMD prolog --dry-run --userid=$(id -u) 2>prolog.err
'
test_expect_success 'ncores is 1' '
	grep "ncores=1 vnis=\[1025\]" prolog.err
'
test_expect_success 'flux-slingshot prolog --jobid works' '
	$SLINGSHOT_CMD prolog --dry-run --userid=$(id -u) \
	    --jobid=$(flux job last)
'
test_expect_success 'flux-slingshot epilog --dry-run works' '
	flux run -n1 \
	    $SLINGSHOT_CMD epilog --dry-run --userid=$(id -u)
'
test_expect_success 'flux-slingshot epilog --jobid works' '
	$SLINGSHOT_CMD epilog --dry-run --userid=$(id -u) \
	    --jobid=$(flux job last)
'
test_expect_success 'flux-slingshot epilog --retry-busy=FSD can be specified' '
	$SLINGSHOT_CMD epilog --dry-run --userid=$(id -u) \
	    --jobid=$(flux job last) --retry-busy=10s
'
test_expect_success 'flux-slingshot epilog --retry-busy=badfsd fails' '
	test_must_fail $SLINGSHOT_CMD epilog --dry-run --userid=$(id -u) \
	    --jobid=$(flux job last) --retry-busy=badfsd
'
test_expect_success 'flux-slingshot clean --dry-run works' '
	$SLINGSHOT_CMD clean --dry-run
'

test_done
