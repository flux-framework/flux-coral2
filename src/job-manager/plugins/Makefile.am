AM_CFLAGS = \
	$(WARNING_CFLAGS) \
	$(CODE_COVERAGE_CFLAGS)

AM_LDFLAGS = \
	$(CODE_COVERAGE_LIBS)

AM_CPPFLAGS = \
	$(FLUX_CORE_CFLAGS) \
	$(FLUX_HOSTLIST_CFLAGS) \
	$(SODIUM_CFLAGS) \
	$(JANSSON_CFLAGS)

jobtapdir = \
	$(fluxlibdir)/job-manager/plugins/

jobtap_LTLIBRARIES = \
	dws-jobtap.la \
	cray-pmi-bootstrap.la

dws_jobtap_la_SOURCES = \
	dws-jobtap.c

dws_jobtap_la_LDFLAGS = \
	$(AM_LDFLAGS) \
	-module \
	-avoid-version

dws_jobtap_la_LIBADD= \
	$(FLUX_CORE_LIBS) \
	$(JANSSON_LIBS)

cray_pmi_bootstrap_la_SOURCES = \
	cray-pmi-bootstrap.c

cray_pmi_bootstrap_la_LDFLAGS = \
	$(AM_LDFLAGS) \
	-module \
	-avoid-version

cray_pmi_bootstrap_la_LIBADD= \
	$(FLUX_CORE_LIBS) \
	$(SODIUM_LIBS) \
	$(FLUX_HOSTLIST_LIBS) \
	$(JANSSON_LIBS)
