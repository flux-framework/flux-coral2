.NOTPARALLEL:

SUBDIRS = . src doc etc t

EXTRA_DIST = \
	config/tap-driver.sh \
	config/tap-driver.py \
	NOTICE.LLNS \
	README.md \
	NEWS.md

ACLOCAL_AMFLAGS = -I config

# coverage

CODE_COVERAGE_IGNORE_PATTERN = \
	"$(abs_top_builddir)/t/*" \
	"*/test/*.c" \
	"*/tests/*.c" \
	"*/man3/*.c" \
	"*/libtap/*" \
	"*/libev/*" \
	"/usr/include/*" \
	"/usr/lib*"

CODE_COVERAGE_LCOV_OPTIONS =
@CODE_COVERAGE_RULES@

# Many of flux-core's tests live down in subdirectories with
# the core that that it is testing.  However, some of those tests
# also have dependencies on other subdirectories higher up the
# source tree.  With the recursive Makefiles approach, there is
# no easy way to express that build dependency in a way that will
# actually trigger the build of the that dependency.  The following
# check-local rule, in conjunction with putting "." _first_ in this
# file's SUBDIRS, ensures that "all" is built before any of the
# recursive checks.
check-local: all
if ENABLE_PYLINT
	$(top_srcdir)/scripts/pylint
endif

check-prep: all
	cd src && $(MAKE) check
	cd doc && $(MAKE) check
	cd t && $(MAKE) check-prep


dist_fluxrc1_SCRIPTS = \
	etc/01-coral2-rc

export DEB_BUILD_OPTIONS ?= nocheck terse
deb: debian scripts/debbuild.sh
	@$(top_srcdir)/scripts/debbuild.sh $(abs_top_srcdir)

clean-local:
	@rm -rf debbuild
