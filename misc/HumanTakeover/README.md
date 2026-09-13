# HumanTakeover

[简体中文](readme/README_zh_Hans.md) | [日本語](readme/README_ja_JP.md)

A human-takeover & manual-reply plugin for LangBot. It lets a human operator take over any private or group conversation through a built-in Web console, block the AI from responding, and reply manually with text, images, or files.

## Features

- **Block AI on takeover**: When a conversation is taken over, the AI pipeline is stopped (`prevent_default`).
- **Web console (single Page component)**: Two-column layout with a collapsible info panel, following the LangBot design language and dark/light themes.
- **All conversations**: Lists every private chat and group chat; group messages distinguish individual senders.
- **Manual reply**: Send plain text, images (base64), and files (base64) from the console.
- **10-minute auto-release**: If there is no human response within the configured timeout, the takeover is released automatically. A live countdown is shown during human silence.
- **Trigger words**: When a user message contains a configured trigger word, the conversation is flagged as unhandled (WeChat-style red dot on the avatar), an alert toast is shown, and (optionally) the conversation is auto-taken-over.
- **Profile cards**: Click a user/group avatar to view available info (ID, group, bot, adapter).
- **Persistence**: Conversations and messages are stored via LangBot `plugin_storage` (database-backed) and survive restarts.
- **Clear storage**: One-click button (with a custom confirm dialog) to wipe all stored data.
- **i18n**: Full Simplified Chinese / English interface.

## Configuration

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `takeover_timeout` | integer | 600 | Auto-release takeover if no human response within this many seconds. |
| `trigger_words` | array[string] | `[]` | Messages containing any of these words flag the session as unhandled and auto take over. |
| `auto_takeover_on_trigger` | boolean | true | Whether to automatically take over when a trigger word is matched. |

## Usage

1. Install and enable the plugin in LangBot, configure the fields above.
2. Open the **Human Takeover** page from the WebUI sidebar.
3. Select a conversation, click **Take Over** to block the AI, then reply manually.
4. Click the avatar to inspect user/group info; use **Clear Storage** to reset data.

## Storage and upgrades

Each session's metadata and history are now saved together under a separate
`ht_session_v2_<sha256>` key. Updating one conversation no longer rewrites every
conversation's history. Writes are serialized in the plugin process and storage
failures are returned to callers rather than reported as successful saves.

On first startup, the plugin reads the legacy `ht_sessions` / `ht_messages`
snapshots and copies **all** their records into the new format, without applying
retention during migration. A completion marker is written only after every
session has been saved. Interrupted migrations can be retried. The original keys
remain as an untouched migration-time backup; they are not updated afterward.
Subsequent startups read only the new records. Back up plugin storage before
upgrading: **downgrading does not include conversations changed after migration**.
The console's Clear storage action removes both formats and their history.

A session record is limited to **8 MiB of UTF-8 JSON**, leaving room for SDK
base64 encoding within the 16 MiB transport frame. Exceeding this limit raises an
explicit error before sending the storage request; it does not trim message
content or discard previously saved history. New messages still use the existing
300-message retention policy. A failed save restores the last acknowledged cache;
this is not evidence that a remotely dispatched write was rejected.
A legacy session exceeding the limit stops initialization and leaves the original
snapshots intact; it requires export/recovery rather than automatic truncation.
A legacy aggregate already too large to read through the SDK also requires
out-of-band recovery. Failed initialization never falls back to empty storage.

This is single-plugin-process serialization, not a multi-writer transaction.
Clear storage deletes multiple keys and may partially complete on a storage
failure. Caller cancellation (including repeated cancellation) waits for the
shielded update, clear, or migration to settle before releasing serialization.
An acknowledged commit remains in the cache even if its caller was cancelled.

Any remote mutation error, including a timeout or lost connection, has an unknown
commit outcome: it marks storage uninitialized and blocks further writes, clear,
and ordinary reinitialization. Do not assume the write was rejected or retry it.
An operator must first establish that the old host operations have finished (or
stop the old host writer), reconcile persisted data, then reload using
`await plugin.initialize(storage_reconciled=True)` or restart the plugin. A mere
read or plugin restart while old host requests can still commit is **not** safe
reconciliation. Partial clear/migration can then be retried.
If a manual reply was delivered but saving its
history failed, the console explicitly warns **not to resend** it.

### Storage regression tests

With `langbot-plugin==0.5.7` installed, run from `HumanTakeover/`:

```sh
python -m unittest discover -s tests -v
```

Tests cover migration/readback, bounded per-session writes, concurrent updates,
rollback/error reporting, retention and clearing. The stdio test uses the real
SDK and an OS subprocess, with a synthetic Host KV sink; it is not a full LangBot
deployment or a live database test.

## Components

- **EventListener**: records messages, caches the adapter, matches trigger words, and blocks the AI while taken over.
- **Page (`console`)**: the Web management console (`index.html` + `console.py`).
