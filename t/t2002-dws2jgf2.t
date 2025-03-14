#!/bin/sh

test_description='Test dws2jgf command with no dws'

. $(dirname $0)/sharness.sh

FLUX_SIZE=2

test_under_flux ${FLUX_SIZE} job

flux setattr log-stderr-level 1

CMD=${FLUX_SOURCE_DIR}/src/cmd/flux-dws2jgf.py
DATADIR=${SHARNESS_TEST_SRCDIR}/data/dws2jgf2

export FLUX_PYCLI_LOGLEVEL=10


test_expect_success 'dws2jgf works from config' '
	flux python ${CMD} --no-validate --from-config $DATADIR/resource.toml \
		--only-sched $DATADIR/rabbitmapping.json | jq . > from_config.jgf &&
	test -s from_config.jgf
'

test_expect_success 'dws2jgf sets properties on nodes not in rabbitmapping' "
	jq -e '.graph.nodes[].metadata | select(.name==\"somecluster42\") \
		| .properties.mi300a == \"\"' from_config.jgf &&
	jq -e '.graph.nodes[].metadata | select(.name==\"somecluster43\") \
		| .properties.mi300a == \"\"' from_config.jgf
"

test_expect_success 'dws2jgf sets properties on nodes in rabbitmapping' "
	jq -e '.graph.nodes[].metadata | select(.name==\"somecluster14\") \
		| .properties.pci == \"\"' from_config.jgf &&
	jq -e '.graph.nodes[].metadata | select(.name==\"somecluster15\") \
		| .properties.pci == \"\"' from_config.jgf &&
	jq -e '.graph.nodes[].metadata | select(.name==\"somecluster18\") \
		| .properties.pdebug == \"\"' from_config.jgf &&
	jq -e '.graph.nodes[].metadata | select(.name==\"somecluster40\") \
		| .properties.pdebug == \"\"' from_config.jgf
"

test_done
