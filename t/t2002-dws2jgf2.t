#!/bin/sh

test_description='Test dws2jgf command with no dws'

. $(dirname $0)/sharness.sh

if ! test_have_prereq FLUXION; then
	skip_all='skipping tests since fluxion is not installed'
	test_done
fi

FLUX_SIZE=2

test_under_flux ${FLUX_SIZE} job -Slog-stderr-level=1

CMD=${FLUX_SOURCE_DIR}/src/cmd/flux-dws2jgf.py
DATADIR=${SHARNESS_TEST_SRCDIR}/data/dws2jgf2
JOBSPEC1=${SHARNESS_TEST_SRCDIR}/data/dws2jgf/rabbit-jobspec.json

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

test_expect_success 'JGF has rabbits as down' "
	jq -e '.graph.nodes[].metadata | select(.type==\"ssd\") \
		| .status == 1' from_config.jgf
"

test_expect_success 'generate local rabbitmapping' "
	cat > rabbits.json <<-EOF &&
	{\"computes\":{\"$(hostname)\":\"rabbit1\"},
\"rabbits\":{\"rabbit1\":{\"capacity\":100000000000,
\"hostlist\":\"$(hostname)\"}}}
EOF
	jq -e '.computes.\"$(hostname)\" == \"rabbit1\"' rabbits.json
"

test_expect_success 'dws2jgf accepts an IDset resource.exclude' "
	cat > idset.toml <<-EOF &&
	[resource]
	exclude = \"1\"

	[[resource.config]]
	hosts = \"somecluster[0-3]\"
	cores = \"0-3\"
	EOF
	flux python \${CMD} --no-validate --from-config idset.toml \
		--only-sched \$DATADIR/rabbitmapping.json | jq . > idset.jgf &&
	test \$(jq '[.graph.nodes[].metadata.name \
		| select(. == \"somecluster1\")] | length' idset.jgf) -eq 0 &&
	jq -e 'any(.graph.nodes[].metadata.name; . == \"somecluster0\")' idset.jgf &&
	jq -e 'any(.graph.nodes[].metadata.name; . == \"somecluster2\")' idset.jgf &&
	jq -e 'any(.graph.nodes[].metadata.name; . == \"somecluster3\")' idset.jgf
"

test_expect_success 'dws2jgf accepts a Hostlist resource.exclude' "
	cat > hostlist.toml <<-EOF &&
	[resource]
	exclude = \"somecluster3\"

	[[resource.config]]
	hosts = \"somecluster[0-3]\"
	cores = \"0-3\"
	EOF
	flux python \${CMD} --no-validate --from-config hostlist.toml \
		--only-sched \$DATADIR/rabbitmapping.json | jq . > hostlist.jgf &&
	test \$(jq '[.graph.nodes[].metadata.name \
		| select(. == \"somecluster3\")] | length' hostlist.jgf) -eq 0 &&
	jq -e 'any(.graph.nodes[].metadata.name; . == \"somecluster0\")' hostlist.jgf &&
	jq -e 'any(.graph.nodes[].metadata.name; . == \"somecluster1\")' hostlist.jgf &&
	jq -e 'any(.graph.nodes[].metadata.name; . == \"somecluster2\")' hostlist.jgf
"

test_expect_success 'fluxion can be loaded with output of dws2jgf' '
	flux run -n1 hostname &&
	flux R encode -l | flux python ${CMD} --no-validate -c1 rabbits.json \
		| jq . > R.local &&
	flux kvs put resource.R="$(cat R.local)" &&
	flux module list &&
	flux module remove -f sched-fluxion-qmanager &&
	flux module remove -f sched-fluxion-resource &&
	flux module reload resource &&
	flux module load sched-fluxion-resource &&
	flux module load sched-fluxion-qmanager &&
	flux run -n1 true
'

test_expect_success 'rabbits start out as down and are not allocated' '
	flux ion-resource find status=down --format=jgf | grep \"ssd\" &&
	flux ion-resource find status=up --format=jgf | test_must_fail grep \"ssd\"
	JOBID=$(flux job submit $JOBSPEC1) &&
	test_must_fail flux job wait-event -vt 3 ${JOBID} alloc &&
	flux cancel $JOBID
'

test_expect_success 'edit R to make rabbits up' "
	sed -e 's/\"status\": 1/\"status\": 0/g' R.local > R2.local &&
	jq -e '.scheduling.graph.nodes[].metadata | select(.type==\"ssd\") \
		| .status == 0' R2.local
"

test_expect_success 'fluxion can run an node/ssd jobspec' '
	flux kvs put resource.R="$(cat R2.local)" &&
	flux module remove -f sched-fluxion-qmanager &&
	flux module remove -f sched-fluxion-resource &&
	flux module reload resource &&
	flux module load sched-fluxion-resource &&
	flux module load sched-fluxion-qmanager &&
	jobid=$(flux job submit $JOBSPEC1) && flux job attach $jobid
'

test_expect_success 'unload fluxion modules' '
	flux module remove sched-fluxion-qmanager &&
	flux module remove sched-fluxion-resource
'

test_done
