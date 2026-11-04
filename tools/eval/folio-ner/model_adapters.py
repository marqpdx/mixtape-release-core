"""Laptop-only M2 adapters. Imports model libraries only on construction.

No package installation, network, Django, canonical Sightings or content writes.
"""
from pathlib import Path
import json
import os
import time

from adapter import recognize, validate_request, validate_response

GLINER_REVISION = "4e091416cf7c3481db542c2a3d26156916f3a47f"
SPACY_MODEL_VERSION = "3.8.0"
LABELS = {"character": "writing.character", "setting": "writing.setting", "scene": "writing.scene"}
SPACY_LABELS = {"PERSON": "writing.character", "GPE": "writing.setting", "LOC": "writing.setting", "FAC": "writing.setting"}
THRESHOLD = 0.5


class LocalModels:
    def __init__(self, backend, model_root):
        os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1", TOKENIZERS_PARALLELISM="false")
        self.backend = backend
        root = Path(model_root)
        start = time.perf_counter()
        if backend == "spacy":
            import spacy
            self.model = spacy.load("en_core_web_sm")
            if self.model.meta["version"] != SPACY_MODEL_VERSION:
                raise ValueError("Unexpected spaCy pipeline version")
            self.producer = {"kind": "model", "id": "spacy/en_core_web_sm", "version": spacy.__version__,
                "model_revision": SPACY_MODEL_VERSION}
        elif backend == "gliner":
            import torch
            import gliner
            from importlib.metadata import version
            torch.manual_seed(0)
            torch.set_num_threads(2)
            self.torch = torch
            self.model = gliner.GLiNER.from_pretrained(str(root / "runtime"), local_files_only=True,
                strict=True, map_location="cpu")
            self.model.eval()
            self.producer = {"kind": "model", "id": "urchade/gliner_small-v2.1", "version": version("gliner"),
                "model_revision": GLINER_REVISION}
        else:
            raise ValueError("Unknown local model backend")
        self.load_seconds = time.perf_counter() - start

    def entities(self, text):
        if self.backend == "spacy":
            return [{"start": e.start_char, "end": e.end_char, "label": e.label_, "score": None}
                    for e in self.model(text).ents if e.label_ in SPACY_LABELS]
        if len(text) > 4000:
            raise ValueError("Evaluation input too long; no silent chunking")
        with self.torch.inference_mode():
            return self.model.predict_entities(text, list(LABELS), threshold=THRESHOLD, flat_ner=False)

    def recognize(self, request):
        validate_request(request)
        result = recognize(request)  # Unchanged deterministic cue baseline.
        source = request["source"]
        raw = self.entities(source["text"])
        mapping = SPACY_LABELS if self.backend == "spacy" else LABELS
        for index, entity in enumerate(raw):
            start, end = entity["start"], entity["end"]
            if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(source["text"]):
                raise ValueError("Invalid model span")
            if "text" in entity and entity["text"] != source["text"][start:end]:
                raise ValueError("Model changed source text")
            result["candidates"].append({"candidate_id": f"{self.backend}-mention-{index+1}",
                "candidate_kind": "mention", "type": mapping[entity["label"]],
                "source_locator": {"source_ref": source["source_ref"], "source_revision": source["source_revision"],
                    "start": start, "end": end, "quote": source["text"][start:end]},
                "score": entity["score"], "negated": False, "ambiguous": True,
                "uncertain": ["Provisional NER label; no Fiction judgement or confirmation."] if self.backend == "gliner"
                    else ["Generic PERSON/place label mapping; not Fiction interpretation."],
                "producer": self.producer})
        validate_response(request, result)
        return result, raw
