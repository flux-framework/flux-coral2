#!/bin/sh

test_description='Test cray-slingshot shell plugin'

. $(dirname $0)/sharness.sh

SHELL_PLUGINPATH=${FLUX_BUILD_DIR}/src/shell/plugins/.libs
JOBTAP_PLUGINPATH=${FLUX_BUILD_DIR}/src/job-manager/plugins/.libs

# make sure the test environment is clean starting out
unset SLINGSHOT_VNIS
unset SLINGSHOT_DEVICES
unset SLINGSHOT_SVC_IDS
unset SLINGSHOT_TCS

test_under_flux 1

test_expect_success 'unload cray-slingshot jobtap plugin if loaded' '
	flux jobtap remove cray-slingshot.so || :
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
test_expect_success '-o cray-slingshot.badopt fails' '
	! flux run -o cray-slingshot.badopt true 2>badopt.err &&
	grep "left unpacked" badopt.err
'
test_expect_success '-o cray-slingshot=badopt fails' '
	! flux run -o cray-slingshot=badopt true 2>badstropt.err &&
	grep "invalid option" badstropt.err
'
test_expect_success 'SLINGSHOT_VNIS leaks via job env if -o cray-slingshot=off' '
	flux run -o cray-slingshot=off \
	    --env=SLINGSHOT_VNIS=9999 \
	    printenv SLINGSHOT_VNIS
'
test_expect_success 'SLINGSHOT_VNIS does not leak when plugin is enabled' '
	test_must_fail flux run \
	    --env=SLINGSHOT_VNIS=9999 \
	    printenv SLINGSHOT_VNIS
'

##
#  Default mode
##

test_expect_success 'run a job without env or rez' '
	flux run -o verbose=2 printenv >default.out 2>default.err
'
test_expect_success 'job is running in default mode' '
	grep "cray-slingshot: no job environment is set" default.err
'
test_expect_success 'the slingshot environment is not set' '
	test_must_fail grep SLINGSHOT_VNIS default.out &&
	test_must_fail grep SLINGSHOT_DEVICES default.out &&
	test_must_fail grep SLINGSHOT_SVC_IDS default.out &&
	test_must_fail grep SLINGSHOT_TCS default.out
'

##
#  Inherit mode
##

test_expect_success 'run a job with broker SLINGSHOT_ environment' '
	flux alloc -N1 -o cray-slingshot=off \
	    --env=SLINGSHOT_VNIS=999 \
	    --env=SLINGSHOT_DEVICES=cxi0,cxi1 \
	    --env=SLINGSHOT_SVC_IDS=42,43 \
	    --env=SLINGSHOT_TCS=0x0a \
	    sh -c "flux setattr conf.shell_initrc testrc.lua &&
	    flux run -o verbose=2 printenv >inherit.out 2>inherit.err"
'
test_expect_success 'job is running in inherited mode' '
	grep "cray-slingshot: using inherited job environment" inherit.err
'
test_expect_success 'the slingshot environment is inherited' '
	grep SLINGSHOT_VNIS=999 inherit.out &&
	grep SLINGSHOT_DEVICES=cxi0,cxi1 inherit.out &&
	grep SLINGSHOT_SVC_IDS=42,43 inherit.out &&
	grep SLINGSHOT_TCS=0x0a inherit.out
'

##
#  Reservation mode
##

test_expect_success 'load the cray-slingshot jobtap plugin' '
	flux jobtap load $JOBTAP_PLUGINPATH/cray-slingshot.so
'
test_expect_success 'run a job with VNI reservation' '
	flux run -o verbose=2 printenv >rez.out 2>rez.err
'
test_expect_success 'job is running in reservation mode' '
	grep "cray-slingshot: setting environment for VNI reservation" rez.err
'
# CI: SLINGSHOST_VNIS will be set even if there are no devices present
test_expect_success 'SLINGSHOT_VNIS=1024' '
	grep SLINGSHOT_VNIS=1024 rez.out
'
test_expect_success 'SLINGSHOT_TCS=0xf' '
	grep SLINGSHOT_TCS=0xf rez.out
'
test_expect_success 'run a job that requests two vnis' '
	flux run -o verbose=2 -o cray-slingshot.vnicount=2 \
	    printenv SLINGSHOT_VNIS >rez2.out 2>rez2.err
'
test_expect_success 'job is running in reservation mode' '
	grep "cray-slingshot: setting environment for VNI reservation" rez2.err
'
test_expect_success 'SLINGSHOT_VNIS=1025,1026' '
	grep 1025,1026 rez2.out
'
test_expect_success 'run a job that requests zero vnis' '
	flux run -o verbose=2 -o cray-slingshot.vnicount=0 \
	    printenv >rez0.out 2>rez0.err
'
test_expect_success 'job is running in reservation mode' '
	grep "cray-slingshot: setting environment for VNI reservation" rez0.err
'
test_expect_success 'SLINGSHOT_VNIS is not set' '
	test_must_fail grep SLINGSHOT_VNIS rez0.out
'
test_expect_success 'SLINGSHOT_TCS=0xf' '
	grep SLINGSHOT_TCS=0xf rez0.out
'

test_done
