#!/usr/bin/env python3

import os
import syslog

import kubernetes as k8s
from kubernetes.client.rest import ApiException
import flux
from flux.job.JobID import id_parse
from flux.constants import FLUX_MSGTYPE_REQUEST
from flux.future import Future
from flux_k8s.crd import WORKFLOW_CRD


def create_cb(fh, t, msg, arg):
    api_instance = arg

    try:
        dw_string = msg.payload["dw_string"]
        if not dw_string.startswith("#DW "):
            dw_string = "#DW " + dw_string
        jobid = msg.payload["jobid"]
        spec = {
            "desiredState": "proposal",
            "dwDirectives": [dw_string],
            "jobID": jobid,
            "userID": 1001,
            "wlmID": "5f239bd8-30db-450b-8c2c-a1a7c8631a1a",
        }
        body = {
            "kind": "Workflow",
            "apiVersion": "/".join([WORKFLOW_CRD.group, WORKFLOW_CRD.version]),
            "spec": spec,
            "metadata": {
                "name": "dws-workflow-test-{}".format(jobid),
                "namespace": WORKFLOW_CRD.namespace,
            },
        }
    except Exception as e:
        fh.log(
            syslog.LOG_ERR,
            "Exception when extracting job data from payload: {}".format(e),
        )
        payload = {"success": False, "errstr": str(e)}
        fh.respond(msg, payload)
        return

    try:
        api_response = api_instance.create_namespaced_custom_object(
            *WORKFLOW_CRD,
            body,
        )
    except ApiException as e:
        fh.log(
            syslog.LOG_ERR,
            "Exception when calling CustomObjectsApi->create_namespaced_custom_object: {}".format(
                e
            ),
        )
        payload = {"success": False, "errstr": str(e)}
    else:
        payload = {"success": True}

    fh.respond(msg, payload)


def main():
    k8s_client = k8s.config.new_client_from_config()
    try:
        k8s_api = k8s.client.CustomObjectsApi(k8s_client)
    except ApiException as rest_exception:
        if rest_exception.status == 403:
            raise Exception(
                "You must be logged in to the K8s or OpenShift" " cluster to continue"
            )
        raise

    fh = flux.Flux()
    serv_reg_fut = fh.service_register("dws")

    w = fh.msg_watcher_create(
        create_cb, FLUX_MSGTYPE_REQUEST, "dws.create", args=k8s_api
    )
    w.start()
    serv_reg_fut.get()

    # This job event is used to close the race condition between the python
    # process starting and the `dws` service being registered. Once
    # https://github.com/flux-framework/flux-core/issues/3821 is
    # implemented/closed, this can be replaced with that solution.
    jobid = id_parse(os.environ["FLUX_JOB_ID"])
    Future(fh.job_raise(jobid, "exception", 7, "dws watchers setup")).get()

    fh.reactor_run()

    w.stop().destroy()


if __name__ == "__main__":
    main()
