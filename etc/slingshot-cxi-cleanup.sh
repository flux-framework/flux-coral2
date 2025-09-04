#!/bin/sh

CXI_ENABLE=$(flux config get --type=boolean --default=false cray-slingshot.cxi-enable)
test "$CXI_ENABLE" = "true" || exit 0

# Retry the epilog action with a longer timeout in housekeeping.
flux slingshot epilog --retry-busy=5m
