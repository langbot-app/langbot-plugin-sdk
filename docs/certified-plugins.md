# Certified Plugin Archives

`langbot_plugin.certification` provides an opt-in archive certification format. It does not change `lbp build` output: existing `.lbpkg` archives retain an empty ZIP comment and verify as `absent`.

## Manifest runtime profile

A plugin manifest may opt into the certified shared-runtime profile only with:

```yaml
execution:
  python:
    path: main.py
    attr: Plugin
  sharedRuntime: shared-runtime-v1
```

If `execution.sharedRuntime` is absent, the manifest remains a dedicated-runtime manifest. Any other value is rejected by the SDK manifest model and by certification verification.

## Envelope format

The envelope is compact, sorted UTF-8 JSON in the ZIP comment. The supported schema is `certified-plugin-envelope-v1` with exactly these fields:

```json
{
  "schema": "certified-plugin-envelope-v1",
  "key_id": "issuer-key-id",
  "plugin_id": {"author": "publisher", "name": "plugin"},
  "version": "1.2.3",
  "digest": "lowercase-sha256-hex",
  "shared_runtime": "shared-runtime-v1",
  "signature": "base64-signature"
}
```

`shared_runtime` is `null` for dedicated-runtime manifests. The digest is SHA-256 of the original ZIP bytes with only its ZIP comment removed, so adding or replacing the envelope does not change the signed digest. ZIP comments are limited to 16 KiB; archive manifests are read without extraction and limited to 1 MiB.

## Signing and verification

The module is algorithm-neutral and does not add a cryptography dependency. Supply the signing callback and a trusted-key resolver from the deployment that owns issuer keys. Production integrations should use an asymmetric signature scheme such as Ed25519; do not use the test-only HMAC pattern as a trust boundary.

```python
from langbot_plugin.certification import create_envelope, verify_archive, write_envelope

# signer(payload: bytes) -> bytes signs with the issuer's private key.
envelope = create_envelope(archive_bytes, "issuer-key-id", signer)
certified_archive = write_envelope(archive_bytes, envelope)

# key_resolver(key_id) -> verifier | None, where verifier(payload, signature) -> bool.
result = verify_archive(certified_archive, key_resolver)
if result.status != "valid":
    raise ValueError(result.status)
```

Verification binds the envelope's `plugin_id.author`, `plugin_id.name`, `version`, normalized digest, and `shared_runtime` to `manifest.yaml`.

## Verification statuses

- `absent`: no ZIP comment; legacy archive.
- `valid`: envelope, signature, digest, and manifest bindings all match.
- `malformed`: invalid ZIP comment or malformed envelope.
- `unknown_key`: the configured resolver does not trust `key_id`.
- `signature_invalid`: the trusted key rejected the envelope signature.
- `digest_mismatch`: archive bytes outside the ZIP comment changed.
- `manifest_mismatch`: the signed identity or runtime profile differs from `manifest.yaml`.
- `unsupported_schema`: a well-formed envelope uses an unsupported schema.
