"""Module entry point for the SDK remote AgentRunner daemon."""

from __future__ import annotations

from langbot_plugin.remote.agent_runner.daemon import main

if __name__ == "__main__":
    raise SystemExit(main())

