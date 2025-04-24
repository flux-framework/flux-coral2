###############################################################
# Copyright 2022 Lawrence Livermore National Security, LLC
# (c.f. AUTHORS, NOTICE.LLNS, COPYING)
#
# This file is part of the Flux resource manager framework.
# For details, see https://github.com/flux-framework.
#
# SPDX-License-Identifier: LGPL-3.0
###############################################################

author = 'This page is maintained by the Flux community.'

# Add man page entries with the following information:
# - Relative file path (without .rst extension)
# - Man page name
# - Man page description
# - Author (use [author])
# - Manual section
#
# Note: the relative order of commands in this list affects the order
# in which commands appear within a section in the output of flux help.
# Therefore, keep these commands in relative order of importance.
#
man_pages = [
	(
        "man1/flux-shell-cray-pals",
        "flux-shell-cray-pals",
        "flux-coral2 commands",
        [author],
        1,
    ),
    (
        "man1/flux-rabbitmapping",
        "flux-rabbitmapping",
        "flux-coral2 commands",
        [author],
        1,
    ),
]
