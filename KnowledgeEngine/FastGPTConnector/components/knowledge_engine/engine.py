from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from langbot_plugin.api.definition.components.knowledge_engine import KnowledgeEngine, KnowledgeEngineCapability
from langbot_plugin.api.entities.builtin.rag import (
    IngestionContext,
    IngestionResult,
    DocumentStatus,
    RetrievalContext,
    RetrievalResultEntry,
    RetrievalResponse,
)
from langbot_plugin.api.entities.builtin.provider.message import ContentElement

logger = logging.getLogger(__name__)


class FastGPTConnector(KnowledgeEngine):
    """Knowledge Engine powered by FastGPT Datasets.

    Supports retrieval via FastGPT's search API, document ingestion by
    uploading files to FastGPT datasets, and document deletion by removing
    collections.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Cache of per-knowledge-base config for use in delete_document,
        # keyed by kb_id.
        self._kb_configs: dict[str, dict[str, Any]] = {}

    @classmethod
    def get_capabilities(cls) -> list[str]:
        return [KnowledgeEngineCapability.DOC_INGESTION, KnowledgeEngineCapability.DOC_PARSING]

    # ========== Lifecycle Hooks ==========

    async def on_knowledge_base_create(self, kb_id: str, config: dict) -> None:
        """Cache knowledge-base config so delete_document can look it up."""
        logger.info(f"[FastGPTKnowledgeEngine] Knowledge base created: {kb_id}")
        self._kb_configs[kb_id] = config

    async def on_knowledge_base_delete(self, kb_id: str) -> None:
        """Remove cached config when a knowledge base is deleted."""
        logger.info(f"[FastGPTKnowledgeEngine] Knowledge base deleted: {kb_id}")
        self._kb_configs.pop(kb_id, None)

    async def retrieve(self, context: RetrievalContext) -> RetrievalResponse:
        """Execute retrieval against FastGPT Dataset API."""
        config = context.creation_settings

        api_base_url = config.get("api_base_url", "http://localhost:3000").rstrip("/")
        api_key = config.get("api_key")
        dataset_id = config.get("dataset_id")
        limit = config.get("limit", 5000)
        similarity = config.get("similarity", 0.0)
        search_mode = config.get("search_mode", "embedding")
        using_rerank = config.get("using_rerank", False)
        dataset_search_using_extension_query = config.get("dataset_search_using_extension_query", False)
        dataset_search_extension_model = config.get("dataset_search_extension_model", "")
        dataset_search_extension_bg = config.get("dataset_search_extension_bg", "")

        if not api_key or not dataset_id:
            logger.error(
                f"[FastGPTKnowledgeEngine] Missing required configuration. "
                f"Config keys: {list(config.keys())}"
            )
            return RetrievalResponse(results=[], total_found=0)

        url = f"{api_base_url}/api/core/dataset/searchTest"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "datasetId": dataset_id,
            "text": context.query,
            "limit": int(limit),
            "similarity": float(similarity),
            "searchMode": search_mode,
            "usingReRank": bool(using_rerank),
        }

        if dataset_search_using_extension_query:
            payload["datasetSearchUsingExtensionQuery"] = True
            if dataset_search_extension_model:
                payload["datasetSearchExtensionModel"] = dataset_search_extension_model
            if dataset_search_extension_bg:
                payload["datasetSearchExtensionBg"] = dataset_search_extension_bg

        results: list[RetrievalResultEntry] = []
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, headers=headers, timeout=30.0)
                response.raise_for_status()
                result = response.json()

                for record in result.get("data", []):
                    content_parts = []
                    if record.get("q"):
                        content_parts.append(record["q"])
                    if record.get("a"):
                        content_parts.append(record["a"])
                    content_text = "\n".join(content_parts) if content_parts else ""

                    score = record.get("score")
                    if score is None:
                        score = 0.0

                    results.append(
                        RetrievalResultEntry(
                            id=record.get("id", ""),
                            content=[ContentElement.from_text(content_text)],
                            metadata={
                                "dataset_id": record.get("datasetId", ""),
                                "collection_id": record.get("collectionId", ""),
                                "source_name": record.get("sourceName", ""),
                                "source_id": record.get("sourceId", ""),
                            },
                            distance=1.0 - float(score),
                            score=float(score),
                        )
                    )

            logger.info(f"[FastGPTKnowledgeEngine] Retrieved {len(results)} chunks from FastGPT.")
        except Exception:
            logger.exception("[FastGPTKnowledgeEngine] Error during retrieval")

        return RetrievalResponse(results=results, total_found=len(results))

    async def ingest(self, context: IngestionContext) -> IngestionResult:
        """Upload a file to FastGPT dataset as a new collection."""
        doc_id = context.file_object.metadata.document_id
        filename = context.file_object.metadata.filename

        config = context.creation_settings
        api_base_url = config.get("api_base_url", "http://localhost:3000").rstrip("/")
        api_key = config.get("api_key")
        dataset_id = config.get("dataset_id")

        if not api_key or not dataset_id:
            logger.error(
                f"[FastGPTKnowledgeEngine] Missing required configuration for ingestion. "
                f"Config keys: {list(config.keys())}"
            )
            return IngestionResult(
                document_id=doc_id,
                status=DocumentStatus.FAILED,
                error_message="Missing api_key or dataset_id in configuration.",
            )

        # 1. Read file content from Host
        try:
            file_bytes = await self.plugin.get_knowledge_file_stream(context.file_object.storage_path)
        except Exception as e:
            logger.error(f"[FastGPTKnowledgeEngine] Failed to read file: {e}")
            return IngestionResult(
                document_id=doc_id,
                status=DocumentStatus.FAILED,
                error_message=f"Could not read file: {e}",
            )

        # 2. Upload file to FastGPT dataset
        url = f"{api_base_url}/api/core/dataset/collection/create/localFile"
        headers = {
            "Authorization": f"Bearer {api_key}",
        }
        data_json = json.dumps({
            "datasetId": dataset_id,
            "trainingType": "chunk",
            "chunkSettingMode": "auto",
            "chunkSize": 512,
        })

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    headers=headers,
                    files={"file": (filename, file_bytes)},
                    data={"data": data_json},
                    timeout=120.0,
                )
                response.raise_for_status()
                result = response.json()

            if result.get("code") != 200:
                error_msg = result.get("message", "Unknown error from FastGPT")
                logger.error(f"[FastGPTKnowledgeEngine] Upload failed: {error_msg}")
                return IngestionResult(
                    document_id=doc_id,
                    status=DocumentStatus.FAILED,
                    error_message=error_msg,
                )

            resp_data = result.get("data", {})
            collection_id = resp_data.get("collectionId", "")
            insert_len = resp_data.get("results", {}).get("insertLen", 0)

            logger.info(
                f"[FastGPTKnowledgeEngine] File uploaded: {filename} -> "
                f"collectionId={collection_id}, insertLen={insert_len}"
            )

            return IngestionResult(
                document_id=collection_id,
                status=DocumentStatus.PROCESSING,
                chunks_created=insert_len,
            )

        except Exception as e:
            logger.error(f"[FastGPTKnowledgeEngine] Ingestion failed for {filename}: {e}")
            return IngestionResult(
                document_id=doc_id,
                status=DocumentStatus.FAILED,
                error_message=str(e),
            )

    async def delete_document(self, kb_id: str, document_id: str) -> bool:
        """Delete a collection from FastGPT dataset."""
        config = self._kb_configs.get(kb_id)
        if not config:
            logger.error(
                f"[FastGPTKnowledgeEngine] No cached config for kb_id={kb_id}. "
                "Cannot delete document."
            )
            return False

        api_base_url = config.get("api_base_url", "http://localhost:3000").rstrip("/")
        api_key = config.get("api_key")

        if not api_key:
            logger.error("[FastGPTKnowledgeEngine] Missing api_key in cached config.")
            return False

        url = f"{api_base_url}/api/core/dataset/collection/delete"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {"collectionId": document_id}

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url, json=payload, headers=headers, timeout=30.0
                )
                response.raise_for_status()
                result = response.json()

            if result.get("code") != 200:
                logger.error(
                    f"[FastGPTKnowledgeEngine] Delete failed for collection={document_id}: "
                    f"{result.get('message', 'Unknown error')}"
                )
                return False

            logger.info(
                f"[FastGPTKnowledgeEngine] Collection deleted: {document_id}"
            )
            return True

        except Exception:
            logger.exception(
                f"[FastGPTKnowledgeEngine] Error deleting collection={document_id}"
            )
            return False
