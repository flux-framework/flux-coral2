# Kubernetes also falls victim to sharness's changing of HOME. Leverage the
# REAL_HOME set in 01-setup.sh to set KUBECONFIG

export KUBECONFIG=${REAL_HOME}/.kube/config

#  Set HPE_VM or NO_HPE_VM prereq
if type "kubectl" > /dev/null \
   && kubectl get crd 2> /dev/null | grep -q workflows; then
    test_set_prereq HPE_VM
else
    test_set_prereq NO_HPE_VM
fi
