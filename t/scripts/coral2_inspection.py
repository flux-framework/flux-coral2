import argparse
import importlib
import importlib.util
import sys
import socket
import pathlib
import logging

import flux
import flux.job
from flux_k8s import cleanup
from flux_k8s import workflow


LOGGER = logging.getLogger(__name__)


def setup_parsing():
    """Set up argument parsing."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "jobid", type=flux.job.JobID, help="job ID of a running job to inspect"
    )
    parser.add_argument(
        "path",
        type=pathlib.Path,
        help="path to coral2_dws module to import",
    )
    return parser


def get_coral2_dws(args):
    spec = importlib.util.spec_from_file_location("coral2_dws", args.path.absolute())
    coral2_dws = importlib.util.module_from_spec(spec)
    sys.modules["coral2_dws"] = coral2_dws
    spec.loader.exec_module(coral2_dws)
    return coral2_dws


def main():
    handle = flux.Flux()
    args = setup_parsing().parse_args()
    coral2_dws = get_coral2_dws(args)
    winfo = workflow.WorkflowInfo.get(int(args.jobid))
    k8s_api = cleanup.get_k8s_api(handle.conf_get("rabbit.kubeconfig"))
    rabbits = coral2_dws.get_servers_with_active_allocations(k8s_api, winfo.name)
    print(f"{__name__}: rabbits: {rabbits}")
    # there should be one rabbit with an active allocation and one mount
    assert isinstance(rabbits, set)
    assert len(rabbits) == 1
    assert isinstance(rabbits.pop(), str)
    unmounts = coral2_dws.get_clientmounts_not_in_state(k8s_api, winfo.name, "mounted")
    print(f"{__name__}: unmounts: {unmounts}")
    assert len(unmounts) == 0
    mounts = coral2_dws.get_clientmounts_not_in_state(k8s_api, winfo.name, "foobar")
    print(f"{__name__}: mounts: {mounts}")
    assert isinstance(mounts, list)
    assert len(mounts) == 1
    assert isinstance(mounts[0], str)
    assert mounts[0] == socket.gethostname()


if __name__ == "__main__":
    main()
