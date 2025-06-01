import argparse
from langbot_plugin.version import __version__
from langbot_plugin.runtime import __main__ as runtime_main


def main():
    parser = argparse.ArgumentParser(description="LangBot Plugin CLI")

    subparsers = parser.add_subparsers(dest="command")

    version_parser = subparsers.add_parser("ver", help="Show the version of the CLI")

    init_parser = subparsers.add_parser("init", help="Initialize a new plugin")
    init_parser.add_argument(
        "--name", "-n", action="store", type=str, help="The name of the plugin"
    )

    runtime_parser = subparsers.add_parser("rt", help="Run the runtime")
    runtime_parser.add_argument(
        "--stdio-control", "-s", action="store_true", default=False
    )
    runtime_parser.add_argument("--ws-control-port", type=int, default=5400)
    runtime_parser.add_argument("--ws-debug-port", type=int, default=5401)

    args = parser.parse_args()

    match args.command:
        case "ver":
            print(f"LangBot Plugin CLI v{__version__}")
        case "init":
            print(f"Initializing plugin {args.name}")
        case "rt":
            runtime_main.main(args)
        case _:
            print(f"Unknown command: {args.command}")
