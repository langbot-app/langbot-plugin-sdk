# handler for command
import asyncio
import argparse

from langbot_plugin.runtime.app import Application


def main(args: argparse.Namespace):
    app = Application(args)
    asyncio.run(app.run())
