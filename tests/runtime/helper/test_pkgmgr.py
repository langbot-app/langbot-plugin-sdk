from __future__ import annotations

import asyncio

from langbot_plugin.runtime.helper import pkgmgr


def test_get_pip_index_args_defaults_to_official_pypi(monkeypatch):
    monkeypatch.delenv(pkgmgr.PYPI_INDEX_URL_ENV, raising=False)
    monkeypatch.delenv(pkgmgr.PYPI_TRUSTED_HOST_ENV, raising=False)

    assert pkgmgr.get_pip_index_args() == ["-i", pkgmgr.DEFAULT_PYPI_INDEX_URL]


def test_get_pip_index_args_reads_custom_index_and_trusted_hosts(monkeypatch):
    monkeypatch.setenv(pkgmgr.PYPI_INDEX_URL_ENV, "https://mirror/simple")
    monkeypatch.setenv(pkgmgr.PYPI_TRUSTED_HOST_ENV, "mirror.local, cache.local ")

    assert pkgmgr.get_pip_index_args() == [
        "-i",
        "https://mirror/simple",
        "--trusted-host",
        "mirror.local",
        "--trusted-host",
        "cache.local",
    ]


def test_parse_requirements_ignores_comments_blank_lines_and_options(tmp_path):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text(
        "\n# comment\nrequests>=2\n-r base.txt\n--index-url https://mirror\npydantic\n",
        encoding="utf-8",
    )

    assert pkgmgr.parse_requirements(str(requirements)) == ["requests>=2", "pydantic"]


def test_parse_downloaded_bytes_supports_common_pip_units():
    output = "\n".join(
        [
            "Downloading a.whl (1.5 kB)",
            "Downloading b.whl (2 MB)",
            "Downloading c.whl (3 bytes)",
        ]
    )

    assert pkgmgr._parse_downloaded_bytes(output) == int(1.5 * 1024) + 2 * 1024 * 1024 + 3


def test_install_single_builds_pip_command_and_returns_parsed_download_size(monkeypatch):
    class Result:
        returncode = 0
        stdout = "Downloading pkg.whl (1 kB)"
        stderr = ""

    calls = []
    monkeypatch.setattr(pkgmgr, "get_pip_index_args", lambda: ["-i", "https://mirror"])
    monkeypatch.setattr(pkgmgr.subprocess, "run", lambda cmd, **kwargs: calls.append((cmd, kwargs)) or Result())

    returncode, downloaded, output = pkgmgr.install_single("demo", ["--no-deps"])

    assert returncode == 0
    assert downloaded == 1024
    assert "Downloading pkg.whl" in output
    assert calls[0][0][-4:] == ["demo", "-i", "https://mirror", "--no-deps"]


def test_install_requirements_passes_extra_params_to_pip(monkeypatch):
    calls = []
    monkeypatch.setattr(pkgmgr, "get_pip_index_args", lambda: ["-i", "https://mirror"])
    monkeypatch.setattr(pkgmgr, "pipmain", lambda params: calls.append(params))

    pkgmgr.install_requirements("requirements.txt", ["--no-deps"])

    assert calls == [
        [
            "install",
            "-r",
            "requirements.txt",
            "-i",
            "https://mirror",
            "--no-deps",
        ]
    ]


def test_install_single_async_builds_pip_command_and_parses_output(monkeypatch):
    class Proc:
        returncode = 0

        async def communicate(self):
            return b"Downloading async.whl (2 kB)", b""

    calls = []

    async def fake_create_subprocess_exec(*cmd, stdout=None, stderr=None):
        calls.append((cmd, stdout, stderr))
        return Proc()

    monkeypatch.setattr(pkgmgr, "get_pip_index_args", lambda: [])
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    returncode, downloaded, output = asyncio.run(pkgmgr.install_single_async("demo"))

    assert returncode == 0
    assert downloaded == 2048
    assert "Downloading async.whl" in output
    assert calls[0][0][-2:] == ("install", "demo")
