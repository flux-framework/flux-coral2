#!/usr/bin/env python3

###############################################################
# Copyright 2026 Lawrence Livermore National Security, LLC
# (c.f. AUTHORS, NOTICE.LLNS, COPYING)
#
# This file is part of the Flux resource manager framework.
# For details, see https://github.com/flux-framework.
#
# SPDX-License-Identifier: LGPL-3.0
###############################################################

import copy
import unittest
import unittest.mock

import kubernetes as k8s
from kubernetes.client.rest import ApiException

from flux_k8s import crd

from pycotap import TAPTestRunner

ORIG_DWS_VERSIONS = copy.deepcopy(crd.DWS_API_VERSIONS)
ORIG_NNF_VERSIONS = copy.deepcopy(crd.NNF_API_VERSIONS)


def reset_module():
    crd.DWS_API_VERSIONS = copy.deepcopy(ORIG_DWS_VERSIONS)
    crd.NNF_API_VERSIONS = copy.deepcopy(ORIG_NNF_VERSIONS)
    for dws_crd in crd._DWS_CRDS:
        dws_crd.version = crd.DWS_API_VERSIONS[0]
    for nnf_crd in crd._NNF_CRDS:
        nnf_crd.version = crd.NNF_API_VERSIONS[0]


class CRDMockTests(unittest.TestCase):
    """Tests for the `flux_k8s.crd module that use mock objects."""

    def setUp(self):
        """Make sure the lists of versions is reverted to its original state."""
        reset_module()

    def test_failure(self):
        handle_mock = unittest.mock.Mock()
        handle_mock.conf_get.return_value = None
        k8s_mock = unittest.mock.Mock()
        k8s_mock.list_namespaced_custom_object.side_effect = ApiException("boom")
        with self.assertRaisesRegex(
            RuntimeError,
            "could not find suitable API " rf"version for {crd.DWS_GROUP} .*",
        ):
            crd.determine_api_versions(handle_mock, k8s_mock)

    def test_success(self):
        handle_mock = unittest.mock.Mock()
        handle_mock.conf_get.return_value = None
        k8s_mock = unittest.mock.Mock()
        crd.WORKFLOW_CRD.version = "foobar"
        crd.DATAMOVEMENT_CRD.version = "foobarbaz"
        crd.determine_api_versions(handle_mock, k8s_mock)
        self.assertEqual(ORIG_DWS_VERSIONS[0], crd.WORKFLOW_CRD.version)
        self.assertEqual(ORIG_DWS_VERSIONS[0], crd.SYSTEMSTATUS_CRD.version)
        self.assertEqual(ORIG_NNF_VERSIONS[0], crd.DATAMOVEMENT_CRD.version)

    def test_api_version_in_config(self):
        handle_mock = unittest.mock.Mock()
        new_api_ver = "v1betafoo"
        handle_mock.conf_get.return_value = new_api_ver
        crd.determine_api_versions(handle_mock, unittest.mock.Mock())
        self.assertEqual(crd.DWS_API_VERSIONS[0], new_api_ver)
        self.assertEqual(crd.NNF_API_VERSIONS[0], new_api_ver)


class CRDTests(unittest.TestCase):
    """Tests for the `flux_k8s.crd module that use mock objects."""

    @classmethod
    def setUpClass(cls):
        reset_module()
        cls.skip_all = False
        try:
            cls.k8s_api = k8s.client.CustomObjectsApi(
                k8s.config.new_client_from_config(None)
            )
            cls.k8s_api.list_namespaced_custom_object(*crd.WORKFLOW_CRD)
        except Exception:
            cls.skip_all = True
            # could instead raise unittest.SkipTest() here but sharness complains

    def setUp(self):
        """Make sure the lists of versions is reverted to its original state."""
        reset_module()
        if self.skip_all:
            self.skipTest("no k8s")

    def test_success(self):
        handle_mock = unittest.mock.Mock()
        handle_mock.conf_get.return_value = None
        crd.determine_api_versions(handle_mock, self.k8s_api)
        self.assertEqual(ORIG_DWS_VERSIONS[0], crd.WORKFLOW_CRD.version)
        self.assertEqual(ORIG_DWS_VERSIONS[0], crd.SYSTEMSTATUS_CRD.version)
        self.assertEqual(ORIG_NNF_VERSIONS[0], crd.DATAMOVEMENT_CRD.version)

    def test_selection(self):
        handle_mock = unittest.mock.Mock()
        new_api_ver = "v1alphabad"
        handle_mock.conf_get.return_value = new_api_ver
        crd.determine_api_versions(handle_mock, self.k8s_api)
        self.assertEqual(ORIG_DWS_VERSIONS[0], crd.WORKFLOW_CRD.version)
        self.assertEqual(ORIG_DWS_VERSIONS[0], crd.SYSTEMSTATUS_CRD.version)
        self.assertEqual(ORIG_NNF_VERSIONS[0], crd.DATAMOVEMENT_CRD.version)

    def test_nnf_api_version_selection(self):
        handle_mock = unittest.mock.Mock()
        handle_mock.conf_get.return_value = None
        crd.NNF_API_VERSIONS = ["v1alphabad"]
        crd.NNF_API_VERSIONS.extend(ORIG_NNF_VERSIONS)
        crd.DATAMOVEMENT_CRD.version = "foobar"
        crd.determine_api_versions(handle_mock, self.k8s_api)
        self.assertEqual(ORIG_NNF_VERSIONS[0], crd.DATAMOVEMENT_CRD.version)

    def test_bad_dws_api_version(self):
        handle_mock = unittest.mock.Mock()
        handle_mock.conf_get.return_value = None
        crd.DWS_API_VERSIONS = ["v1alphabad"]
        with self.assertRaisesRegex(
            RuntimeError,
            "could not find suitable API " rf"version for {crd.DWS_GROUP} .*",
        ):
            crd.determine_api_versions(handle_mock, self.k8s_api)

    def test_bad_nnf_api_version(self):
        handle_mock = unittest.mock.Mock()
        handle_mock.conf_get.return_value = None
        crd.NNF_API_VERSIONS = ["v1alphabad"]
        with self.assertRaisesRegex(
            RuntimeError,
            "could not find suitable API " rf"version for {crd.NNF_GROUP} .*",
        ):
            crd.determine_api_versions(handle_mock, self.k8s_api)


unittest.main(testRunner=TAPTestRunner())
