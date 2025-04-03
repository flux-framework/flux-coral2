AM_CFLAGS = \
	$(WARNING_CFLAGS) \
	$(CODE_COVERAGE_CFLAGS)

AM_LDFLAGS = \
	$(CODE_COVERAGE_LIBS)

AM_TESTS_ENVIRONMENT = \
	test -n "$$FLUX_TEST_INSTALLED_PATH" && \
	export PYTHON="${PYTHON}";\
	export PATH="$(FLUX_PREFIX)/bin:$(PATH)";\
	export PYTHONPATH="$(top_srcdir)/src/python:$(PYTHON_SITE_PKG):$$PYTHONPATH";

TEST_EXTENSIONS = .t .py
T_LOG_DRIVER = env AM_TAP_AWK='$(AWK)' $(SHELL) \
	$(top_srcdir)/config/tap-driver.sh
PY_LOG_DRIVER = $(PYTHON) $(top_srcdir)/config/tap-driver.py

clean-local:
	rm -fr trash-directory.* test-results .prove *.broker.log */*.broker.log *.output python/__pycache__

# This list is included in both TESTS and dist_check_SCRIPTS.
TESTSCRIPTS = \
	t0000-sharness.t \
	t1000-dws-dependencies.t \
	t1001-cray-pals.t \
	t1002-dws-workflow-obj.t \
	t1003-dws-nnf-watch.t \
	t1004-dws-environment.t \
	t2000-dws2jgf.t \
	t2001-getrabbit.t \
	t2002-dws2jgf2.t \
	python/t0001-directive-breakdown.py

# make check runs these TAP tests directly (both scripts and programs)
TESTS = \
	$(TESTSCRIPTS)

EXTRA_DIST= \
	aggregate-results.sh \
	sharness.sh \
	sharness.d \
	data \
	$(T)

dist_check_SCRIPTS = \
	scripts/run_timeout.py \
	scripts/apinfo_checker.py \
	scripts/set_status.py \
	scripts/sign-as.py \
	scripts/coral2_inspection.py \
	rc/rc1-job \
	rc/rc3-job \
	python/pycotap \
	dws-dependencies/coral2_dws.py \
	$(TESTSCRIPTS)

check_PROGRAMS = \
	util/rpc

util_rpc_SOURCES = util/rpc.c
util_rpc_CFLAGS = $(FLUX_CORE_CFLAGS)
util_rpc_LDADD = $(FLUX_CORE_LIBS)

check-prep:
	$(MAKE) $(check_PROGRAMS)

