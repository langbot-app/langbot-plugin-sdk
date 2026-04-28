import asyncio
import importlib.util
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


async def verify_dependencies(deps: list[str]) -> list[str]:
    """验证依赖是否真正安装成功

    Args:
        deps: 依赖列表，格式如 ['package==1.0.0', 'package>=2.0']

    Returns:
        未安装成功的依赖列表
    """
    missing = []
    for dep in deps:
        # 提取包名（去除版本约束）
        pkg_name = (
            dep.split("==")[0]
            .split(">=")[0]
            .split("<=")[0]
            .split("<")[0]
            .split(">")[0]
            .split("[")[0]
            .strip()
        )
        # 处理包名中的连字符（pip 安装时会转换为下划线）
        pkg_name_normalized = pkg_name.replace("-", "_")
        if importlib.util.find_spec(pkg_name_normalized) is None:
            # 尝试原始名称
            if importlib.util.find_spec(pkg_name) is None:
                missing.append(dep)
    return missing


async def install_with_retry(
    package: str,
    max_retries: int = 3,
    retry_delay: float = 1.0,
    extra_params: list | None = None,
) -> tuple[int, int, str]:
    """带重试机制的依赖安装

    Args:
        package: 要安装的包名
        max_retries: 最大重试次数
        retry_delay: 重试间隔（秒）
        extra_params: 额外的 pip 参数

    Returns:
        (returncode, downloaded_bytes, error_message)
    """
    last_error = ""
    for attempt in range(max_retries):
        returncode, downloaded_bytes = await install_single_async(package, extra_params)
        if returncode == 0:
            return returncode, downloaded_bytes, ""

        # 获取错误信息
        last_error = f"Attempt {attempt + 1}/{max_retries} failed with code {returncode}"

        if attempt < max_retries - 1:
            await asyncio.sleep(retry_delay)

    return returncode, 0, last_error


async def precheck_dependencies(requirements_file: str) -> dict:
    """依赖预检查 - 检查依赖冲突和已安装状态

    Args:
        requirements_file: requirements.txt 文件路径

    Returns:
        {
            'deps': list[str],           # 所有依赖列表
            'already_installed': list[str],  # 已安装的依赖
            'to_install': list[str],     # 需要安装的依赖
            'conflicts': list[str]       # 可能的冲突（可选）
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
        "conflicts": [],  # 暂不实现冲突检测
    }
