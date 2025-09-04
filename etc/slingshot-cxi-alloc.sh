#!/bin/sh

CXI_ENABLE=$(flux config get --type=boolean --default=false cray-slingshot.cxi-enable)
test "$CXI_ENABLE" = "true" || exit 0

# Fetch cray-slingshot event from job eventlog and
# for each Cassini NIC, allocate CXI services for the
# job's VNI reservation.

flux slingshot prolog
