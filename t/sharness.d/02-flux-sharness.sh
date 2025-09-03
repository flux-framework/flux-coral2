
#
#  project-local sharness code for Flux
#

#
#  Extra functions for Flux testsuite
#
run_timeout() {
    if test -z "$LD_PRELOAD" ; then
        "${PYTHON:-python3}" "${SHARNESS_TEST_SRCDIR}/scripts/run_timeout.py" "$@"
    else
        (
            TIMEOUT_PRELOAD="$LD_PRELOAD"
            unset -v LD_PRELOAD
            exec "${PYTHON:-python3}" -S "${SHARNESS_TEST_SRCDIR}/scripts/run_timeout.py" -e LD_PRELOAD="$TIMEOUT_PRELOAD" "$@"
        )
    fi
}

#
#  Echo on stdout a reasonable size for a large test session,
#   controllable test-wide via env vars FLUX_TEST_SIZE_MIN and
#   FLUX_TEST_SIZE_MAX.
#
test_size_large() {
    min=${FLUX_TEST_SIZE_MIN:-4}
    max=${FLUX_TEST_SIZE_MAX:-17}
    size=$(($(nproc)+1))
    test ${size} -lt ${min} && size=$min
    test ${size} -gt ${max} && size=$max
    echo ${size}
}

#
#  Like test_must_fail(), but additionally allow process to be
#   terminated by SIGKILL or SIGTERM
#
test_must_fail_or_be_terminated() {
    "$@"
    exit_code=$?
    # Allow death by SIGTERM or SIGKILL
    if test $exit_code = 143 -o $exit_code = 137; then
        return 0
    elif test $exit_code = 0; then
        echo >&2 "test_must_fail_or_be_terminated: command succeeded: $*"
        return 1
    elif test $exit_code -ge 129 -a $exit_code -le 192; then
        echo >&2 "test_must_fail_or_be_terminated: died by signal $(($exit_code-128)): $*"
        return 1
    elif test $exit_code = 127; then
        echo >&2 "test_must_fail_or_be_terminated: command not found: $*"
        return 1
    fi
    return 0
}

#
#  Tests using test_under_flux() and which load their own modules should
#   ensure those modules are unloaded at the end of the test for proper
#   cleanup and test coverage (also as a general principle, module unload
#   should be something explicitly tested).
#
#  The functions below ensure that every module loaded at "test_done" time
#   when test_under_flux() was used was also loaded before test_under_flux
#   was called.
#
flux_module_list() {
    flux module list | awk '!/^Module/{print $1}' | sort
}

check_module_list() {
    flux_module_list > module-list.final
    while read module; do
       grep "^$module$" module-list.initial >/dev/null 2>&1 \
            || bad="${bad}${bad:+ }$module"
    done < module-list.final
    if test -n "$bad"; then
        test -n "$logfile" \
            && say_color error >&3 \
                 "Error: manually loaded module(s) not unloaded: $bad"
        # This function is run under test_eval_ so redirect
        #  error message to &5 (saved stdout) so text doesn't disappear:
        error >&5 2>&1 "manually loaded module(s) not unloaded: $bad"
    fi
}

