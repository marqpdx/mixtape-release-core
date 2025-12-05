# inkwell/scripts/utils.py

import logging


logger = logging.getLogger(__name__)

import functools
import os
import threading
from collections.abc import Callable
from functools import wraps
from typing import List

# from inkwell.config.ai_config import collection_name, retriever
from uuid import UUID

from django.conf import settings
from filelock import FileLock
from langchain_community.chat_models import ChatLlamaCpp
from qdrant_client import QdrantClient

from inkwell.config.custom_settings import Settings
from inkwell.models import LLMSession
from inkwell.scripts.storage import load_or_create_index
from inkwell.utils.startup_locks import LOCK_DIR


def run_once_in_main_process(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if (
            os.environ.get("RUN_AI_STARTUP") == "1"
            and os.environ.get("RUN_MAIN") == "true"
        ):
            return func(*args, **kwargs)
        logger.info("Skipping {func.__name__}: Not in main process or startup not enabled.")
    return wrapper


_run_once_registry = {}
_registry_lock = threading.Lock()

def run_once_globally(key: str):
    def decorator(func):
        def wrapper(*args, **kwargs):
            with _registry_lock:
                if _run_once_registry.get(key):
                    return None
                _run_once_registry[key] = True
            return func(*args, **kwargs)
        return wrapper
    return decorator





LLM_LOCK_DIR = "/tmp"
LLM_LOCK_FILE = os.path.join(LOCK_DIR, "llm_config.lock")

def llm_setup_once(func):
    """
    Decorator that ensures the LLM setup function runs only once across multiple processes.
    It uses a file lock to synchronize the process.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        # Acquire file-based lock for LLM setup
        lock = FileLock(LLM_LOCK_FILE)

        try:
            with lock:
                # Ensure the LLM is only initialized once
                logger.info("[llm] Attempting to acquire lock for LLM setup: {LLM_LOCK_FILE}")

                # Execute the LLM setup function
                return func(*args, **kwargs)

        finally:
            # Ensure the lock file is removed after the task completes
            if os.path.exists(LLM_LOCK_FILE):
                os.remove(LLM_LOCK_FILE)
                logger.info("[llm]  Lock released and lock file removed: %s", LLM_LOCK_FILE)

    return wrapper


def check_rag_status():
    status = {
        "embed_model": None,
        "retriever_ready": False,
        "num_indexed_chunks": 0,
        "qdrant_collections": [],
    }

    try:
        # Embedding model
        embed_model = getattr(Settings, "embed_model", None)
        status["embed_model"] = embed_model.__class__.__name__ if embed_model else None

        # TODO fix these
        # Retriever
        # status["retriever_ready"] = retriever is not None

        # Index / nodes
        # index = get_index(collection_name)
        # status["num_indexed_chunks"] = len(index.docstore.docs) if index else 0

        # Qdrant
        qdrant = QdrantClient(settings.QDRANT_URL)
        collections = qdrant.get_collections().collections
        status["qdrant_collections"] = [c.name for c in collections]

    except Exception as e:
        status["error"] = str(e)

    return status

_index_cache = {}

def get_index(collection_name: str):
    logger.info(" Loading index for collection: %s", collection_name)

    if collection_name not in _index_cache:
        logger.info("🔄 Index not found in cache, creating new one for {collection_name}")
        _index_cache[collection_name] = load_or_create_index(collection_name)
    return _index_cache[collection_name]

def get_or_create_session(session_id: str = None) -> LLMSession:
    """
    Load a LLMSession by UUID, or create a new one if not found or invalid.

    Args:
        session_id (str): Optional UUID string.

    Returns:
        LLMSession: An existing or new LLMSession instance.
    """
    if session_id:
        try:
            return LLMSession.objects.get(session_id=UUID(session_id))
        except (LLMSession.DoesNotExist, ValueError):
            pass  # Fall through to create a new session

    return LLMSession.objects.create()


# move these below to # ai/config/llm_utils.py

def make_chat_llm_from_settings(llm=None):
    llm = llm or Settings.llm
    return ChatLlamaCpp(
        model_path=llm.model_path,
        temperature=llm.temperature,
        max_new_tokens=llm.max_new_tokens,
        context_window=llm.context_window,
        model_kwargs=llm.model_kwargs,
        verbose=True,
    )


def tokenizer_from_llm(llm) -> Callable[[str], list[str]]:
    def tokenize(text: str) -> list[str]:
        # Very basic fallback tokenizer
        return text.strip().split()

    # If your LLM exposes a tokenizer (e.g., huggingface or llama-cpp-python with bindings), use it
    if hasattr(llm, "tokenize"):
        return lambda text: llm.tokenize(text)

    # Otherwise, return fallback
    return tokenize
