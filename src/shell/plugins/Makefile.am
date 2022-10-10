AM_CFLAGS = \
	$(WARNING_CFLAGS) \
	$(CODE_COVERAGE_CFLAGS) \
    $(FLUX_CORE_CFLAGS)

AM_LDFLAGS = \
	$(CODE_COVERAGE_LIBS)

shell_plugindir = \
    $(fluxlibdir)/shell/plugins/coral2/

shell_plugin_LTLIBRARIES = cray_pals.la

cray_pals_la_SOURCES = cray_pals.c
cray_pals_la_CPPFLAGS = $(AM_CPPFLAGS)
cray_pals_la_LIBADD = \
	$(FLUX_CORE_LIBS) \
	$(FLUX_HOSTLIST_LIBS) \
	$(JANSSON_LIBS)
cray_pals_la_LDFLAGS = \
	$(AM_LDFLAGS) \
	$(fluxplugin_ldflags) -module

