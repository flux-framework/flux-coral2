#!/usr/bin/env python3

import random
import argparse
import logging
import sys
import os

try:
    import flux
except ImportError:
    sys.exit("'flux hop' must be run in the context of a Flux instance")


# Assume we are operating from the same location as the flux-coral2 repository
here = os.path.abspath(os.path.dirname(__file__))
parent = os.path.dirname(here)
sys.path.insert(0, os.path.abspath(os.path.join(parent, "modules")))

import flux_operator  # noqa

LOGGER = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def generate_job_name():
    """
    Generates a random, two-word name from predefined lists.

    This is akin to Docker, and I have a dumb function like this in libraries
    back to 2017.
    """
    adjectives = [
        "agile",
        "brave",
        "clever",
        "curious",
        "dreamy",
        "fast",
        "glowing",
        "happy",
        "jolly",
        "keen",
        "lucky",
        "noble",
        "serene",
        "sparkling",
        "sunny",
        "vivid",
        "whimsical",
        "zesty",
        "stinky",
        "luxurious",
        "cloudy",
        "dusty",
        "electric",
        "asynchronous",
        "atomic",
        "binary",
        "cached",
        "converged",
        "distributed",
        "elastic",
        "giga",
        "ephemeral",
        "headless",
        "linked",
        "parallel",
        "photonic",
        "peta",
        "quantum",
        "recursive",
        "serverless",
        "stateless",
        "streaming",
        "tera",
        "threaded",
        "turbo",
        "virtual",
        "vector",
        "farty",
        "shiny",
        "squeaky",
        "cozy",
        "wooden",
        "plastic",
        "bouncing",
        "clumsy",
        "dapper",
        "goofy",
        "gossipy",
        "wandering",
        "wobbly",
        "zany",
        "giggling",
        "sleepy",
    ]

    nouns = [
        "breeze",
        "comet",
        "dragon",
        "griffin",
        "kitten",
        "meadow",
        "nova",
        "ocean",
        "otter",
        "panda",
        "phoenix",
        "pixel",
        "quokka",
        "quasar",
        "rabbit",
        "river",
        "robot",
        "star",
        "willow" "accelerator",
        "algorithm",
        "cluster",
        "container",
        "core",
        "daemon",
        "dongle",
        "firewall",
        "gateway",
        "gpu",
        "kernel",
        "lambda",
        "node",
        "packet",
        "pipeline",
        "scheduler",
        "socket",
        "switch",
        "token",
        "iterator",
        "tensor",
        "pancakes",
        "corgi",
        "capybara",
        "gecko",
        "lemur",
        "narwhal",
        "wombat",
        "potato",
        "pancake",
        "waffle",
        "noodles",
        "blender",
        "cushion",
        "doorknob",
        "fork",
        "kettle",
        "lamp",
        "router",
        "sofa",
        "spatula",
        "stapler",
        "toaster",
        "dustbunny",
    ]

    adjective = random.choice(adjectives)
    noun = random.choice(nouns)

    return f"{adjective}-{noun}"


def get_parser():
    """
    Parse command-line arguments.

    These will be used to populate the Flux MiniCluster.
    """
    parser = argparse.ArgumentParser(description="Rabbit MPI MiniCluster Generator")

    # Group for Rabbit MPI specific options for better help output
    group = parser.add_argument_group("Rabbit MPI Options")

    group.add_argument(
        "--image",
        default=flux_operator.default_container,
        help=f"Container image to use for the MPI job. Defaults to '{flux_operator.default_container}'.",
    )
    group.add_argument(
        "--workdir",
        default=None,
        help="Working directory to set inside the container. Defaults to the container's WORKDIR.",
    )
    group.add_argument(
        "--command",
        default=None,
        help="Command to execute in the container. If unset, the MiniCluster will be interactive.",
    )
    group.add_argument(
        "--name",
        default=None,
        help="Name for the MiniCluster",
    )
    group.add_argument(
        "--namespace",
        default="default",
        help="Namespace for the MiniCluster",
    )
    group.add_argument(
        "--tasks",
        type=int,
        default=None,
        help="Total number of MPI tasks to request for the job (at your discretion)",
    )
    group.add_argument(
        "--nodes",
        type=int,
        default=None,
        help="Number of nodes to request for the job. Defaults to using selected rabbit length.",
    )
    group.add_argument(
        "--rabbits",
        default=None,
        help="Comma-separated list of specific rabbit nodes to use (e.g., 'hetchy201,hetchy202').",
    )
    group.add_argument(
        "--add-flux",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Add the Flux view to the container. Use --no-add-flux if your container has Flux.",
    )
    group.add_argument(
        "--succeed",
        action="store_true",
        help="Force the job to always succeed, regardless of the command's exit code.",
    )
    group.add_argument(
        "-e",
        "--env",
        action="append",
        help="Set an environment variable in the container (e.g., --env KEY=VALUE). Can be specified multiple times.",
    )
    return parser


