from __future__ import annotations

import abc
from typing import Any

from langbot_plugin.api.definition.components.base import PolymorphicComponent
from langbot_plugin.api.entities.builtin.rag.context import (
    RetrievalContext,
    RetrievalResultEntry,
    RetrievalResponse,
)
from langbot_plugin.api.entities.builtin.rag.models import (
    IngestionContext,
    IngestionResult,
)


class KnowledgeRetriever(PolymorphicComponent):
    """The knowledge retriever component.
    
    This is the legacy interface for knowledge retrieval.
    For new implementations, use RAGEngine instead.
    """

    __kind__ = "KnowledgeRetriever"

    @abc.abstractmethod
    async def retrieve(self, context: RetrievalContext) -> list[RetrievalResultEntry]:
        """Retrieve the data from the knowledge retriever.
        
        Args:
            context: The retrieval context.
            
        Returns:
            The retrieval result.
            The retrieval result is a list of RetrievalResultEntry.
            The RetrievalResultEntry contains the id, metadata, and distance of the retrieved data.
        """
        pass


class RAGEngine(PolymorphicComponent):
    """Complete RAG engine component with full lifecycle management.
    
    This component provides comprehensive RAG operations including document ingestion,
    deletion, and retrieval. It replaces the legacy KnowledgeRetriever with a more
    complete interface.
    
    Plugins implementing this component should use `self.plugin.rag_*` methods
    to access Host capabilities.
    """

    __kind__ = "RAGEngine"

    # ========== Lifecycle Hooks ==========

    async def on_knowledge_base_create(self, kb_id: str, config: dict) -> None:
        """Called when a knowledge base using this engine is created.
        
        Args:
            kb_id: The knowledge base identifier.
            config: Creation settings provided by the user.
        """
        pass

    async def on_knowledge_base_delete(self, kb_id: str) -> None:
        """Called when a knowledge base using this engine is deleted.
        
        Args:
            kb_id: The knowledge base identifier.
        """
        pass

    # ========== Core Methods ==========

    @abc.abstractmethod
    async def ingest(self, context: IngestionContext) -> IngestionResult:
        """Ingest a document into the knowledge base.
        
        This method should:
        1. Read the file using `await self.plugin.rag_get_file_content(context.file_object.storage_path)`
        2. Parse and chunk the content
        3. Embed using `await self.plugin.rag_embed_documents(context.knowledge_base_id, chunks)`
        4. Store using `await self.plugin.rag_vector_upsert(kb_id, ...)`
        
        Args:
            context: Ingestion context containing file info and settings.
            
        Returns:
            Ingestion result with status and metadata.
        """
        pass

    @abc.abstractmethod
    async def delete_document(self, kb_id: str, document_id: str) -> bool:
        """Delete a document and its associated data from the knowledge base.
        
        Use `await self.plugin.rag_vector_delete(...)` to clean up vectors.
        
        Args:
            kb_id: Knowledge base identifier.
            document_id: Document identifier to delete.
            
        Returns:
            True if deletion was successful.
        """
        pass

    @abc.abstractmethod
    async def retrieve(self, context: RetrievalContext) -> RetrievalResponse:
        """Retrieve relevant content from the knowledge base.
        
        This method should:
        1. Embed query using `await self.plugin.rag_embed_query(context.knowledge_base_id, query)`
        2. Search using `await self.plugin.rag_vector_search(kb_id, ...)`
        3. Return structured response
        
        Args:
            context: Retrieval context with query and settings.
            
        Returns:
            Structured retrieval response.
        """
        pass

    # ========== Schema Definitions ==========

    @abc.abstractmethod
    def get_creation_settings_schema(self) -> dict:
        """Get JSON Schema for knowledge base creation settings.
        
        Returns:
            JSON Schema dict for creation settings.
        """
        pass

    @abc.abstractmethod
    def get_retrieval_settings_schema(self) -> dict:
        """Get JSON Schema for retrieval runtime settings.
        
        Returns:
            JSON Schema dict for retrieval settings.
        """
        pass
