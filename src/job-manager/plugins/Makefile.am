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
	cray_pals_port_distributor.la

dws_jobtap_la_SOURCES = \
	dws-jobtap.c

dws_jobtap_la_LDFLAGS = \
	$(AM_LDFLAGS) \
	-module \
	-avoid-version

dws_jobtap_la_LIBADD= \
	$(FLUX_CORE_LIBS) \
	$(JANSSON_LIBS)

cray_pals_port_distributor_la_SOURCES = \
	cray_pals_port_distributor.c

cray_pals_port_distributor_la_LDFLAGS = \
	$(AM_LDFLAGS) \
	-module \
	-avoid-version

cray_pals_port_distributor_la_LIBADD= \
	$(FLUX_CORE_LIBS) \
	$(SODIUM_LIBS) \
	$(FLUX_HOSTLIST_LIBS) \
	$(JANSSON_LIBS)
