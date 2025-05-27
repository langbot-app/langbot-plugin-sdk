import argparse

def main():
    parser = argparse.ArgumentParser(description="LangBot Plugin CLI")

    parser.add_argument("--version", action="version", version="0.1.0")
    
    subparsers = parser.add_subparsers(dest="command")
    init_parser = subparsers.add_parser("init", help="Initialize a new plugin")
    init_parser.add_argument("--name", "-n", action="store", type=str, help="The name of the plugin")
    
    args = parser.parse_args()

    print(args)

