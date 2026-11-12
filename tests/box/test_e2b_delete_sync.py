"""Deletion authorization uses successful uploads and real no-follow probes."""

import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from langbot_plugin.box.e2b_backend import E2BSandboxBackend, _read_sync_file
from langbot_plugin.box.errors import BoxError
from langbot_plugin.box.models import BoxHostMountMode, BoxMountSpec, BoxSpec


@pytest.fixture
def sync_env(tmp_path):
    host, remote = tmp_path / "host", tmp_path / "remote"
    host.mkdir()
    remote.mkdir()

    async def write(path, data):
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    async def write_files(entries):
        for entry in entries:
            await write(entry["path"], entry["data"])

    async def list_files(root, depth):
        return [
            SimpleNamespace(
                path=str(path),
                size=path.stat().st_size,
                type=SimpleNamespace(value="file" if path.is_file() else "dir"),
            )
            for path in Path(root).rglob("*")
        ]

    async def read(path, **kwargs):
        async def stream():
            yield Path(path).read_bytes()

        return stream()

    async def run(command, **kwargs):
        process = await asyncio.create_subprocess_shell(
            command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        return SimpleNamespace(
            exit_code=process.returncode, stdout=stdout.decode(), stderr=stderr.decode()
        )

    sandbox = SimpleNamespace(
        commands=SimpleNamespace(run=AsyncMock(side_effect=run)),
        files=SimpleNamespace(
            write=AsyncMock(side_effect=write),
            write_files=AsyncMock(side_effect=write_files),
            list=AsyncMock(side_effect=list_files),
            read=AsyncMock(side_effect=read),
        ),
    )
    backend = E2BSandboxBackend(logger=logging.getLogger("delete-sync-test"))
    return backend, sandbox, host, remote


@pytest.mark.asyncio
async def test_deletion_does_not_resurrect_or_remove_new_untracked_files(sync_env):
    backend, sandbox, host, remote = sync_env
    (host / "gone.txt").write_bytes(b"delete")
    (host / "keep.txt").write_bytes(b"keep")
    uploaded = await backend._sync_host_tree_to_e2b(
        sandbox, host_root=str(host), remote_root=str(remote)
    )
    (remote / "gone.txt").unlink()
    (host / "new.txt").write_bytes(b"another execution")
    await backend._sync_e2b_tree_to_host(
        sandbox, host_root=str(host), remote_root=str(remote), uploaded=uploaded
    )
    assert not (host / "gone.txt").exists()
    assert (host / "keep.txt").read_bytes() == b"keep"
    assert (host / "new.txt").read_bytes() == b"another execution"
    await backend._sync_host_tree_to_e2b(
        sandbox, host_root=str(host), remote_root=str(remote)
    )
    assert not (remote / "gone.txt").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    ["content", "replacement", "file_link", "directory_link", "directory_replacement"],
)
async def test_concurrent_changes_and_links_retain_files(sync_env, change, tmp_path):
    backend, sandbox, host, remote = sync_env
    (host / "nested").mkdir()
    target = host / "nested/file.txt"
    target.write_bytes(b"original")
    uploaded = await backend._sync_host_tree_to_e2b(
        sandbox, host_root=str(host), remote_root=str(remote)
    )
    (remote / "nested/file.txt").unlink()
    outside = tmp_path / "other-workspace"
    outside.mkdir()
    (outside / "file.txt").write_bytes(b"other tenant")
    if change == "content":
        target.write_bytes(b"new content")
    elif change == "replacement":
        target.unlink()
        target.write_bytes(b"original")
    elif change == "file_link":
        target.unlink()
        target.symlink_to(outside / "file.txt")
    else:
        (host / "nested").rename(host / "old")
        if change == "directory_link":
            (host / "nested").symlink_to(outside, target_is_directory=True)
        else:
            (host / "nested").mkdir()
            target.write_bytes(b"original")
    with pytest.raises(BoxError, match="conflict or verification failure"):
        await backend._sync_e2b_tree_to_host(
            sandbox, host_root=str(host), remote_root=str(remote), uploaded=uploaded
        )
    assert target.exists()
    assert (outside / "file.txt").read_bytes() == b"other tenant"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", ["list", "omitted", "probe", "invalid", "foreign", "remote_link"]
)
async def test_incomplete_listing_or_probe_cannot_authorize_deletion(sync_env, failure):
    backend, sandbox, host, remote = sync_env
    (host / "file.txt").write_bytes(b"keep")
    uploaded = await backend._sync_host_tree_to_e2b(
        sandbox, host_root=str(host), remote_root=str(remote)
    )
    sandbox.files.list.side_effect = None
    sandbox.files.list.return_value = []  # Simulate a depth/file-count truncated listing.
    if failure == "list":
        sandbox.files.list.side_effect = OSError("incomplete")
    elif failure in {"probe", "invalid", "foreign"}:
        sandbox.commands.run.side_effect = None
        sandbox.commands.run.return_value = SimpleNamespace(
            exit_code=1 if failure == "probe" else 0,
            stdout="not json"
            if failure == "invalid"
            else '["../other-workspace/file.txt"]',
        )
    elif failure == "remote_link":
        (remote / "file.txt").unlink()
        (remote / "file.txt").symlink_to(host / "file.txt")
    if failure == "omitted":
        await backend._sync_e2b_tree_to_host(
            sandbox, host_root=str(host), remote_root=str(remote), uploaded=uploaded
        )
    else:
        with pytest.raises(BoxError):
            await backend._sync_e2b_tree_to_host(
                sandbox, host_root=str(host), remote_root=str(remote), uploaded=uploaded
            )
    assert (host / "file.txt").read_bytes() == b"keep"


