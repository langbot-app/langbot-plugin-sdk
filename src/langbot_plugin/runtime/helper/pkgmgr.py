import asyncio
import re
import subprocess
import sys

from pip._internal import main as pipmain


def install(package):
    pipmain(["install", package])


def install_upgrade(package):
    pipmain(
        [
            "install",
            "--upgrade",
            package,
            "-i",
            "https://pypi.tuna.tsinghua.edu.cn/simple",
            "--trusted-host",
            "pypi.tuna.tsinghua.edu.cn",
        ]
    )


def run_pip(params: list):
    pipmain(params)


def install_requirements(file, extra_params: list = []):
    pipmain(
        [
            "install",
            "-r",
            file,
            "-i",
            "https://pypi.tuna.tsinghua.edu.cn/simple",
            "--trusted-host",
            "pypi.tuna.tsinghua.edu.cn",
        ]
        + extra_params
    )


def parse_requirements(file: str) -> list[str]:
    """Parse requirements.txt and return list of package specs."""
    deps = []
    with open(file, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("-"):
                deps.append(line)
    return deps


def install_single(package: str, extra_params: list | None = None) -> tuple[int, int]:
    """Install a single package via subprocess and return (returncode, downloaded_bytes)."""
    if extra_params is None:
        extra_params = []

    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        package,
        "-i",
        "https://pypi.tuna.tsinghua.edu.cn/simple",
        "--trusted-host",
        "pypi.tuna.tsinghua.edu.cn",
    ] + extra_params

    result = subprocess.run(cmd, capture_output=True, text=True)
    downloaded_bytes = _parse_downloaded_bytes(result.stdout + "\n" + result.stderr)
    return result.returncode, downloaded_bytes


async def install_single_async(
    package: str, extra_params: list | None = None
) -> tuple[int, int]:
    """Install a single package via async subprocess, non-blocking for the event loop."""
    if extra_params is None:
        extra_params = []

    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        package,
        "-i",
        "https://pypi.tuna.tsinghua.edu.cn/simple",
        "--trusted-host",
        "pypi.tuna.tsinghua.edu.cn",
    ] + extra_params

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = await proc.communicate()
    output = (
        stdout_bytes.decode("utf-8", errors="ignore")
        + "\n"
        + stderr_bytes.decode("utf-8", errors="ignore")
    )
    downloaded_bytes = _parse_downloaded_bytes(output)
    return proc.returncode, downloaded_bytes


def _parse_downloaded_bytes(output: str) -> int:
    """Parse pip output to extract total downloaded bytes."""
    total = 0
    for line in output.splitlines():
        m = re.search(r"Downloading\s+\S+\s+\(([0-9.]+)\s*(kB|MB|GB|bytes?)\)", line)
        if m:
            val = float(m.group(1))
            unit = m.group(2).lower()
            if unit == "kb":
                total += int(val * 1024)
            elif unit == "mb":
                total += int(val * 1024 * 1024)
            elif unit == "gb":
                total += int(val * 1024 * 1024 * 1024)
            else:
                total += int(val)
    return total
