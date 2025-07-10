AM_CFLAGS = \
	$(WARNING_CFLAGS) \
	$(CODE_COVERAGE_CFLAGS)

AM_LDFLAGS = \
	$(CODE_COVERAGE_LIBS)

AM_CPPFLAGS = \
	-I$(top_srcdir) \
	-I$(top_srcdir)/src/common/libccan \
	$(CODE_COVERAGE_CPPFLAGS)

noinst_LTLIBRARIES = libutil.la

libutil_la_SOURCES = \
	monotime.h \
	monotime.c \
	errprintf.h \
	errprintf.c \
	eventlog.h \
	eventlog.c \
	idf58.h