def parse_env(environ):
    """
    Parse the provided environment.
    """
    env_dict = {}
    for item in environ:
        if "=" not in item:
            LOGGER.error(
                f"Invalid environment variable format: '{item}'. Use KEY=VALUE."
            )
            sys.exit(1)
        key, value = item.split("=", 1)
        env_dict[key] = value


def main():
    """
    Main entrypoint for the client script.
    """
    parser = get_parser()
    args = parser.parse_args()

    # --rabbits are required for now.
    if not args.rabbits:
        LOGGER.error("List of rabbit nodes --rabbits is required. Exiting.")
        sys.exit(0)

    # Generate a faux jobspec - for now we just need attributes (and not resources)
    wabbits = [x.strip() for x in args.rabbits.split(",")]
    mpi_attributes = {"rabbits": wabbits}
    if args.image:
        mpi_attributes["image"] = args.image
    if args.workdir:
        mpi_attributes["workdir"] = args.workdir
    if args.command:
        mpi_attributes["command"] = args.command
    if args.tasks:
        mpi_attributes["tasks"] = args.tasks
    if args.nodes:
        mpi_attributes["nodes"] = args.nodes
    if not args.nodes:
        mpi_attributes["nodes"] = len(wabbits)
    if args.succeed:
        # The class checks for presence, so any non-None value works.
        mpi_attributes["succeed"] = True

    if args.add_flux is False:
        mpi_attributes["add_flux"] = args.add_flux

    # Parse environment variables from KEY=VALUE strings into a dictionary
    if args.env:
        mpi_attributes["env"] = parse_env(args.env)

    # Construct the final jobspec
    jobspec = {
        "attributes": {
            "system": {
                "rabbit": {
                    "mpi": mpi_attributes,
                }
            }
        }
    }

    # We can now generate a RabbitMPI job akin to if we had a normal JobSpec
    rabbit_job = flux_operator.RabbitMPI(jobspec)

    # You can now use the rabbit_job object to get the processed attributes.
    print("--- Generated Rabbit MPI Configuration ---")
    print(f"Working Directory: {rabbit_job.workdir}")
    print(f"  Container Image: {rabbit_job.container}")
    print(f"   Always Succeed: {rabbit_job.always_succeed}")
    print(f"   Target Rabbits: {rabbit_job.rabbits}")
    print(f"    Add Flux View: {rabbit_job.add_flux()}")
    print(f"      Interactive: {rabbit_job.interactive}")
    print(f"      Environment: {rabbit_job.environment}")
    print(f"          Enabled: {rabbit_job.is_enabled()}")
    print(f"          Command: {rabbit_job.command}")
    print(f"            Tasks: {rabbit_job.tasks}")
    print(f"            Nodes: {rabbit_job.nodes}")

    # Make a funny name!
    name = args.name or generate_job_name()

    # Generate a regular MiniCluster
    handle = flux.Flux()
    minicluster = flux_operator.MiniCluster(handle)
    minicluster.generate(rabbit_job, name, args.namespace)

    LOGGER.info("Rabbit MPI jobspec processed successfully.")


if __name__ == "__main__":
    main()
