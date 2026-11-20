import unittest
from uuid import uuid4

from pydantic import ValidationError

from app.api.schemas import TranscriberCreate, TranscriberSettingsCreate, TranscriptionCreate, TranscriptionTaskCreate


class SchemaTests(unittest.TestCase):
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
                transcriber_id=uuid4(), original_filename="test.mp3",
                audio_path="audio/test.mp3", status="completed",
            )

    def test_transcriber_and_empty_transcription_are_valid(self):
        transcriber = TranscriberCreate(
            engine="gigaam", model_name="v3_e2e_rnnt", settings_id=uuid4(),
        )
        self.assertEqual(transcriber.engine, "gigaam")
        result = TranscriptionCreate(task_id=uuid4(), text="", duration_seconds=10)
        self.assertEqual(result.text, "")
