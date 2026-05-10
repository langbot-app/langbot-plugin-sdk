import asyncio
import importlib.util
import os
import re
import subprocess
import sys

from pip._internal import main as pipmain


PYPI_INDEX_URL_ENV = "LANGBOT_PLUGIN_PYPI_INDEX_URL"
PYPI_TRUSTED_HOST_ENV = "LANGBOT_PLUGIN_PYPI_TRUSTED_HOST"
DEFAULT_PYPI_INDEX_URL = "https://pypi.org/simple"


def get_pip_index_args() -> list[str]:
    """Build pip index args from environment. Defaults to official PyPI."""
    index_url = os.getenv(PYPI_INDEX_URL_ENV, DEFAULT_PYPI_INDEX_URL).strip()
    args: list[str] = []

    if index_url:
        args.extend(["-i", index_url])

    trusted_hosts = os.getenv(PYPI_TRUSTED_HOST_ENV, "")
    for host in [item.strip() for item in trusted_hosts.split(",") if item.strip()]:
        args.extend(["--trusted-host", host])

    return args


def install(package):
    pipmain(["install", package, *get_pip_index_args()])


def install_upgrade(package):
    pipmain(
        [
            "install",
            "--upgrade",
            package,
            *get_pip_index_args(),
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
            *get_pip_index_args(),
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


def install_single(
    package: str, extra_params: list | None = None
) -> tuple[int, int, str]:
    """Install a package and return (returncode, downloaded_bytes, output)."""
    if extra_params is None:
        extra_params = []

    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        package,
        *get_pip_index_args(),
    ] + extra_params

    result = subprocess.run(cmd, capture_output=True, text=True)
    output = result.stdout + "\n" + result.stderr
    downloaded_bytes = _parse_downloaded_bytes(output)
    return result.returncode, downloaded_bytes, output


async def install_single_async(
    package: str, extra_params: list | None = None
) -> tuple[int, int, str]:
    """Install a package via async subprocess without blocking the event loop."""
    if extra_params is None:
        extra_params = []

    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        package,
        *get_pip_index_args(),
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
    return proc.returncode, downloaded_bytes, output


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


async def verify_dependencies(deps: list[str]) -> list[str]:
    """Verify that installed dependencies are actually importable.

    Args:
        deps: List of dependency specs, e.g. ['pkg==1.0.0', 'pkg>=2.0']

    Returns:
        List of dependencies that failed import verification.
    """
    missing = []
    for dep in deps:
        pkg_name = (
            dep.split("==")[0]
            .split(">=")[0]
            .split("<=")[0]
            .split("<")[0]
            .split(">")[0]
            .split("[")[0]
            .strip()
        )
        pkg_name_normalized = pkg_name.replace("-", "_")
        if importlib.util.find_spec(pkg_name_normalized) is None:
            if importlib.util.find_spec(pkg_name) is None:
                missing.append(dep)
    return missing


async def install_with_retry(
    package: str,
    max_retries: int = 3,
    retry_delay: float = 1.0,
    extra_params: list | None = None,
) -> tuple[int, int, str]:
    """Install a package with retry on failure.

    Args:
        package: Package name to install.
        max_retries: Maximum number of retry attempts.
        retry_delay: Delay between retries in seconds.
        extra_params: Additional pip parameters.

    Returns:
        (returncode, downloaded_bytes, error_message)
    """
    last_error = ""
    for attempt in range(max_retries):
        returncode, downloaded_bytes, _ = await install_single_async(
            package, extra_params
        )
        if returncode == 0:
            return returncode, downloaded_bytes, ""

        last_error = (
            f"Attempt {attempt + 1}/{max_retries} failed with code {returncode}"
        )

        if attempt < max_retries - 1:
            await asyncio.sleep(retry_delay)

    return returncode, 0, last_error


async def precheck_dependencies(requirements_file: str) -> dict:
    """Pre-check dependency status before installation.

    Args:
        requirements_file: Path to requirements.txt.

    Returns:
        {
            'deps': list[str],
            'already_installed': list[str],
            'to_install': list[str],
            'conflicts': list[str],
        }
    """
    deps = parse_requirements(requirements_file)
    already_installed = []
    to_install = []

    for dep in deps:
        pkg_name = (
            dep.split("==")[0]
            .split(">=")[0]
            .split("<=")[0]
            .split("<")[0]
            .split(">")[0]
            .split("[")[0]
            .strip()
        )
        pkg_name_normalized = pkg_name.replace("-", "_")

        if (
            importlib.util.find_spec(pkg_name_normalized) is not None
            or importlib.util.find_spec(pkg_name) is not None
        ):
            already_installed.append(dep)
        else:
            to_install.append(dep)

    return {
        "deps": deps,
        "already_installed": already_installed,
        "to_install": to_install,
        "conflicts": [],
    }
