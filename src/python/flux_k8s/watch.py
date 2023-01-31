import syslog
import logging

from flux.constants import FLUX_MSGTYPE_REQUEST
import kubernetes as k8s

from flux.core.watchers import fd_handler_wrapper


LOGGER = logging.getLogger(__name__)


class Watch:
    def __init__(self, api, crd, resource_version, cb, *args, **kwargs):
        self.api = api
        self.crd = crd
        self.resource_version = int(resource_version)
        self.cb = cb
        self.cb_args = args
        self.cb_kwargs = kwargs

    def watch(self):
        kwargs = {
            "resource_version": self.resource_version,
            "watch": True,
            "timeout_seconds": 1,
        }
        for event in k8s.watch.Watch().stream(
            self.api.list_namespaced_custom_object, *self.crd, **kwargs
        ):
            # when there are only old workflows lying around and no new ones,
            # the resourceversion will be > 0 but too old for kubernetes to accept it
            if event["type"] == "ERROR" and event["object"]["code"] == 410:
                LOGGER.debug(
                    "Resource version too old in watch, restarting "
                    "from resourceVersion = 0: %s",
                    event["object"]["message"],
                )
                self.resource_version = 0
                return
            event_version = int(event["object"]["metadata"]["resourceVersion"])
            self.resource_version = max(event_version, self.resource_version)
            self.cb(event, *self.cb_args, **self.cb_kwargs)


def watch_cb(reactor, watcher, _r, watchers):
    # watchers.fh.log(syslog.LOG_ERR, "Watch timer cb fired")
    watchers.watch()


def watch_test_cb(fh, t, msg, watchers):
    fh.log(syslog.LOG_DEBUG, "received DWS watch test RPC")
    watchers.watch()
    fh.respond(msg)


class Watchers:
    def __init__(self, fh, watch_interval=5):
        self.watches = []
        self.fh = fh
        self.timer_fh_watch = fh.timer_watcher_create(
            watch_interval, watch_cb, repeat=watch_interval, args=self
        )
        self.timer_fh_watch.start()
        self.msg_fh_watch = fh.msg_watcher_create(
            watch_test_cb, FLUX_MSGTYPE_REQUEST, "dws.watch_test", args=self
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
        self.watches.append(watch)

    def watch(self):
        for watch in self.watches:
            watch.watch()
