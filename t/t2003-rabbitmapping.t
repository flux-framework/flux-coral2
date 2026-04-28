#!/bin/sh

test_description='Test rabbitmapping command'

. $(dirname $0)/sharness.sh

FLUX_SIZE=1

test_under_flux ${FLUX_SIZE} job -Slog-stderr-level=1

CMD=${FLUX_SOURCE_DIR}/src/cmd/flux-rabbitmapping.py
DATADIR=${SHARNESS_TEST_SRCDIR}/data/rabbitmapping

export FLUX_PYCLI_LOGLEVEL=10
# Have to set so kubernetes can automatically detect the ~/.kube/config
export KUBECONFIG=${REAL_HOME}/.kube/config

if test_have_prereq NO_DWS_K8S; then
    skip_all='skipping rabbitmapping tests due to no DWS K8s'
    test_done
fi

test_expect_success 'smoke test to ensure the storage resources are expected' '
	test $(kubectl get storages | wc -l) -eq 3 &&
	kubectl get storages kind-worker2 -ojson | jq -e ".status.access.computes | length == 3" &&
	kubectl get storages kind-worker2 -ojson | jq -e ".status.access.computes[0].name == \"compute-01\"" &&
	kubectl get storages kind-worker2 -ojson | jq -e ".status.access.computes[1].name == \"compute-02\"" &&
	kubectl get storages kind-worker2 -ojson | jq -e ".status.access.computes[2].name == \"compute-03\"" &&
	kubectl get storages kind-worker3 -ojson | jq -e ".status.access.computes | length == 1" &&
	kubectl get storages kind-worker3 -ojson | jq -e ".status.access.computes[0].name == \"compute-04\""
'

test_expect_success 'flux-rabbitmapping outputs expected mapping' '
	flux python ${CMD} -i2 > rabbits-basic.json &&
	# add a newline to make the files the same
	echo >> rabbits-basic.json &&
	test_cmp ${DATADIR}/rabbits-basic.json rabbits-basic.json
'

test_expect_success 'flux-rabbitmapping works with compact output' '
	flux python ${CMD} > rabbits-compact.json &&
	test $(jq ".computes | length" rabbits-compact.json) -eq 4 &&
	test $(jq ".rabbits | length" rabbits-compact.json) -eq 2 &&
	test $(jq -r ".computes[\"compute-01\"]" rabbits-compact.json) = "kind-worker2" &&
	test $(jq -r ".computes[\"compute-04\"]" rabbits-compact.json) = "kind-worker3"
'

test_expect_success 'flux-rabbitmapping generates capacity field' '
	flux python ${CMD} -i2 > rabbits-capacity.json &&
	jq -e ".rabbits[\"kind-worker2\"].capacity" rabbits-capacity.json &&
	jq -e ".rabbits[\"kind-worker3\"].capacity" rabbits-capacity.json
'

test_expect_success 'flux-rabbitmapping generates hostlist field' '
	flux python ${CMD} -i2 > rabbits-hostlist.json &&
	test $(jq -r ".rabbits[\"kind-worker2\"].hostlist" rabbits-hostlist.json) = "compute-[01-03]" &&
	test $(jq -r ".rabbits[\"kind-worker3\"].hostlist" rabbits-hostlist.json) = "compute-04"
'

test_expect_success 'flux-rabbitmapping respects --nosort flag' '
	flux python ${CMD} --nosort > rabbits-nosort.json &&
	jq -e ".computes" rabbits-nosort.json &&
	jq -e ".rabbits" rabbits-nosort.json
'

test_expect_success 'create external Servers allocation for testing' '
	cat > systemstorage.yaml <<-EOF &&
apiVersion: nnf.cray.hpe.com/v1alpha11
kind: NnfSystemStorage
metadata:
  name: example
  namespace: default
spec:
  excludeDisabledRabbits: true
  type: "xfs"
  capacity: 5000000000
  computesTarget: "all"
  makeClientMounts: false
  ignoreOfflineComputes: true
  shared: false
  storageProfile:
    name: default
    namespace: nnf-system
    kind: NnfStorageProfile
EOF
	kubectl apply -f systemstorage.yaml
'

test_expect_success 'flux-rabbitmapping reduces capacity by external allocations' '
	flux python ${CMD} -i2 > rabbits-reduced.json &&
	orig_capacity=$(jq ".rabbits[\"kind-worker2\"].capacity" ${DATADIR}/rabbits-basic.json) &&
	new_capacity=$(jq ".rabbits[\"kind-worker2\"].capacity" rabbits-reduced.json) &&
	test $new_capacity -lt $orig_capacity
'

test_expect_success 'flux-rabbitmapping --ignore-external-allocations shows full capacity' '
	flux python ${CMD} --ignore-external-allocations -i2 > rabbits-ignored.json &&
	# add a newline to make the files the same
	echo >> rabbits-ignored.json &&
	test_cmp ${DATADIR}/rabbits-basic.json rabbits-ignored.json
'

test_expect_success 'delete example systemstorage' '
	kubectl delete nnfsystemstorage example
'

test_expect_success 'flux-rabbitmapping ignores Flux-managed Servers' '
	cat > systemstorage_namedflux.yaml <<-EOF &&
apiVersion: nnf.cray.hpe.com/v1alpha11
kind: NnfSystemStorage
metadata:
  name: fluxjob-example
  namespace: default
spec:
  excludeDisabledRabbits: true
  type: "xfs"
  capacity: 5000000000
  computesTarget: "all"
  makeClientMounts: false
  ignoreOfflineComputes: true
  shared: false
  storageProfile:
    name: default
    namespace: nnf-system
    kind: NnfStorageProfile
EOF
	kubectl apply -f systemstorage_namedflux.yaml &&
	flux python ${CMD} -i2 > rabbits-flux-managed.json &&
	echo >> rabbits-flux-managed.json &&
	test_cmp ${DATADIR}/rabbits-basic.json rabbits-flux-managed.json
'

test_expect_success 'delete example fluxjob systemstorage' '
	kubectl delete nnfsystemstorage fluxjob-example
'

test_expect_success 'flux-rabbitmapping capacity never goes negative' '
	cat > huge_systemstorage.yaml <<-EOF &&
apiVersion: nnf.cray.hpe.com/v1alpha11
kind: NnfSystemStorage
metadata:
  name: example
  namespace: default
spec:
  excludeDisabledRabbits: true
  type: "xfs"
  capacity: 50000000000000
  computesTarget: "all"
  makeClientMounts: false
  ignoreOfflineComputes: true
  shared: false
  storageProfile:
    name: default
    namespace: nnf-system
    kind: NnfStorageProfile
EOF
	kubectl apply -f huge_systemstorage.yaml &&
	flux python ${CMD} -i2 > rabbits-huge-alloc.json &&
	capacity=$(jq ".rabbits[\"kind-worker2\"].capacity" rabbits-huge-alloc.json) &&
	test $capacity -eq 0
'

test_expect_success 'cleanup external Servers allocations' '
	kubectl delete nnfsystemstorage example
'

test_done
