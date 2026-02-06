AM_CFLAGS = \
	$(WARNING_CFLAGS) \
	$(CODE_COVERAGE_CFLAGS)

AM_LDFLAGS = \
	$(CODE_COVERAGE_LIBS)

AM_CPPFLAGS = \
	$(CODE_COVERAGE_CPPFLAGS) \
	-I$(top_srcdir) \
	-I$(top_srcdir)/src/common/libccan \
	$(FLUX_CORE_CFLAGS) \
	$(FLUX_HOSTLIST_CFLAGS) \
	$(FLUX_IDSET_CFLAGS) \
	$(FLUX_OPTPARSE_CFLAGS) \
	$(JANSSON_CFLAGS)

fluxcmd_ldadd = \
	$(FLUX_CORE_LIBS) \
	$(FLUX_HOSTLIST_LIBS) \
	$(FLUX_IDSET_LIBS) \
	$(FLUX_OPTPARSE_LIBS) \
	$(JANSSON_LIBS)


dist_fluxcmd_SCRIPTS = \
	flux-dws2jgf.py \
	flux-rabbitmapping.py \
	flux-hop.py \
	flux-getrabbit.py

fluxcmd_PROGRAMS =

fluxcmd_PROGRAMS += flux-slingshot

flux_slingshot_CPPFLAGS = \
        $(AM_CPPFLAGS) \
        $(CXI_CFLAGS)

flux_slingshot_LDADD = \
        $(top_builddir)/src/common/libccan/libccan.la \
        $(top_builddir)/src/common/libutil/libutil.la \
        $(fluxcmd_ldadd) \
        $(CXI_LIBS)
