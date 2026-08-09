"""Composition root.

This is the single place that decides *which* store implementation the app runs
against. Pointing the dashboard at Cosmos DB or Azure SQL later is a change to
`get_store` and nothing else.
"""

from __future__ import annotations

from functools import lru_cache

from .chat import ChatEngine
from .config import Settings, get_settings
from .store import JsonWorkflowStore, WorkflowStore


@lru_cache
def get_store() -> WorkflowStore:
    settings: Settings = get_settings()
    return JsonWorkflowStore(settings.data_path)


@lru_cache
def get_chat_engine() -> ChatEngine:
    return ChatEngine(get_store(), get_settings())
