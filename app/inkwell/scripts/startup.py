# inkwell/scripts/startup.py

import logging


logger = logging.getLogger(__name__)

import os
import time

from django.utils import timezone

# from inkwell.config import collection_name
from inkwell.config.ai_config import collection_name
from inkwell.config.custom_settings import Settings
from inkwell.config.llm_config import configure_llm
from inkwell.utils.startup_locks import run_once_globally_filelock


startup_finished = False

# @run_once_globally("startup:indexing")
@run_once_globally_filelock("startup_indexing")
def run_startup_tasks(force=False):
    from llama_index.core import Settings as LlamaIndexSettings

    from inkwell.config.ai_config import configure_embedding, configure_rag
    from inkwell.config.custom_settings import Settings
    from inkwell.models import StartupLog
    from inkwell.scripts.documents_pg import ingest_documents
    from inkwell.scripts.storage import load_or_create_index
    from inkwell.scripts.utils import make_chat_llm_from_settings, tokenizer_from_llm
    log = StartupLog.objects.create(key="startup_indexing")
    try:
        global startup_finished

        logger.info("Running startup...")

        doc_path = "./ai/ebooks" if collection_name == "gutenberg25" else "./ai/files"

        configure_llm()

        Settings.chat_llm = make_chat_llm_from_settings(Settings.llm)
        Settings.tokenizer = tokenizer_from_llm(Settings.llm)
        # Sync with LlamaIndex
        LlamaIndexSettings.llm = Settings.llm
        LlamaIndexSettings.embed_model = Settings.embed_model
        LlamaIndexSettings.tokenizer = Settings.tokenizer

        logger.info("✅ STARTUP LLM CONFIG DONE")

        configure_embedding()
        logger.info("after configure_embedding")

        index = load_or_create_index(collection_name)
        logger.info("index in hand")

        configure_rag(index, collection_name)

        ingest_documents(index, doc_path, collection_name)

        warm_up_llm()

        startup_finished = True
        logger.info("---STARTUP TASKS COMPLETED---")

    except Exception as e:
        log.status = "error"
        log.completed_at = timezone.now()
        log.message = str(e)
        log.save()
        raise


def warm_up_llm():
    if not Settings.llm:
        logger.warning("LLM not configured, skipping warm-up")
        return

    try:
        logger.info("Warming up LLM with minimal dummy prompt...")

        # Step 1: Flush cache context with a short completion
        start = time.time()
        Settings.llm.complete(
            prompt="ignore this.",
            max_tokens=1,
            temperature=0.0,
            stop=["\n", ".", "!", ":"]
        )
        duration = time.time() - start
        logger.info("LLM warm-up flush phase complete in %.2f seconds", duration)

        # Step 2: Real warm-up with clean prompt
        start = time.time()
        response = Settings.llm.complete(
            prompt="Say hello:",
            max_tokens=4,
            temperature=0.0,
            stop=["\n", ".", "!", ":"]
        )
        duration = time.time() - start
        logger.info("LLM warm-up complete in %.2f seconds: %s", duration, response.text.strip())

    except Exception as e:
        logger.warning("Warm-up failed: %s", e)

