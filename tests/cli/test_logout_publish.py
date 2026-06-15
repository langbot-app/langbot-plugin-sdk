from __future__ import annotations

import json

import httpx

from langbot_plugin.cli.commands import logout, publish


def test_logout_process_reports_already_logged_out_when_config_missing(
    tmp_path, monkeypatch
):
    prints = []
    monkeypatch.setattr(logout.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(logout, "cli_print", lambda *args: prints.append(args))

    logout.logout_process()

    assert prints == [("already_logged_out",)]


def test_logout_process_removes_old_flat_token_config(tmp_path, monkeypatch):
    config_dir = tmp_path / ".langbot" / "cli"
    config_dir.mkdir(parents=True)
    config_file = config_dir / "config.json"
    config_file.write_text(json.dumps({"access_token": "token"}), encoding="utf-8")
    prints = []
    monkeypatch.setattr(logout.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(logout, "cli_print", lambda *args: prints.append(args))

    logout.logout_process()

    assert not config_file.exists()
    assert prints[0] == ("logout_successful",)


def test_logout_process_removes_current_server_from_nested_config(
    tmp_path, monkeypatch
):
    config_dir = tmp_path / ".langbot" / "cli"
    config_dir.mkdir(parents=True)
    config_file = config_dir / "config.json"
    config_file.write_text(
        json.dumps(
            {
                "https://cloud": {"access_token": "token"},
                "https://other": {"access_token": "other"},
            }
        ),
        encoding="utf-8",
    )
    prints = []
    monkeypatch.setattr(logout.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(logout, "SERVER_URL", "https://cloud")
    monkeypatch.setattr(logout, "cli_print", lambda *args: prints.append(args))

    logout.logout_process()

    assert json.loads(config_file.read_text()) == {
        "https://other": {"access_token": "other"}
    }
    assert prints == [("logout_successful",)]


def test_logout_process_removes_file_when_last_nested_credential_is_deleted(
    tmp_path, monkeypatch
):
    config_dir = tmp_path / ".langbot" / "cli"
    config_dir.mkdir(parents=True)
    config_file = config_dir / "config.json"
    config_file.write_text(
        json.dumps({"https://cloud": {"access_token": "token"}}),
        encoding="utf-8",
    )
    prints = []
    monkeypatch.setattr(logout.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(logout, "SERVER_URL", "https://cloud")
    monkeypatch.setattr(logout, "cli_print", lambda *args: prints.append(args))

    logout.logout_process()

    assert not config_file.exists()
    assert prints[0] == ("logout_successful",)


class FakeResponse:
    def __init__(self, json_data, *, raise_error=False):
        self._json_data = json_data
        self.raise_error = raise_error

    def raise_for_status(self):
        if self.raise_error:
            raise httpx.HTTPStatusError("bad", request=None, response=None)

    def json(self):
        return self._json_data


class FakeClient:
    calls = []
    response = FakeResponse({"code": 0, "data": {"submission": {"status": "live"}}})

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, url, files, data, headers, timeout):
        self.calls.append(
            {
                "url": url,
                "file_name": files["file"].name,
                "data": data,
                "headers": headers,
                "timeout": timeout,
            }
        )
        return self.response


def test_publish_plugin_posts_package_with_bearer_token(tmp_path, monkeypatch):
    package = tmp_path / "plugin.lbpkg"
    package.write_bytes(b"package")
    prints = []
    FakeClient.calls = []
    FakeClient.response = FakeResponse(
        {"code": 0, "data": {"submission": {"status": "live"}}}
    )
    monkeypatch.setattr(publish.httpx, "Client", FakeClient)
    monkeypatch.setattr(publish, "SERVER_URL", "https://cloud")
    monkeypatch.setattr(publish, "cli_print", lambda *args: prints.append(args))

    publish.publish_plugin(str(package), "change", "token")

    assert FakeClient.calls == [
        {
            "url": "https://cloud/api/v1/marketplace/plugins/publish",
            "file_name": str(package),
            "data": {"changelog": "change"},
            "headers": {"Authorization": "Bearer token"},
            "timeout": 300,
        }
    ]
    assert prints == [("publish_successful", "https://cloud")]


def test_publish_plugin_reports_api_failure(tmp_path, monkeypatch):
    package = tmp_path / "plugin.lbpkg"
    package.write_bytes(b"package")
    prints = []
    FakeClient.calls = []
    FakeClient.response = FakeResponse({"code": 1, "msg": "nope"})
    monkeypatch.setattr(publish.httpx, "Client", FakeClient)
    monkeypatch.setattr(publish, "cli_print", lambda *args: prints.append(args))

    publish.publish_plugin(str(package), "", "token")

    assert prints == [("publish_failed", "nope")]


def test_publish_process_requires_login(monkeypatch):
    prints = []
    monkeypatch.setattr(publish, "check_login_status", lambda: False)
    monkeypatch.setattr(publish, "cli_print", lambda *args: prints.append(args))

    publish.publish_process()

    assert prints == [("not_logged_in",)]


def test_publish_process_builds_publishes_and_cleans_tmp_dir(monkeypatch):
    calls = []
    monkeypatch.setattr(publish, "check_login_status", lambda: True)
    monkeypatch.setattr(publish, "get_access_token", lambda: "token")
    monkeypatch.setattr(
        publish,
        "build_plugin_process",
        lambda output_dir: calls.append(("build", output_dir)) or "pkg",
    )
    monkeypatch.setattr(
        publish,
        "publish_plugin",
        lambda path, changelog, token: calls.append(
            ("publish", path, changelog, token)
        ),
    )
    monkeypatch.setattr(
        publish.shutil, "rmtree", lambda path: calls.append(("rmtree", path))
    )

    publish.publish_process()

    assert calls == [
        ("build", publish.TMP_DIR),
        ("publish", "pkg", "", "token"),
        ("rmtree", publish.TMP_DIR),
    ]
