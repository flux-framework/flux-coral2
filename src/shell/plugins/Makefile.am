AM_CFLAGS = \
	$(WARNING_CFLAGS) \
	$(CODE_COVERAGE_CFLAGS)

AM_LDFLAGS = \
	$(CODE_COVERAGE_LIBS)

AM_CPPFLAGS = \
	-I$(top_srcdir) \
	$(FLUX_CORE_CFLAGS) \
	$(FLUX_HOSTLIST_CFLAGS) \
	$(FLUX_TASKMAP_CFLAGS) \
	$(FLUX_IDSET_CFLAGS) \
	$(JANSSON_CFLAGS)

shell_plugindir = \
	$(fluxlibdir)/shell/plugins

shell_plugin_LTLIBRARIES = \
	cray_pals.la \
	dws_environment.la

cray_pals_la_SOURCES = cray_pals.c
cray_pals_la_CPPFLAGS = $(AM_CPPFLAGS)
cray_pals_la_LIBADD = \
	$(top_builddir)/src/common/libapinfo/libapinfo.la \
	$(top_builddir)/src/common/libutil/libutil.la \
	$(FLUX_CORE_LIBS) \
	$(FLUX_HOSTLIST_LIBS) \
	$(FLUX_TASKMAP_LIBS) \
	$(FLUX_IDSET_LIBS) \
	$(JANSSON_LIBS)
cray_pals_la_LDFLAGS = \
	$(AM_LDFLAGS) \
	$(fluxplugin_ldflags) -module

dws_environment_la_SOURCES = dws_environment.c
dws_environment_la_CPPFLAGS = $(AM_CPPFLAGS)
dws_environment_la_LIBADD = \
	$(top_builddir)/src/common/libutil/libutil.la \
	$(FLUX_CORE_LIBS) \
	$(FLUX_HOSTLIST_LIBS) \
	$(JANSSON_LIBS)
dws_environment_la_LDFLAGS = \
	$(AM_LDFLAGS) \
	$(fluxplugin_ldflags) -module
