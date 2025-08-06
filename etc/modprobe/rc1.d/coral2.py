#############################################################
# Copyright 2025 Lawrence Livermore National Security, LLC
# (c.f. AUTHORS, NOTICE.LLNS, COPYING)
#
# This file is part of the Flux resource manager framework.
# For details, see https://github.com/flux-framework.
#
# SPDX-License-Identifier: LGPL-3.0
##############################################################

from flux.modprobe import task

# These jobtaps should be loaded in all Flux instances on coral2 systems.
# Skip loading (silently) if already loaded (e.g. by configuration).
@task(
    "coral2-jobtaps-all",
    ranks="0",
    after=["job-manager"],
    requires=["job-manager"],
)
def coral2_jobtaps_all(context):
    for mod in ["cray-pmi-bootstrap.so"]:
        try:
            context.rpc("job-manager.jobtap", {"load": mod}).get()
        except FileExistsError:
            pass
