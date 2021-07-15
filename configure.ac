#                                               -*- Autoconf -*-
# Process this file with autoconf to produce a configure script.

AC_PREREQ([2.63])
AC_INIT([flux-coral2],
        m4_esyscmd([git describe --always | awk '/.*/ {sub(/^v/, ""); printf "%s",$1; exit}']))
AC_CONFIG_AUX_DIR([config])
AC_CONFIG_MACRO_DIR([config])
AC_CONFIG_SRCDIR([NEWS])

AM_INIT_AUTOMAKE([subdir-objects tar-ustar filename-length-max=256])
AM_SILENT_RULES([yes])
AM_CONFIG_HEADER([config.h])
AM_MAINTAINER_MODE([enable])

#LT_PREREQ([2.4.2])
LT_INIT([dlopen])

AC_PREFIX_PROGRAM([flux])

# Checks for programs.
AC_DEFINE([_GNU_SOURCE], 1,
          [Define _GNU_SOURCE so that we get all necessary prototypes])
AC_PROG_CC_C99
AC_PROG_LN_S
AC_PROG_MAKE_SET
AM_PROG_CC_C_O
AX_CODE_COVERAGE

if test "$GCC" = yes; then
  WARNING_CFLAGS="-Wall -Werror -Werror=missing-field-initializers -Wno-error=deprecated-declarations"
  AC_SUBST([WARNING_CFLAGS])
fi

# Checks for libraries.
PKG_PROG_PKG_CONFIG
AC_CHECK_LIB([dl], [dlerror],
             [AC_SUBST([DL_LIBS], ["-ldl"])
              AC_DEFINE([HAVE_LIBDL], [1],
                        [Define if you have libdl])],
             [AC_MSG_ERROR([Please install dl])])
AX_VALGRIND_H

AX_FLUX_CORE

#  Set PYTHON_VERSION to FLUX_PYTHON_VERSION here
PYTHON_VERSION=${PYTHON_VERSION:-$FLUX_PYTHON_VERSION}
AX_PYTHON_DEVEL([>='3.6'])

AM_PATH_PYTHON([$ac_python_version])
if test "X$PYTHON" = "X"; then
  AC_MSG_ERROR([could not find python])
fi

# Flag for PYTHON_LDFLAGS workaround below.
if test -n "$PYTHON_LDFLAGS"; then
  ac_python_ldflags_set_by_user=true
fi

AC_ARG_ENABLE([pylint],
  [AS_HELP_STRING([--enable-pylint],
    [Enable pylint checks of python bindings])],,
  [enable_pylint="no"]
)
AS_IF([test "x$enable_pylint" = "xyes"], [
  AC_CHECK_PROG(PYLINT,[pylint],[pylint])
  AS_IF([test "x$PYLINT" != "xpylint"], [AC_MSG_ERROR([No pylint found in PATH])])
  AM_CHECK_PYMOD(pylint,
                   [StrictVersion(pylint.__version__) >= StrictVersion('1.8.4')],
                   ,
                   [AC_MSG_ERROR([could not find python module pylint, version 1.8.4+ required])]
                 )
])
AM_CONDITIONAL([ENABLE_PYLINT], [test "x$PYLINT" = "xpylint"])
AM_CHECK_PYMOD(kubernetes,
                  [StrictVersion(kubernetes.__version__) >= StrictVersion('12.0.0')],
                  ,
                  [AC_MSG_ERROR([could not find python module kubernetes, version 12.0.0+ required])]
                )

# Checks for header files.
AC_CHECK_HEADERS([\
  inttypes.h \
  limits.h \
  stdint.h \
  stdlib.h \
  string.h \
  sys/time.h \
  unistd.h \
])

# Checks for typedefs, structures, and compiler characteristics.
AC_HEADER_STDBOOL # in newer ac version:  AC_CHECK_HEADER_STDBOOL
AC_C_INLINE
AC_TYPE_INT64_T
AC_TYPE_SIZE_T
AC_TYPE_UINT32_T
AC_TYPE_UINT64_T

# Checks for library functions.
AC_FUNC_MALLOC
AC_CHECK_FUNCS([gettimeofday localtime_r memset strchr strdup strerror strstr strtol strtoul])

##
# Project directories
##
AS_VAR_SET(fluxcmddir, $libexecdir/flux/cmd)
AC_SUBST(fluxcmddir)

AS_VAR_SET(fluxlibdir, $libdir/flux)
AC_SUBST(fluxlibdir)

AS_VAR_SET(fluxmoddir, $libdir/flux/modules)
AC_SUBST(fluxmoddir)

AS_VAR_SET(fluxrc1dir, $sysconfdir/flux/rc1.d)
AC_SUBST(fluxrc1dir)

AS_VAR_SET(fluxrc3dir, $sysconfdir/flux/rc3.d)
AC_SUBST(fluxrc3dir)

AS_VAR_SET(fluxrc1dir, $sysconfdir/flux/rc1.d)
AC_SUBST(fluxrc1dir)

AS_VAR_SET(fluxrc3dir, $sysconfdir/flux/rc3.d)
AC_SUBST(fluxrc3dir)

AS_VAR_SET(fluxcoral2pydir, $pyexecdir/fluxcoral2)
AC_SUBST(fluxcoral2pydir)

# Target of PYTHONPATH set by flux(1) cmddriver, so flux(1)
# doesn't inadvertently insert system python paths (or any
# other python path for that matter) first in PYTHONPATH.
#
AS_VAR_SET(fluxcoral2pylinkdir, $fluxlibdir/python$PYTHON_VERSION)
AC_SUBST(fluxcoral2pylinkdir)

##
# Macros to avoid repetition in Makefiles.am's
##
fluxmod_ldflags="-Wl,--no-undefined -avoid-version -export-symbols-regex '^mod_(main|name|service)\$\$' --disable-static -shared -export-dynamic"
AC_SUBST(fluxmod_ldflags)

fluxplugin_ldflags="-avoid-version -export-symbols-regex '^flux_plugin_init\$\$' --disable-static -shared -export-dynamic"
AC_SUBST(fluxplugin_ldflags)

fluxlib_ldflags="-shared -export-dynamic --disable-static -Wl,--no-undefined"
AC_SUBST(fluxlib_ldflags)

AC_CONFIG_FILES([Makefile
  src/Makefile
  src/job-manager/Makefile
  src/job-manager/plugins/Makefile
  src/shell/Makefile
  src/shell/plugins/Makefile
  t/Makefile])
AC_OUTPUT

echo "
  $PACKAGE_NAME version $PACKAGE_VERSION
  Prefix...........: $prefix
  Debug Build......: $debug
  C Compiler.......: $CC
  CFLAGS...........: $CFLAGS
  FLUX.............: $FLUX
  FLUX_VERSION.....: $($FLUX version | sed -n 's/libflux-core:\t*//p')
  FLUX_CORE_CFLAGS.: $FLUX_CORE_CFLAGS
  FLUX_CORE_LIBS...: $FLUX_CORE_LIBS
  LIBFLUX_VERSION..: $LIBFLUX_VERSION
  FLUX_PREFIX......: $FLUX_PREFIX
  LDFLAGS..........: $LDFLAGS
  LIBS.............: $LIBS
  Linker...........: $LD
"
