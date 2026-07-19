from __future__ import annotations

import hashlib
import io
import stat
import zipfile

import pytest

from langbot_plugin.entities.io.context import InstallationBinding
from langbot_plugin.runtime.plugin.artifact import PluginArtifactStore


def _plugin_package(*, body: str = "VALUE = 1", extra_manifest: str = "") -> bytes:
    manifest = f"""
apiVersion: v1
kind: Plugin
metadata:
  author: tester
  name: demo
  version: 1.0.0
spec:
  worker:
    max_cpus: 99
{extra_manifest}
"""
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("manifest.yaml", manifest)
        archive.writestr("main.py", body)
        archive.writestr(".env", "FORGED_RUNTIME_SECRET=yes")
    return output.getvalue()


def _binding(installation_uuid: str, digest: str) -> InstallationBinding:
    return InstallationBinding(
        instance_uuid="instance-1",
        workspace_uuid=f"workspace-{installation_uuid}",
        placement_generation=1,
        installation_uuid=installation_uuid,
        runtime_revision=1,
        artifact_digest=digest,
    )


def test_same_digest_shares_read_only_code_but_not_writable_paths(tmp_path):
    package = _plugin_package()
    digest = hashlib.sha256(package).hexdigest()
    store = PluginArtifactStore(tmp_path / "plugin-runtime")

    artifact_a = store.install_package(package, digest)
    artifact_b = store.install_package(package, digest)
    paths_a = store.ensure_installation_paths(_binding("installation-a", digest))
    paths_b = store.ensure_installation_paths(_binding("installation-b", digest))

    assert artifact_a.code_path == artifact_b.code_path
    assert stat.S_IMODE(artifact_a.code_path.stat().st_mode) == 0o555
    assert stat.S_IMODE((artifact_a.code_path / "main.py").stat().st_mode) == 0o444
    assert paths_a.home_path != paths_b.home_path
    assert paths_a.tmp_path != paths_b.tmp_path
    assert paths_a.data_path != paths_b.data_path
    assert paths_a.home_path.is_dir() and paths_b.home_path.is_dir()


def test_different_digest_never_shares_artifact_path(tmp_path):
    package_a = _plugin_package(body="VALUE = 1")
    package_b = _plugin_package(body="VALUE = 2")
    digest_a = hashlib.sha256(package_a).hexdigest()
    digest_b = hashlib.sha256(package_b).hexdigest()
    store = PluginArtifactStore(tmp_path / "plugin-runtime")

    artifact_a = store.install_package(package_a, digest_a)
    artifact_b = store.install_package(package_b, digest_b)

    assert digest_a != digest_b
    assert artifact_a.code_path != artifact_b.code_path
    assert artifact_a.code_path.parent.name == digest_a
    assert artifact_b.code_path.parent.name == digest_b


def test_artifact_digest_mismatch_and_zip_slip_fail_closed(tmp_path):
    package = _plugin_package()
    store = PluginArtifactStore(tmp_path / "plugin-runtime")

    with pytest.raises(ValueError, match="digest mismatch"):
        store.install_package(package, "0" * 64)

    malicious = io.BytesIO()
    with zipfile.ZipFile(malicious, "w") as archive:
        archive.writestr("../escape", "bad")
        archive.writestr("manifest.yaml", "kind: Plugin")
    malicious_package = malicious.getvalue()
    with pytest.raises(ValueError, match="unsafe path"):
        store.install_package(
            malicious_package,
            hashlib.sha256(malicious_package).hexdigest(),
        )
