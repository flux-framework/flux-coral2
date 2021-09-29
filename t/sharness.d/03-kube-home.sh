# Kubernetes also falls victim to sharness's changing of HOME. Leverage the
# REAL_HOME set in 01-setup.sh to set KUBECONFIG

export KUBECONFIG=${REAL_HOME}/.kube/config