@pytest.mark.asyncio
@pytest.mark.parametrize("upload_failure", [False, True])
async def test_only_successful_bounded_uploads_can_authorize_deletion(
    sync_env, monkeypatch, upload_failure
):
    import langbot_plugin.box.e2b_backend as module

    backend, sandbox, host, remote = sync_env
    for name in ("a", "b", "c"):
        (host / name).write_bytes(b"keep")
    if upload_failure:
        sandbox.files.write_files.side_effect = OSError("batch failed")
    write = sandbox.files.write.side_effect

    async def partial_write(path, data):
        if upload_failure and path.endswith("/a"):
            raise OSError("file failed")
        await write(path, data)

    sandbox.files.write.side_effect = partial_write
    monkeypatch.setattr(module, "_MAX_E2B_SYNC_FILES", 2)
    uploaded = await backend._sync_host_tree_to_e2b(
        sandbox, host_root=str(host), remote_root=str(remote)
    )
    if upload_failure:
        assert "a" not in uploaded
    assert len(uploaded) == 2
    for name in uploaded:
        (remote / name).unlink()
    await backend._sync_e2b_tree_to_host(
        sandbox, host_root=str(host), remote_root=str(remote), uploaded=uploaded
    )
    assert {path.name: path.read_bytes() for path in host.iterdir()} == {
        name: b"keep" for name in ("a", "b", "c") if name not in uploaded
    }


@pytest.mark.asyncio
async def test_writable_mounts_delete_only_their_files_and_exclude_nested_projections(
    sync_env, tmp_path
):
    backend, sandbox, host, remote = sync_env
    extra, readonly = tmp_path / "extra", tmp_path / "readonly"
    extra.mkdir()
    readonly.mkdir()
    (host / "file.txt").write_bytes(b"primary")
    (extra / "file.txt").write_bytes(b"extra")
    (extra / "protected").mkdir()
    (extra / "protected/stale.txt").write_bytes(b"shadowed")
    (readonly / "file.txt").write_bytes(b"read only")
    spec = BoxSpec(
        session_id="delete-mounts",
        host_path=str(host),
        mount_path=str(remote),
        extra_mounts=[
            BoxMountSpec(
                host_path=str(extra),
                mount_path=str(remote / "extra"),
                mode=BoxHostMountMode.READ_WRITE,
            ),
            BoxMountSpec(
                host_path=str(readonly),
                mount_path=str(remote / "extra/protected"),
                mode=BoxHostMountMode.READ_ONLY,
            ),
        ],
    )
    backend._materialize_immutable_mount = AsyncMock()
    uploaded = await backend._sync_mounts_to_e2b(sandbox, spec)
    assert "protected/stale.txt" not in uploaded[(str(extra), str(remote / "extra"))]
    assert (str(readonly), str(remote / "extra/protected")) not in uploaded
    (remote / "file.txt").unlink()
    (remote / "extra/file.txt").unlink()
    await backend._sync_mounts_from_e2b(sandbox, spec, uploaded)
    assert not (host / "file.txt").exists() and not (extra / "file.txt").exists()
    assert (extra / "protected/stale.txt").read_bytes() == b"shadowed"
    assert (readonly / "file.txt").read_bytes() == b"read only"


def test_upload_rejects_symlink_escape(tmp_path):
    outside = tmp_path / "outside"
    outside.write_bytes(b"secret")
    host = tmp_path / "host"
    host.mkdir()
    (host / "link").symlink_to(outside)
    with pytest.raises(OSError):
        _read_sync_file(str(host), "link")
    assert outside.read_bytes() == b"secret"
