# Kubernetes also falls victim to sharness's changing of HOME. Leverage the
# REAL_HOME set in 01-setup.sh to set KUBECONFIG

export KUBECONFIG=${REAL_HOME}/.kube/config

#  Set DWS_K8S or NO_DWS_K8S prereq
if type "kubectl" > /dev/null \
   && kubectl get crd 2> /dev/null | grep -q dws.cray.hpe.com; then
    test_set_prereq DWS_K8S
else
    test_set_prereq NO_DWS_K8S
fi
