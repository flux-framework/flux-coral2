#!/bin/bash

# stop the nnf-clientmount service.
# if the job's jobspec has a .attributes.system.dw entry, it uses
# rabbits and so the clientmount service should not be stopped until
# the mount has completed, which is indicated by the
# `dws_environment` event being posted to the job's eventlog.
# This script should run last because the `flux job wait-event` may
# take some time waiting, hence the 'z' prefix in the filename.

flux getrabbit || exit 0  # exit if not configured with rabbits

if flux job info ${FLUX_JOB_ID} jobspec | jq -e .attributes.system.dw > /dev/null ; then
    # the nnf-clientmount service should already be running. However, if
    # it isn't running, the job could hang while waiting
    # for the mounts. Just in case, issue a `systemctl start`.
    systemctl start nnf-clientmount
    TIMEOUT=$(flux config get --default=1800 rabbit.prolog_timeout)
    flux job wait-event -t${TIMEOUT} ${FLUX_JOB_ID} dws_environment || \
        flux job raise -t prolog-timeout ${FLUX_JOB_ID} "dws_environment timeout"
    systemctl stop nnf-clientmount
else
    systemctl stop nnf-clientmount
fi
