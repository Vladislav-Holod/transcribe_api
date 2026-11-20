import unittest
from uuid import uuid4

from pydantic import ValidationError

from app.api.schemas import TranscriberCreate, TranscriberSettingsCreate, TranscriptionCreate, TranscriptionTaskCreate


class SchemaTests(unittest.TestCase):
    def test_device_defaults_to_cpu_and_accepts_cuda(self):
        self.assertEqual(TranscriberSettingsCreate().device, "cpu")
        self.assertEqual(TranscriberSettingsCreate(device="cuda").device, "cuda")
        for device in ("gpu", "", None):
            with self.subTest(device=device), self.assertRaises(ValidationError):
                TranscriberSettingsCreate(device=device)

    def test_client_cannot_set_file_uuid_or_audio_path(self):
        for values in (
            {"file_uuid": str(uuid4())},
            {"audio_path": "audio/test.mp3"},
            {"transcriber_id": str(uuid4())},
        ):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                TranscriptionTaskCreate(
                    original_filename="test.mp3", **values,
                )

    def test_invalid_processing_settings_are_rejected(self):
        for values in (
            {"chunk_duration_seconds": 0},
            {"chunk_overlap_seconds": -1},
            {"chunk_overlap_seconds": 20},
            {"batch_size": 0},
            {"chunk_duration_seconds": float("inf")},
        ):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                TranscriberSettingsCreate(**values)

    def test_client_cannot_set_task_status(self):
        with self.assertRaises(ValidationError):
            TranscriptionTaskCreate(
                original_filename="test.mp3",
                status="completed",
            )

    def test_transcriber_and_empty_transcription_are_valid(self):
        transcriber = TranscriberCreate(
            engine="gigaam", model_name="v3_e2e_rnnt", settings_id=uuid4(),
        )
        self.assertEqual(transcriber.engine, "gigaam")
        result = TranscriptionCreate(task_id=uuid4(), text="", duration_seconds=10)
        self.assertEqual(result.text, "")
