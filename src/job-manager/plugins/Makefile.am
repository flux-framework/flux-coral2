AM_CFLAGS = \
	$(WARNING_CFLAGS) \
	$(CODE_COVERAGE_CFLAGS) \
    $(FLUX_CORE_CFLAGS)

AM_LDFLAGS = \
	$(CODE_COVERAGE_LIBS)

jobtapdir = \
    $(fluxlibdir)/job-manager/

jobtap_LTLIBRARIES = dws-jobtap.la

dws_jobtap_la_SOURCES = \
	dws-jobtap.c

dws_jobtap_la_LDFLAGS = \
	$(AM_LDFLAGS) \
	-module \
	-avoid-version

dws_jobtap_la_LIBADD= \
    $(FLUX_CORE_LDFLAGS)

