import argparse
import sys
from langbot_plugin.version import __version__
from langbot_plugin.runtime import app as runtime_app
from langbot_plugin.cli.commands.initplugin import init_plugin_process
from langbot_plugin.cli.commands.gencomponent import generate_component_process
from langbot_plugin.cli.commands.runplugin import run_plugin_process

"""
Usage:
    langbot-plugin <command>

Commands:
    ver: Show the version of the CLI
    init: Initialize a new plugin
        - <plugin_name>: The name of the plugin
    comp: Generate a component
        - <component_type>: The type of the component
    run: Run/remote debug the plugin
    rt: Run the runtime
        - [--stdio-control -s]: Use stdio for control connection
        - [--ws-control-port]: The port for control connection
        - [--ws-debug-port]: The port for debug connection
"""


def main():
    parser = argparse.ArgumentParser(description="LangBot Plugin CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # ver command
    ver_parser = subparsers.add_parser("ver", help="Show the version of the CLI")

    # init command
    init_parser = subparsers.add_parser("init", help="Initialize a new plugin")
    init_parser.add_argument("plugin_name", help="The name of the plugin")

    # comp command
    comp_parser = subparsers.add_parser("comp", help="Generate a component")
    comp_parser.add_argument("component_type", help="The type of the component")

    # run command
    run_parser = subparsers.add_parser("run", help="Run/remote debug the plugin")
    run_parser.add_argument(
        "-s", "--stdio", action="store_true", help="Use stdio for control connection"
    )

    # rt command
    rt_parser = subparsers.add_parser("rt", help="Run the runtime")
    rt_parser.add_argument(
        "-s",
        "--stdio-control",
        action="store_true",
        help="Use stdio for control connection",
    )
    rt_parser.add_argument(
        "--ws-control-port",
        type=int,
        help="The port for control connection",
        default=5400,
    )
    rt_parser.add_argument(
        "--ws-debug-port", type=int, help="The port for debug connection", default=5401
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    match args.command:
        case "ver":
            print(f"LangBot Plugin CLI v{__version__}")
        case "init":
            init_plugin_process(args.plugin_name)
        case "comp":
            generate_component_process(args.component_type)
        case "run":
            print("Running plugin in current directory")
            run_plugin_process(args.stdio)
        case "rt":
            runtime_app.main(args)
        case _:
            print(f"Unknown command: {args.command}")
            sys.exit(1)


if __name__ == "__main__":
    main()
