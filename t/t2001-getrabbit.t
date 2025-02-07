#!/bin/sh

test_description='Test getrabbit command'

. $(dirname $0)/sharness.sh

FLUX_SIZE=2

test_under_flux ${FLUX_SIZE} job

flux setattr log-stderr-level 1

CMD="flux python ${FLUX_SOURCE_DIR}/src/cmd/flux-getrabbit.py"
DATADIR=${SHARNESS_TEST_SRCDIR}/data/getrabbit

export FLUX_PYCLI_LOGLEVEL=10


test_expect_success 'flux rabbitmapping works on rabbits' '
    echo "
[rabbit]
mapping = \"$DATADIR/rzadams_rabbitmapping\"
    " | flux config load &&
    test $($CMD rzadams201 | flux hostlist -c) -eq 16 &&
    test $($CMD rzadams201 | flux hostlist -n0) = rzadams1001 &&
    test $($CMD rzadams202 | flux hostlist -c) -eq 16 &&
    test $($CMD rzadams202 | flux hostlist -n15) = rzadams1032 &&
    test $($CMD rzadams203 | flux hostlist -c) -eq 16 &&
    test $($CMD rzadams204 | flux hostlist -c) -eq 16 &&
    test $($CMD rzadams205 | flux hostlist -c) -eq 16 &&
    test $($CMD rzadams206 | flux hostlist -c) -eq 16 &&
    test $($CMD rzadams207 | flux hostlist -c) -eq 16 &&
    test $($CMD rzadams208 | flux hostlist -c) -eq 16
'

test_expect_success 'flux rabbitmapping works on computes' '
    test $($CMD -c rzadams1001) = rzadams201 &&
    test $($CMD -c rzadams1032) = rzadams202 &&
    test $($CMD -c rzadams[1001,1032]) = rzadams[201-202]
'

test_expect_success 'flux rabbitmapping parses arguments correctly' '
	test_must_fail $CMD --computes &&
	test_must_fail $CMD rzadams201 -c rzadams1001
'

test_expect_success 'flux rabbitmapping works with second mapping' '
    echo "
[rabbit]
mapping = \"$DATADIR/tuolumne_rabbitmapping\"
    " | flux config load &&
    test $($CMD tuolumne270 | flux hostlist -c) -eq 16 &&
    test $($CMD tuolumne270 | flux hostlist -n0) = tuolumne2105 &&
    test $($CMD tuolumne[270-271] | flux hostlist -c) -eq 32
'

test_expect_success 'flux rabbitmapping works on computes with second mapping' '
    test $($CMD -c tuolumne[1385-1416]) = tuolumne[225-226]
'

test_expect_success 'flux rabbitmapping works with no arguments' '
    test $($CMD) = tuolumne[201-272]
'

test_done
