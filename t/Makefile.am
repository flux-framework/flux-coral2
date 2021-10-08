AM_CFLAGS = \
	$(WARNING_CFLAGS) \
	$(CODE_COVERAGE_CFLAGS)

AM_LDFLAGS = \
	$(CODE_COVERAGE_LIBS)

AM_TESTS_ENVIRONMENT = \
	test -n "$$FLUX_TEST_INSTALLED_PATH" && \
	export PYTHONPATH="$(PYTHON_SITE_PKG):$$PYTHONPATH";\
	export PYTHON="${PYTHON}";\
	export PATH="$(FLUX_PREFIX)/bin:$(PATH)";

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
	t2000-dws2jgf.t

# make check runs these TAP tests directly (both scripts and programs)
TESTS = \
	$(TESTSCRIPTS)

EXTRA_DIST= \
	aggregate-results.sh \
	sharness.sh \
	sharness.d \
	$(T)

dist_check_SCRIPTS = \
	$(TESTSCRIPTS)

check-prep:
	$(MAKE)

	