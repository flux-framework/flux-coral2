#!/bin/bash
#-------------------------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See https://go.microsoft.com/fwlink/?linkid=2090316 for license information.
#-------------------------------------------------------------------------------------------------------------
#
# Docs: https://github.com/microsoft/vscode-dev-containers/blob/main/script-library/docs/kubectl-helm.md

# Install the kubectl, verify checksum
if [[ -z "$1" ]]; then
    KUBECTL_VERSION="latest"
else
    KUBECTL_VERSION=$1
fi

ARCHITECTURE="$(uname -m)"
case $ARCHITECTURE in
    armv*) ARCHITECTURE="arm";;
    aarch64) ARCHITECTURE="arm64";;
    x86_64) ARCHITECTURE="amd64";;
esac

echo "Downloading kubectl..."
if [ "${KUBECTL_VERSION}" = "latest" ] || [ "${KUBECTL_VERSION}" = "lts" ] || [ "${KUBECTL_VERSION}" = "current" ] || [ "${KUBECTL_VERSION}" = "stable" ]; then
    KUBECTL_VERSION="$(curl -sSL https://dl.k8s.io/release/stable.txt)"
fi
if [ "${KUBECTL_VERSION::1}" != 'v' ]; then
    KUBECTL_VERSION="v${KUBECTL_VERSION}"
fi
curl -sSL -o /usr/local/bin/kubectl "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${ARCHITECTURE}/kubectl"
set -x
chmod 0755 /usr/local/bin/kubectl
KUBECTL_SHA256="$(curl -sSL "https://dl.k8s.io/${KUBECTL_VERSION}/bin/linux/${ARCHITECTURE}/kubectl.sha256")"
(echo "${KUBECTL_SHA256} */usr/local/bin/kubectl" | sha256sum -c -)
