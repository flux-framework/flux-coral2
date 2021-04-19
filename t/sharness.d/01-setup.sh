#
#  Export some extra variables to test scripts specific to flux-core
#   testsuite

#
#  Unset variables important to Flux
#
unset FLUX_CONFIG
unset FLUX_MODULE_PATH

#
#  FLUX_BUILD_DIR and FLUX_SOURCE_DIR are set to build and source paths
#  (based on current directory)
#
if test -z "$FLUX_BUILD_DIR"; then
    if test -z "${builddir}"; then
        FLUX_BUILD_DIR="$(cd .. && pwd)"
    else
        FLUX_BUILD_DIR="$(cd ${builddir}/.. && pwd))"
    fi
    export FLUX_BUILD_DIR
fi
if test -z "$FLUX_SOURCE_DIR"; then
    if test -z "${srcdir}"; then
        FLUX_SOURCE_DIR="$(cd ${SHARNESS_TEST_SRCDIR}/.. && pwd)"
    else
        FLUX_SOURCE_DIR="$(cd ${srcdir}/.. && pwd)"
    fi
    export FLUX_SOURCE_DIR
fi

#  Python's site module won't be able to determine the correct path
#   for site.USER_SITE because sharness reassigns HOME to a per-test
#   trash directory. Set up a REAL_HOME here from the passwd database
#   and append the real USER_SITE to PYTHONPATH so Python can find
#   user installed modules (e.g. those installed with pip install --user)
#
REAL_HOME=$(getent passwd $USER | cut -d: -f6)
USER_SITE=$(HOME=$REAL_HOME flux python -c 'import site; print(site.USER_SITE)')
PYTHONPATH=${PYTHONPATH:+${PYTHONPATH}:}${USER_SITE}
export REAL_HOME PYTHONPATH

# vi: ts=4 sw=4 expandtab
