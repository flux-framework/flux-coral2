AM_CFLAGS = \
	$(WARNING_CFLAGS) \
	$(CODE_COVERAGE_CFLAGS)

AM_LDFLAGS = \
	$(CODE_COVERAGE_LIBS)

AM_CPPFLAGS = \
	-I$(top_srcdir) \
	$(CODE_COVERAGE_CPPFLAGS)

noinst_LTLIBRARIES = \
	libapinfo.la

libapinfo_la_SOURCES = \
	apinfo.c \
	apinfo.h \
	apinfo1.c \
	apinfo1.h \
	apimpl.h

TESTS =

if HAVE_PALS
TESTS += test_pals.t
endif

test_ldadd = \
	$(builddir)/libapinfo.la \
	$(top_builddir)/src/common/libutil/libutil.la \
	$(top_builddir)/src/common/libtap/libtap.la \
	$(FLUX_CORE_LIBS) \
	$(FLUX_HOSTLIST_LIBS) \
	$(FLUX_TASKMAP_LIBS) \
	$(FLUX_IDSET_LIBS)

test_cppflags = \
	$(AM_CPPFLAGS) \
	-I$(top_srcdir)/src/common/libtap \
	$(FLUX_CORE_CFLAGS) \
	$(FLUX_HOSTLIST_CFLAGS) \
	$(FLUX_TASKMAP_CFLAGS) \
	$(FLUX_IDSET_CFLAGS)

check_PROGRAMS = \
	$(TESTS)

TEST_EXTENSIONS = .t
T_LOG_DRIVER = env AM_TAP_AWK='$(AWK)' $(SHELL) \
       $(top_srcdir)/config/tap-driver.sh

test_pals_t_SOURCES = test/pals.c
test_pals_t_CPPFLAGS = \
	$(PALS_CFLAGS) \
	$(test_cppflags)
test_pals_t_LDADD = \
	$(PALS_LIBS) \
	$(test_ldadd)
