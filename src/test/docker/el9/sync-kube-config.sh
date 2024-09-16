#!/bin/bash -i
#-------------------------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See https://go.microsoft.com/fwlink/?linkid=2090316 for license information.
#-------------------------------------------------------------------------------------------------------------
#
# Docs: https://github.com/microsoft/vscode-dev-containers/blob/main/script-library/docs/kubectl-helm.md

# Copies localhost's ~/.kube/config file into the container and swap out localhost
# for host.docker.internal on the first shell start to keep them in sync.
if [ -d "/usr/local/share/kube-localhost" ] && [ ! -f "$HOME/.kube/.copied" ]; then
    echo "Syncing Kube config"
    mkdir -p $HOME/.kube
    sudo cp -r /usr/local/share/kube-localhost/* $HOME/.kube
    sudo chown -R $(id -u) $HOME/.kube
    sed -i -e "s/localhost/host.docker.internal/g" $HOME/.kube/config
    sed -i -e "s/127.0.0.1/host.docker.internal/g" $HOME/.kube/config

    touch $HOME/.kube/.copied
fi
