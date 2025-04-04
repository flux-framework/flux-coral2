#!/usr/bin/env python3

###############################################################
# Copyright 2025 Lawrence Livermore National Security, LLC
# (c.f. AUTHORS, NOTICE.LLNS, COPYING)
#
# This file is part of the Flux resource manager framework.
# For details, see https://github.com/flux-framework.
#
# SPDX-License-Identifier: LGPL-3.0
###############################################################

import json
import unittest
import unittest.mock
from pathlib import Path

from flux.hostlist import Hostlist

from pycotap import TAPTestRunner
from flux_k8s import storage

JGFDIR = Path(__file__).resolve().parent.parent / "data" / "dws2jgf"


def _generate_fake_rabbit(compute_nodes, status):
    return {
        "status": {
            "access": {
                "computes": [{"name": name, "status": status} for name in compute_nodes]
            }
        }
    }


class StorageModuleTests(unittest.TestCase):
    def test_get_offline_nodes(self):
        compute_nodes = {f"compute{i}" for i in range(10)}
        rabbit = _generate_fake_rabbit(compute_nodes, storage._READY_STATUS)
        self.assertSetEqual(set(), storage._get_offline_nodes(rabbit))
        rabbit = _generate_fake_rabbit(compute_nodes, "Foobar")
        self.assertSetEqual(compute_nodes, storage._get_offline_nodes(rabbit))

    def test_get_status(self):
        for status in ("a", None, 5):
            rabbit = {"status": {"status": status}}
            not_rabbit = {}
            self.assertEqual(status, storage._get_status(rabbit, "foobar"))
            self.assertEqual("foobar", storage._get_status(not_rabbit, "foobar"))


class TestRabbitManager(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._old_RABBITS_TO_HOSTLISTS = storage._RABBITS_TO_HOSTLISTS
        cls._old_HOSTNAMES_TO_RABBITS = storage.HOSTNAMES_TO_RABBITS
        storage._RABBITS_TO_HOSTLISTS = {
            f"rabbit{i}": Hostlist(f"compute{j + 10*i}" for j in range(10))
            for i in range(4)
        }
        storage.HOSTNAMES_TO_RABBITS = {
            compute: rabbit
            for rabbit, hostlist in storage._RABBITS_TO_HOSTLISTS.items()
            for compute in hostlist
        }

    @classmethod
    def tearDownClass(cls):
        storage._RABBITS_TO_HOSTLISTS = cls._old_RABBITS_TO_HOSTLISTS
        storage.HOSTNAMES_TO_RABBITS = cls._old_HOSTNAMES_TO_RABBITS

    def test_nodes_not_recognized(self):
        mock_flux = unittest.mock.Mock()
        manager = storage.RabbitManager(mock_flux, None)
        manager.set_property({"foo", "bar"})
        mock_flux.rpc.assert_not_called()
        manager.remove_property({"foo", "bar"})
        mock_flux.rpc.assert_not_called()

    def test_set_remove_property(self):
        mock_flux = unittest.mock.Mock()
        manager = storage.RabbitManager(mock_flux, None)
        manager.set_property({"compute1"})
        mock_flux.rpc.assert_called_once()
        mock_flux.rpc.reset_mock()
        manager.remove_property({"compute1"})
        mock_flux.rpc.assert_called_once()


class TestFluxionRabbitManager(TestRabbitManager):
    @unittest.mock.patch("flux.kvs.get")
    def test_nodes_not_recognized(self, patched_kvs_get):
        with open(JGFDIR / "expected-compute-01.jgf", "r") as json_fd:
            patched_kvs_get.return_value = json.load(json_fd)
        mock_flux = unittest.mock.Mock()
        manager = storage.FluxionRabbitManager(mock_flux, None)
        manager.set_property({"foo", "bar"})
        mock_flux.rpc.assert_not_called()
        manager.remove_property({"foo", "bar"})
        mock_flux.rpc.assert_not_called()
        manager.set_property({"compute1"})
        mock_flux.rpc.assert_not_called()

    @unittest.mock.patch("flux.kvs.get")
    def test_set_remove_property(self, patched_kvs_get):
        with open(JGFDIR / "expected-compute-01.jgf", "r") as json_fd:
            patched_kvs_get.return_value = json.load(json_fd)
        mock_flux = unittest.mock.Mock()
        manager = storage.FluxionRabbitManager(mock_flux, None)
        manager.set_property({"compute-01"})
        mock_flux.rpc.assert_called_once()
        mock_flux.rpc.reset_mock()
        manager.remove_property({"compute-01"})
        mock_flux.rpc.assert_called_once()

    @unittest.mock.patch("flux.kvs.get")
    def test_mark_rabbit(self, patched_kvs_get):
        with open(JGFDIR / "expected-compute-01.jgf", "r") as json_fd:
            patched_kvs_get.return_value = json.load(json_fd)
        mock_flux = unittest.mock.Mock()
        manager = storage.FluxionRabbitManager(mock_flux, None)
        manager._mark_rabbit("Ready", "kind-worker2")
        mock_flux.rpc.assert_called()
        mock_flux.rpc.reset_mock()
        mock_flux.rpc.assert_not_called()
        manager._mark_rabbit("Down", "kind-worker2")
        mock_flux.rpc.assert_called()
        with self.assertRaises(KeyError):
            manager._mark_rabbit("Ready", "foobar")

    @unittest.mock.patch("flux.kvs.get")
    def test_drain_offline_nodes(self, patched_kvs_get):
        with open(JGFDIR / "expected-compute-01.jgf", "r") as json_fd:
            patched_kvs_get.return_value = json.load(json_fd)
        mock_flux = unittest.mock.Mock()
        manager = storage.FluxionRabbitManager(mock_flux, None)
        compute_nodes = {f"compute-0{i}" for i in range(3)}
        rabbit = _generate_fake_rabbit(compute_nodes, storage._READY_STATUS)
        manager._drain_offline_nodes(rabbit)
        mock_flux.rpc.assert_not_called()
        rabbit = _generate_fake_rabbit(compute_nodes, "Down")
        manager._drain_offline_nodes(rabbit)
        mock_flux.rpc.assert_called_once()

    @unittest.mock.patch("flux.kvs.get")
    def test_drain_offline_nodes_allowlist(self, patched_kvs_get):
        with open(JGFDIR / "expected-compute-01.jgf", "r") as json_fd:
            patched_kvs_get.return_value = json.load(json_fd)
        mock_flux = unittest.mock.Mock()
        manager = storage.FluxionRabbitManager(mock_flux, set())
        compute_nodes = {f"compute-0{i}" for i in range(3)}
        rabbit = _generate_fake_rabbit(compute_nodes, "Down")
        manager._drain_offline_nodes(rabbit)
        mock_flux.rpc.assert_not_called()
        manager = storage.FluxionRabbitManager(mock_flux, compute_nodes)
        rabbit = _generate_fake_rabbit(compute_nodes, "Down")
        manager._drain_offline_nodes(rabbit)
        mock_flux.rpc.assert_called_once()


unittest.main(testRunner=TAPTestRunner())
