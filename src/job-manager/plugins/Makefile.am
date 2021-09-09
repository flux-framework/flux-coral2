AM_CFLAGS = \
	$(WARNING_CFLAGS) \
	$(CODE_COVERAGE_CFLAGS) \
    $(FLUX_CORE_CFLAGS)

AM_LDFLAGS = \
	$(CODE_COVERAGE_LIBS)

jobtapdir = \
    $(fluxlibdir)/job-manager/

jobtap_LTLIBRARIES = \
	dws-jobtap.la \
	cray_pals_port_distributor.la

dws_jobtap_la_SOURCES = \
	dws-jobtap.c

dws_jobtap_la_LDFLAGS = \
	$(AM_LDFLAGS) \
	-module \
	-avoid-version

dws_jobtap_la_LIBADD= \
    $(FLUX_CORE_LDFLAGS)

cray_pals_port_distributor_la_SOURCES = \
	cray_pals_port_distributor.c

cray_pals_port_distributor_la_LDFLAGS = \
	$(AM_LDFLAGS) \
	-module \
	-avoid-version

cray_pals_port_distributor_la_LIBADD= \
    $(FLUX_CORE_LIBS) \
    $(FLUX_HOSTLIST_LIBS)