#
#  Reinvoke a test file under a flux instance
#
#  Usage: test_under_flux <size>
#
test_under_flux() {
    size=${1:-1}
    personality=${2:-full}
    log_file="$TEST_NAME.broker.log"
    if test -n "$TEST_UNDER_FLUX_ACTIVE" ; then
        test "$debug" = "t" || cleanup rm "${SHARNESS_TEST_DIRECTORY:-..}/$log_file"
        flux_module_list > module-list.initial
        cleanup check_module_list
        return
    fi
    if test "$verbose" = "t" -o -n "$FLUX_TESTS_DEBUG" ; then
        flags="${flags} --verbose"
    fi
    if test "$debug" = "t" -o -n "$FLUX_TESTS_DEBUG" ; then
        flags="${flags} --debug"
        export FLUX_PYCLI_LOGLEVEL=10
    fi
    if test "$chain_lint" = "t"; then
        flags="${flags} --chain-lint"
    fi
    if test -n "$logfile" -o -n "$FLUX_TESTS_LOGFILE" ; then
        flags="${flags} --logfile"
    fi
    if test -n "$SHARNESS_TEST_DIRECTORY"; then
        cd $SHARNESS_TEST_DIRECTORY
    fi

    if test "$personality" = "minimal"; then
        RC1_PATH=""
        RC3_PATH=""
    elif test "$personality" != "full"; then
        RC1_PATH=$FLUX_SOURCE_DIR/t/rc/rc1-$personality
        RC3_PATH=$FLUX_SOURCE_DIR/t/rc/rc3-$personality
        test -x $RC1_PATH || error "cannot execute $RC1_PATH"
        test -x $RC3_PATH || error "cannot execute $RC3_PATH"
    else
        unset RC1_PATH
        unset RC3_PATH
    fi
    if test -n "$FLUX_TEST_VALGRIND" ; then
        VALGRIND_SUPPRESSIONS=${SHARNESS_TEST_SRCDIR}/valgrind/valgrind.supp
        valgrind="--wrap=libtool,e"
        valgrind="$valgrind,valgrind,--leak-check=full"
        valgrind="$valgrind,--trace-children=no,--child-silent-after-fork=yes"
        valgrind="$valgrind,--leak-resolution=med,--error-exitcode=1"
        valgrind="$valgrind,--suppressions=${VALGRIND_SUPPRESSIONS}"
    fi
    # Extend timeouts when running under AddressSanitizer
    if test_have_prereq ASAN; then
        # Set log_path for ASan o/w errors from broker may be lost
        ASAN_OPTIONS=${ASAN_OPTIONS}:log_path=${TEST_NAME}.asan
    fi
    logopts="-o -Slog-filename=${log_file},-Slog-forward-level=7"
    TEST_UNDER_FLUX_ACTIVE=t \
    TERM=${ORIGINAL_TERM} \
      exec flux start --test-size=${size} \
                      ${RC1_PATH+-o -Sbroker.rc1_path=${RC1_PATH}} \
                      ${RC3_PATH+-o -Sbroker.rc3_path=${RC3_PATH}} \
                      ${logopts} \
                      ${valgrind} \
                     "sh $0 ${flags}"
}

mock_bootstrap_instance() {
    if test -z "${TEST_UNDER_FLUX_ACTIVE}"; then
        unset FLUX_URI
    fi
}

#
#  Execute arguments $2-N on rank or ranks specified in arg $1
#   using the flux-exec utility
#
test_on_rank() {
    test "$#" -ge 2 ||
        error "test_on_rank expects at least two parameters"
    test -n "$TEST_UNDER_FLUX_ACTIVE"  ||
        error "test_on_rank: test_under_flux not active ($TEST_UNDER_FLUX_ACTIVE)"

    ranks=$1; shift;
    flux exec --rank=${ranks} "$@"
}

#  Export a shorter name for this test
TEST_NAME=$SHARNESS_TEST_NAME
export TEST_NAME

#  Test requirements for testsuite
if ! command -v jq >/dev/null; then
    error "jq is required for the flux-coral2 testsuite"
fi
if ! run_timeout 10.0 lua -e 'require "posix"'; then
    error "failed to find lua posix module in path"
fi
jq=$(command -v jq)

#  Some tests in flux don't work with --chain-lint, add a prereq for
#   --no-chain-lint:
test "$chain_lint" = "t" || test_set_prereq NO_CHAIN_LINT

#  Set LONGTEST prereq
if test "$TEST_LONG" = "t" || test "$LONGTEST" = "t"; then
    test_set_prereq LONGTEST
fi

#  Set ASAN or NO_ASAN prereq
if flux version | grep -q +asan; then
    test_set_prereq ASAN
else
    test_set_prereq NO_ASAN
fi

# Sanitize PMI_* environment for all tests. This allows commands like
#  `flux broker` in tests to boot as singleton even when run under a
#  job of an existing RM.
for var in $(env | grep ^PMI); do unset ${var%%=*}; done
for var in $(env | grep ^SLURM); do unset ${var%%=*}; done

export FLUX_RC_USE_MODPROBE=t

# vi: ts=4 sw=4 expandtab
