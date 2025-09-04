#!/bin/sh

CXI_ENABLE=$(flux config get --type=boolean --default=false cray-slingshot.cxi-enable)
test "$CXI_ENABLE" = "true" || exit 0

# Fetch the cray-slingshot event from the job eventlog and
# for each Cassini NIC, destroy CXI services that match the
# job's VNI reservation.
#
# Retry any busy CXI services for a short time, but leave
# it to housekeeping to try again with a longer timeout.

flux slingshot epilog --retry-busy=5s
