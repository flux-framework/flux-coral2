"""Module defining utilities for watching K8s resources."""

import syslog
import logging

from flux.constants import FLUX_MSGTYPE_REQUEST
import kubernetes as k8s
from kubernetes.client.rest import ApiException


LOGGER = logging.getLogger(__name__)


class Watch:
    """Represents a watch on a k8s resource."""

    def __init__(self, api, crd, resource_version, callback, *args, **kwargs):
        self.api = api
        self.crd = crd
        self.resource_version = resource_version
        self.callback = callback
        self.cb_args = args
        self.cb_kwargs = kwargs

    def watch(self):
        """Watch resource, firing off callbacks.

        When there are only old resources lying around and no new ones,
        the resourceversion will be > 0 but too old for kubernetes to accept it.

        Some versions of kubernetes (newer ones) throw an exception, others
        just return an ERROR event. Handle both cases by resetting the
        resource_version to 0.
        """
        kwargs = {
            "resource_version": self.resource_version,
            "watch": True,
            "timeout_seconds": 1,
        }
        try:
            stream = k8s.watch.Watch().stream(
                self.api.list_namespaced_custom_object, *self.crd, **kwargs
            )
        except ApiException as apiexc:
            if apiexc.status != 410:
                raise
            self.resource_version = kwargs["resource_version"] = 0
            stream = k8s.watch.Watch().stream(
                self.api.list_namespaced_custom_object, *self.crd, **kwargs
            )
        try:
            for event in stream:
                if event["type"] == "ERROR" and event["object"]["code"] == 410:
                    LOGGER.debug(
                        "Resource version too old in watch, restarting "
                        "from resourceVersion = 0: %s",
                        event["object"]["message"],
                    )
                    self.resource_version = 0
                    self.watch()
                    return
                self.resource_version = event["object"]["metadata"]["resourceVersion"]
                self.callback(event, *self.cb_args, **self.cb_kwargs)
        except ApiException as apiexc:
            if apiexc.status != 410:
                raise
            self.resource_version = 0
            self.watch()


def _watch_cb(reactor, watcher, _r, watchers):
    watchers.watch()


def _watch_test_cb(handle, _t, msg, watchers):
    """Respond to watch_test RPC."""
    handle.log(syslog.LOG_DEBUG, "received DWS watch test RPC")
    watchers.watch()
    handle.respond(msg)


class Watchers:
    """Watch a group of resources."""

    def __init__(self, handle, watch_interval=5):
        self.watches = []
        self.handle = handle
        self.timer_fh_watch = handle.timer_watcher_create(
            watch_interval, _watch_cb, repeat=watch_interval, args=self
        )
        self.timer_fh_watch.start()
        # for testing purposes
        self.msg_fh_watch = handle.msg_watcher_create(
            _watch_test_cb, FLUX_MSGTYPE_REQUEST, "dws.watch_test", args=self
        )
        self.msg_fh_watch.start()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.timer_fh_watch.stop()
        self.timer_fh_watch.destroy()
        self.msg_fh_watch.stop()
        self.msg_fh_watch.destroy()

    def add_watch(self, watch):
        """Add a new resource to watch."""
        self.watches.append(watch)

    def watch(self):
        """Watch all resources currently registered."""
        for watch in self.watches:
            watch.watch()
