"""SE-0: deterministic local-only boundary tests; no DB, models or network."""

import ast
import builtins
import math
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from concord.services import interpretation, whisper
from concord.services.errors import CloudAIDisabledError
from concord.tasks.interpretation import interpret_recording_task
from concord.tasks.transcription import transcribe_recording_task


@override_settings(OPENAI_API_KEY="synthetic-unused-key")
class LocalOnlyServicesTests(SimpleTestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "OPENAI_API_KEY": "synthetic-unused-key", "WHISPER_BACKEND": "",
            "WHISPER_MODEL_SIZE": "", "WHISPER_DEVICE": "", "WHISPER_COMPUTE_TYPE": "",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.provider = MagicMock()
        self.provider_modules = patch.dict(sys.modules, {"openai": self.provider})
        self.provider_modules.start()
        self.addCleanup(self.provider_modules.stop)

    def tearDown(self):
        self.provider.OpenAI.assert_not_called()

    def test_cloud_override_aliases_are_denied_before_local_loading(self):
        for alias in ("openai-api", "openai_api", "openai", "OPENAI"):
            with self.subTest(alias=alias), patch.dict(os.environ, {"WHISPER_BACKEND": alias}):
                service = whisper.WhisperService()
                with patch.object(service, "_load_faster_whisper") as load:
                    with self.assertRaises(CloudAIDisabledError) as raised:
                        service.transcribe("unused.wav")
                    self.assertEqual(raised.exception.code, "cloud_ai_disabled")
                    load.assert_not_called()
                with patch.object(whisper.os.path, "exists", return_value=True):
                    with self.assertRaises(CloudAIDisabledError):
                        whisper.transcribe_audio("unused.wav")

    def test_auto_selection_is_local_even_with_provider_available(self):
        with patch.dict(sys.modules, {"faster_whisper": None, "whisper": MagicMock()}):
            self.assertEqual(whisper.WhisperService()._detect_backend(), "whisper")
        with patch.dict(sys.modules, {"faster_whisper": MagicMock(), "whisper": MagicMock()}):
            self.assertEqual(whisper.WhisperService()._detect_backend(), "faster-whisper")

    def test_missing_local_backends_never_import_provider(self):
        original_import = builtins.__import__

        def guarded_import(name, *args, **kwargs):
            if name == "openai":
                self.fail("Local backend discovery must not import a provider SDK")
            return original_import(name, *args, **kwargs)

        with patch.dict(sys.modules, {"faster_whisper": None, "whisper": None}):
            with patch("builtins.__import__", side_effect=guarded_import):
                with self.assertRaisesRegex(ImportError, "No local Whisper backend"):
                    whisper.WhisperService().transcribe("unused.wav")
                with patch.object(whisper.os.path, "exists", return_value=True):
                    with self.assertRaisesRegex(ImportError, "No local Whisper backend"):
                        whisper.transcribe_audio("unused.wav")

    def test_local_override_aliases_are_preserved(self):
        for alias, expected in (
            ("faster-whisper", "faster-whisper"), ("faster_whisper", "faster-whisper"),
            ("faster", "faster-whisper"), ("whisper", "whisper"),
            ("openai-whisper", "whisper"), ("openai_whisper", "whisper"),
        ):
            with self.subTest(alias=alias), patch.dict(os.environ, {"WHISPER_BACKEND": alias}):
                self.assertEqual(whisper.WhisperService()._detect_backend(), expected)

    def test_local_loading_and_inference_failures_do_not_change_backend(self):
        with patch.dict(os.environ, {"WHISPER_BACKEND": "faster"}):
            service = whisper.WhisperService()
            with patch.object(service, "_load_faster_whisper", side_effect=RuntimeError("load failed")):
                with self.assertRaisesRegex(RuntimeError, "load failed"):
                    service.transcribe("unused.wav")
            service._model = MagicMock()
            service._model.transcribe.side_effect = RuntimeError("inference failed")
            with self.assertRaisesRegex(RuntimeError, "inference failed"):
                service.transcribe("unused.wav")
            self.assertEqual(service._backend, "faster-whisper")

    def test_faster_whisper_result_and_options_are_preserved(self):
        model_class = MagicMock()
        segment = SimpleNamespace(start=0.125, end=1.75, text=" Synthetic words. ", avg_logprob=-0.5)
        model_class.return_value.transcribe.return_value = (
            iter([segment]), SimpleNamespace(language="en", duration=2.25),
        )
        module = SimpleNamespace(WhisperModel=model_class)
        with patch.dict(sys.modules, {"faster_whisper": module}):
            with patch.object(whisper, "_detect_device", return_value="cpu"):
                with patch.object(whisper.os.path, "exists", return_value=True):
                    result = whisper.transcribe_audio("synthetic.wav", language="en")
        model_class.assert_called_once_with("base", device="cpu", compute_type="auto")
        model_class.return_value.transcribe.assert_called_once_with(
            "synthetic.wav", language="en", word_timestamps=False, vad_filter=False,
        )
        self.assertEqual((result.text, result.language, result.model_name, result.backend),
                         ("Synthetic words.", "en", "base", "faster-whisper"))
        self.assertEqual((result.duration_ms, result.segments[0].start_ms, result.segments[0].end_ms),
                         (2250, 125, 1750))
        self.assertAlmostEqual(result.confidence_avg, math.exp(-0.5))

    def test_local_whisper_result_and_options_are_preserved(self):
        local = MagicMock()
        local.load_model.return_value.transcribe.return_value = {
            "text": "Synthetic words.", "language": "fr",
            "segments": [{"start": 0.25, "end": 1.5, "text": " Synthetic words. "}],
        }
        with patch.dict(os.environ, {"WHISPER_BACKEND": "whisper"}):
            with patch.dict(sys.modules, {"whisper": local}):
                service = whisper.WhisperService(model_name="base", device="cpu")
                result = service.transcribe("synthetic.wav", language="fr", word_timestamps=True)
        local.load_model.assert_called_once_with("base", device="cpu")
        local.load_model.return_value.transcribe.assert_called_once_with(
            "synthetic.wav", language="fr", word_timestamps=True,
        )
        self.assertEqual((result.text, result.language, result.backend), ("Synthetic words.", "fr", "whisper"))
        self.assertEqual((result.segments[0].start_ms, result.segments[0].end_ms), (250, 1500))
        self.assertEqual(result.segments[0].text, "Synthetic words.")

    def test_storage_wrapper_cleans_temporary_audio_after_denial(self):
        from io import BytesIO

        tempfile.gettempdir()  # Resolve tempfile's directory probe before tracking cleanup.
        with patch.dict(os.environ, {"WHISPER_BACKEND": "openai"}):
            with patch.object(whisper, "default_storage") as storage:
                storage.exists.return_value = True
                storage.open.return_value = BytesIO(b"synthetic audio")
                with patch.object(whisper.os, "unlink", wraps=os.unlink) as unlink:
                    with self.assertRaises(CloudAIDisabledError):
                        whisper.transcribe_audio("recordings/synthetic.wav")
                    unlink.assert_called_once()
                    self.assertFalse(Path(unlink.call_args.args[0]).exists())

    def test_extractive_defaults_and_empty_result_are_preserved(self):
        text = "This is the first synthetic sentence. This is the second synthetic sentence."
        expected = interpretation.InterpretationResult(
            summary=text, key_points=["This is the first synthetic sentence.", "This is the second synthetic sentence."],
            word_count=12, method="extractive",
        )
        for service in (interpretation.InterpretationService(), interpretation.InterpretationService(use_llm=False)):
            self.assertEqual(service.interpret(text), expected)
        self.assertEqual(interpretation.interpret_transcription(text), expected)
        self.assertEqual(interpretation.interpret_transcription("  "),
                         interpretation.InterpretationResult("", [], 0, "none"))
        short = interpretation.interpret_transcription(text, max_summary_length=40)
        self.assertEqual(short.summary, "This is the first synthetic sentence.")

    def test_explicit_cloud_interpretation_is_denied_in_service_and_wrappers(self):
        with self.assertRaises(CloudAIDisabledError):
            interpretation.InterpretationService(use_llm=True)
        for text in ("Synthetic content.", ""):
            with self.assertRaises(CloudAIDisabledError):
                interpretation.interpret_transcription(text, use_llm=True)
        with patch("concord.models.Recording.objects.get") as get:
            get.return_value.transcriptions.order_by.return_value.first.return_value.text = "Synthetic content."
            with self.assertRaises(CloudAIDisabledError):
                interpretation.interpret_recording("synthetic-id", use_llm=True)

    def test_recording_transcription_wrapper_preserves_denial(self):
        with patch("concord.models.Recording.objects.get") as get:
            get.return_value.audio_path = "synthetic.wav"
            with patch.dict(os.environ, {"WHISPER_BACKEND": "openai"}):
                with patch.object(whisper.os.path, "exists", return_value=True):
                    with self.assertRaises(CloudAIDisabledError):
                        whisper.transcribe_recording("synthetic-id")

    def test_concord_tasks_report_denial_without_retry_or_success(self):
        for task, module, service in (
            (interpret_recording_task, "interpretation", "interpret_recording"),
            (transcribe_recording_task, "transcription", "transcribe_recording"),
        ):
            with self.subTest(task=module), patch("concord.models.Recording.objects.get") as get:
                from concord.models import RecordingStatus
                recording = get.return_value
                recording.status = RecordingStatus.INTERPRETING if module == "interpretation" else RecordingStatus.UPLOADED
                with patch(f"concord.services.{ 'interpretation' if module == 'interpretation' else 'whisper'}.{service}",
                           side_effect=CloudAIDisabledError("Direct cloud AI is disabled")):
                    with patch.object(task, "retry") as retry:
                        result = task.run(recording_id="synthetic-id")
                self.assertEqual(result["status"], "error")
                self.assertEqual(result["error_code"], "cloud_ai_disabled")
                self.assertEqual(recording.status, RecordingStatus.FAILED)
                self.assertEqual(recording.processing_error, "Direct cloud AI is disabled")
                retry.assert_not_called()

    def test_provider_imports_cannot_return_to_these_services(self):
        # Check all import forms, including aliases, in both owned modules.
        for module in (whisper, interpretation):
            tree = ast.parse(Path(module.__file__).read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                else:
                    continue
                self.assertFalse(any(name.split(".")[0] in {"openai", "anthropic"} for name in names),
                                 f"Direct provider import in {module.__name__}")
