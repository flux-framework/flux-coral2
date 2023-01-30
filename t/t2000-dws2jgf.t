#!/bin/sh

test_description='Test dws2jgf command'

. $(dirname $0)/sharness.sh

CMD=${FLUX_SOURCE_DIR}/src/cmd/flux-dws2jgf.py
DATADIR=${SHARNESS_TEST_SRCDIR}/data/dws2jgf

export FLUX_PYCLI_LOGLEVEL=10

# Have to set HOME to the proper location so that the kubernetes
# module can automatically detect the ~/.kube/config
test_expect_failure DWS_K8S 'flux-dws2jgf.py outputs expected JGF' '
	HOME=$REAL_HOME flux python ${CMD} --test-pattern "flux-test-.*" | jq . > actual.jgf &&
	test_cmp ${DATADIR}/expected.jgf actual.jgf
'

# TODO: get a stable Storage configuration into DWS's kind environment
# for testing against.

test_done
