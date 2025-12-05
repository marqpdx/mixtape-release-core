# ai/config/constants.py

import os


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.normpath(
    os.path.join(SCRIPT_DIR, "..", "llm_models", "Nous-Hermes-2-Mistral-7B-DPO.Q4_K_M.gguf")
)
DEFAULT_COLLECTION_NAME = "gutenberg25"

INGESTION_STATUS_CHOICES = [
    ("not_started", "Not Started"),
    ("queued", "Queued"),
    ("processing", "Processing"),
    ("complete", "Complete"),
    ("failed", "Failed"),
]

DEFAULT_INGESTION_STATUS = "not_started"


SYNOPSIS_STATUS_CHOICES = [
    ("pending", "Pending"),
    ("generating", "Generating"),
    ("complete", "Complete"),
    ("failed", "Failed"),
]
