"""Tests for artifact entities and proxy methods."""

from __future__ import annotations

import pytest
import pydantic

from langbot_plugin.api.entities.builtin.agent_runner.artifact import (
    ArtifactMetadata,
    ArtifactReadResult,
)


class TestArtifactMetadata:
    """Test ArtifactMetadata entity."""

    def test_artifact_metadata_required_fields(self):
        """Test that required fields are enforced."""
        with pytest.raises(pydantic.ValidationError):
            ArtifactMetadata()

    def test_artifact_metadata_minimal(self):
        """Test minimal valid metadata."""
        metadata = ArtifactMetadata(
            artifact_id="art_001",
            artifact_type="image",
            source="platform",
        )
        assert metadata.artifact_id == "art_001"
        assert metadata.artifact_type == "image"
        assert metadata.source == "platform"
        assert metadata.mime_type is None
        assert metadata.conversation_id is None
        assert metadata.run_id is None

    def test_artifact_metadata_full(self):
        """Test full metadata with all fields."""
        metadata = ArtifactMetadata(
            artifact_id="art_001",
            artifact_type="file",
            mime_type="application/pdf",
            name="document.pdf",
            size_bytes=1024,
            sha256="abc123",
            source="runner",
            conversation_id="conv_001",
            run_id="run_001",
            runner_id="plugin:test/plugin/runner",
            created_at=1700000000,
            expires_at=1700086400,
            metadata={"page_count": 10},
        )
        assert metadata.artifact_id == "art_001"
        assert metadata.mime_type == "application/pdf"
        assert metadata.size_bytes == 1024
        assert metadata.metadata == {"page_count": 10}

    def test_artifact_metadata_serialization(self):
        """Test serialization to JSON."""
        metadata = ArtifactMetadata(
            artifact_id="art_001",
            artifact_type="image",
            source="platform",
            metadata={"key": "value"},
        )
        data = metadata.model_dump()
        assert data["artifact_id"] == "art_001"
        assert data["metadata"] == {"key": "value"}

    def test_artifact_metadata_extra_forbidden(self):
        """Test that extra fields are forbidden."""
        with pytest.raises(pydantic.ValidationError):
            ArtifactMetadata(
                artifact_id="art_001",
                artifact_type="image",
                source="platform",
                unknown_field="should fail",
            )

    def test_artifact_metadata_host_round_trip(self):
        """Test that metadata from Host can be parsed without error.

        This verifies that Host returns only fields defined in SDK ArtifactMetadata,
        not Host-only fields like bot_id, workspace_id, storage_key, storage_type.
        """
        # Simulate what Host returns (after _row_to_dict fix)
        host_response = {
            "artifact_id": "art_001",
            "artifact_type": "file",
            "mime_type": "application/pdf",
            "name": "document.pdf",
            "size_bytes": 1024,
            "sha256": "abc123",
            "source": "runner",
            "conversation_id": "conv_001",
            "run_id": "run_001",
            "runner_id": "plugin:test/plugin/runner",
            "created_at": 1700000000,
            "expires_at": 1700086400,
            "metadata": {"page_count": 10},
        }

        # Should not raise ValidationError
        metadata = ArtifactMetadata.model_validate(host_response)
        assert metadata.artifact_id == "art_001"
        assert metadata.name == "document.pdf"

    def test_artifact_metadata_rejects_host_only_fields(self):
        """Test that Host-only fields cause validation error.

        This ensures we don't accidentally leak Host-only fields.
        """
        # If Host returns bot_id or workspace_id, parsing should fail
        host_response_with_extras = {
            "artifact_id": "art_001",
            "artifact_type": "file",
            "source": "runner",
            "bot_id": "bot_001",  # Host-only field
        }

        with pytest.raises(pydantic.ValidationError):
            ArtifactMetadata.model_validate(host_response_with_extras)


class TestArtifactReadResult:
    """Test ArtifactReadResult entity."""

    def test_artifact_read_result_minimal(self):
        """Test minimal read result."""
        result = ArtifactReadResult(
            artifact_id="art_001",
        )
        assert result.artifact_id == "art_001"
        assert result.content_base64 is None
        assert result.file_key is None
        assert result.offset == 0

    def test_artifact_read_result_inline(self):
        """Test read result with inline content."""
        import base64

        content = b"test content"
        result = ArtifactReadResult(
            artifact_id="art_001",
            mime_type="text/plain",
            size_bytes=len(content),
            offset=0,
            length=len(content),
            content_base64=base64.b64encode(content).decode("utf-8"),
            has_more=False,
        )
        assert result.content_base64 is not None
        assert base64.b64decode(result.content_base64) == content
        assert result.has_more is False

    def test_artifact_read_result_file_key(self):
        """Test read result with file key for chunked transfer."""
        result = ArtifactReadResult(
            artifact_id="art_001",
            mime_type="video/mp4",
            size_bytes=10_000_000,
            offset=0,
            length=None,
            file_key="temp_file_001",
            has_more=True,
        )
        assert result.file_key == "temp_file_001"
        assert result.content_base64 is None
        assert result.has_more is True

    def test_artifact_read_result_serialization(self):
        """Test serialization to JSON."""
        result = ArtifactReadResult(
            artifact_id="art_001",
            mime_type="image/png",
            size_bytes=1024,
            offset=0,
            length=1024,
            content_base64="base64data",
            has_more=False,
        )
        data = result.model_dump()
        assert data["artifact_id"] == "art_001"
        assert data["mime_type"] == "image/png"
        assert data["content_base64"] == "base64data"

    def test_artifact_read_result_extra_forbidden(self):
        """Test that extra fields are forbidden."""
        with pytest.raises(pydantic.ValidationError):
            ArtifactReadResult(
                artifact_id="art_001",
                unknown_field="should fail",
            )
