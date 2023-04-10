AM_CFLAGS = \
	$(WARNING_CFLAGS) \
	$(CODE_COVERAGE_CFLAGS) \
    $(FLUX_CORE_CFLAGS)

AM_LDFLAGS = \
	$(CODE_COVERAGE_LIBS)

shell_plugindir = \
    $(fluxlibdir)/shell/plugins

shell_plugin_LTLIBRARIES = \
	cray_pals.la \
	dws_environment.la

cray_pals_la_SOURCES = cray_pals.c \
	eventlog_helpers.c \
	eventlog_helpers.h
cray_pals_la_CPPFLAGS = $(AM_CPPFLAGS)
cray_pals_la_LIBADD = \
	$(FLUX_CORE_LIBS) \
	$(FLUX_HOSTLIST_LIBS) \
	$(JANSSON_LIBS)
cray_pals_la_LDFLAGS = \
	$(AM_LDFLAGS) \
	$(fluxplugin_ldflags) -module

dws_environment_la_SOURCES = dws_environment.c \
	eventlog_helpers.c \
	eventlog_helpers.h
dws_environment_la_CPPFLAGS = $(AM_CPPFLAGS)
dws_environment_la_LIBADD = \
	$(FLUX_CORE_LIBS) \
	$(JANSSON_LIBS)
dws_environment_la_LDFLAGS = \
	$(AM_LDFLAGS) \
	$(fluxplugin_ldflags) -module
