# ai/config/llm_config.py

import logging


logger = logging.getLogger(__name__)

from llama_index.core import Settings as LlamaIndexSettings
from llama_index.llms.llama_cpp import LlamaCPP

from inkwell.config.constants import MODEL_PATH
from inkwell.config.custom_settings import Settings
from inkwell.scripts.utils import (
    llm_setup_once,
    make_chat_llm_from_settings,
    tokenizer_from_llm,
)


@llm_setup_once
def configure_llm(force=False, wait_until_ready=True):
    if Settings.llm is not None and not force:
        if wait_until_ready:
            try:
                logger.info("⏳ [llm] Checking if LLM is ready...")
                # Just trying to ping LLM and wait for the response
                ping_result = Settings.llm.complete("ping")
                logger.info(" [llm] LLM responded with: %s", ping_result.text.strip())
                return Settings.llm
            except Exception as e:
                logger.warning(" [llm] LLM ping failed, retrying init: %s", e)
        else:
            return Settings.llm  # may or may not be ready

    logger.info("🧠 Configuring local LLM...")
    logger.info(" Model path: %s", MODEL_PATH)

    try:
        # init + assign
        Settings.llm = LlamaCPP(
            model_path=MODEL_PATH,
            temperature=0.2,
            max_new_tokens=400,
            context_window=2048,
            model_kwargs={
                "n_gpu_layers": 20,
                "n_batch": 128,
                "f16_kv": True,
                "use_mlock": False,
                "n_threads": 4,
                "verbose": False,
            },
        )

        Settings.chat_llm = make_chat_llm_from_settings(Settings.llm)
        Settings.tokenizer = tokenizer_from_llm(Settings.llm)

        # Sync with LlamaIndex (if using both settings in your pipeline)
        LlamaIndexSettings.llm = Settings.llm
        LlamaIndexSettings.embed_model = Settings.embed_model
        LlamaIndexSettings.tokenizer = Settings.tokenizer

        if wait_until_ready:
                logger.info("⏳ [llm] Waiting for LLM to respond...")
                ping_attempts = 0
                while ping_attempts < 5:  # Retry a few times before failing
                    try:
                        ping_result = Settings.llm.complete("ping")
                        logger.info(" [llm] LLM responded with: %s", ping_result.text.strip())
                        break
                    except Exception as e:
                        ping_attempts += 1
                        logger.warning(" [llm] LLM ping attempt {ping_attempts} failed: %s", e)
                        if ping_attempts == 5:
                            logger.info("❌ [llm] Max ping attempts reached. LLM not ready.")
                            raise e
                        logger.info("⏳ [llm] Retrying...")

        logger.info("✅ Local LLM configured.")
        return Settings.llm

    except Exception as e:
        logger.error(" Failed to configure LLM: %s", e)
        Settings.llm = None
        return None


