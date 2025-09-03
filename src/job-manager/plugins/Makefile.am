AM_CFLAGS = \
	$(WARNING_CFLAGS) \
	$(CODE_COVERAGE_CFLAGS)

AM_LDFLAGS = \
	$(CODE_COVERAGE_LIBS)

AM_CPPFLAGS = \
	-I$(top_srcdir) \
	-I$(top_srcdir)/src/common/libccan \
	$(FLUX_CORE_CFLAGS) \
	$(FLUX_HOSTLIST_CFLAGS) \
	$(FLUX_IDSET_CFLAGS) \
	$(SODIUM_CFLAGS) \
	$(JANSSON_CFLAGS)

jobtapdir = \
	$(fluxlibdir)/job-manager/plugins/

jobtap_LTLIBRARIES = \
	dws-jobtap.la \
	cray-slingshot.la \
	cray-pmi-bootstrap.la

dws_jobtap_la_SOURCES = \
	dws-jobtap.c

dws_jobtap_la_LDFLAGS = \
	$(AM_LDFLAGS) \
	$(fluxplugin_ldflags) -module

dws_jobtap_la_LIBADD= \
	$(FLUX_CORE_LIBS) \
	$(JANSSON_LIBS)

cray_slingshot_la_SOURCES = \
	cray-slingshot.c \
	vnipool.h \
	vnipool.c

cray_slingshot_la_LDFLAGS = \
	$(AM_LDFLAGS) \
	$(fluxplugin_ldflags) -module

cray_slingshot_la_LIBADD= \
	$(top_builddir)/src/common/libutil/libutil.la \
	$(top_builddir)/src/common/libccan/libccan.la \
	$(FLUX_CORE_LIBS) \
	$(JANSSON_LIBS) \
	$(FLUX_IDSET_LIBS)

cray_pmi_bootstrap_la_SOURCES = \
	cray-pmi-bootstrap.c

cray_pmi_bootstrap_la_LDFLAGS = \
	$(AM_LDFLAGS) \
	$(fluxplugin_ldflags) -module

cray_pmi_bootstrap_la_LIBADD= \
	$(FLUX_CORE_LIBS) \
	$(SODIUM_LIBS) \
	$(FLUX_HOSTLIST_LIBS) \
	$(JANSSON_LIBS)
