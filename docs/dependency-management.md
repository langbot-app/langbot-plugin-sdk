# Plugin Dependency Management

## Problem

When users update their LangBot containers (by pulling new images and rebuilding), the Python environment is fresh but the `data/plugins/` directory persists as a mounted volume. This causes plugin dependencies to be lost, leading to plugin failures.

## OSS development profile

The runtime now **automatically reinstalls all plugin dependencies on every startup**. This is a simple and straightforward approach that ensures dependencies are always available.

### How It Works

When the runtime starts and launches plugins (in `launch_all_plugins()`):
1. For each plugin directory in `data/plugins/`
2. Check if a `requirements.txt` file exists
3. If it exists, run `pip install -r requirements.txt`
4. Then launch the plugin

This happens **every time** the runtime starts, ensuring that:
- After container rebuild, all dependencies are reinstalled
- After requirements.txt changes, new dependencies are installed
- No state tracking or complexity needed

This is the legacy `oss_dev` behavior and remains backward compatible.

## Shared multi-tenant profile

The shared Runtime never installs plugin dependencies into its own Python
environment. Before an enabled desired installation can launch, it:

1. Parses the verified artifact's `requirements.txt` as PEP 508 requirements.
2. Runs pip inside a policy-limited nsjail with only a writable staging target
   and temporary directory.
3. Rejects symbolic links and verifies the installed distribution metadata.
4. Atomically publishes the dependency tree as read-only under
   `data/plugin-runtime/environments/sha256/<environment-digest>`.
5. Mounts that tree read-only into each matching plugin worker.

The environment digest includes the artifact and requirements digests, Python
ABI, Runtime version, and installer schema. Therefore the same verified
artifact can reuse one immutable dependency tree across installations without
sharing any writable plugin state. Concurrent preparation is serialized, and a
failure leaves no ready or half-published tree. Apply/reconcile reports
`state=failed`, `error_code=dependency_prepare_failed`, and does not launch the
worker. Reapplying the same desired revision retries preparation.

Shared artifacts cannot place pip control options such as `--index-url`,
`--extra-index-url`, or nested `-r` files in `requirements.txt`; index and trust
configuration is owned by the Runtime process.

### Implementation

Modified `src/langbot_plugin/runtime/plugin/mgr.py`:
- `launch_all_plugins()`: Added `pip install -r requirements.txt` before launching each plugin

### Benefits

1. **Simple**: No complex state tracking or hash computation
2. **Reliable**: Dependencies always installed, regardless of container state
3. **Automatic**: Works automatically after container rebuild
4. **Backward Compatible**: Works with existing plugins without modification
5. **Robust**: Handles all edge cases (pip handles already-installed packages efficiently)

### Performance Considerations

- `pip` is smart enough to skip reinstalling packages that are already installed at the correct version
- The startup time will increase slightly due to pip checking installed packages
- For most plugins with few dependencies, this overhead is minimal
