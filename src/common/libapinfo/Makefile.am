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
