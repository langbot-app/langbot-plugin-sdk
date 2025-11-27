from __future__ import annotations

import abc
from typing import Any

from langbot_plugin.api.definition.components.base import PolymorphicComponent
from langbot_plugin.api.entities.builtin.rag.context import RetrievalContext, RetrievalResultEntry


class KnowledgeRetriever(PolymorphicComponent):
    """The knowledge retriever component."""

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
