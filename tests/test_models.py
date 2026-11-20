import unittest

from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Base, TaskStatus, Transcriber, TranscriberSettings, Transcription_Text as Transcription, TranscriptionTask


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)

    def test_settings_are_shared_and_result_belongs_to_one_task(self):
        with Session(self.engine) as session:
            settings = TranscriberSettings()
            session.add(settings)
            session.flush()
            transcriber = Transcriber(engine="gigaam", model_name="v3_e2e_rnnt", settings_id=settings.id)
            session.add(transcriber)
            session.flush()
            tasks = [
                TranscriptionTask(
                    transcriber_id=transcriber.id, original_filename=f"{index}.mp3",
                    audio_path=f"audio/{index}.mp3",
                )
                for index in range(2)
            ]
            session.add_all(tasks)
            session.flush()
            self.assertEqual(tasks[0].status, TaskStatus.QUEUED)
            self.assertEqual(settings.chunk_duration_seconds, 20)
            self.assertEqual(tasks[0].attempt_count, 0)
            session.add(Transcription(task_id=tasks[0].id, text="Привет", duration_seconds=5))
            session.commit()
            self.assertEqual(session.get(Transcription, tasks[0].id).text, "Привет")
            self.assertIsNone(session.get(Transcription, tasks[1].id))

            session.add(Transcription(task_id=tasks[0].id, text="Дубль", duration_seconds=5))
            with self.assertRaises(IntegrityError):
                session.commit()

    def test_settings_used_by_task_cannot_be_deleted(self):
        with Session(self.engine) as session:
            settings = TranscriberSettings()
            session.add(settings)
            session.flush()
            transcriber = Transcriber(engine="gigaam", model_name="v3_e2e_rnnt", settings_id=settings.id)
            session.add(transcriber)
            session.flush()
            session.add(TranscriptionTask(
                transcriber_id=transcriber.id, original_filename="test.mp3", audio_path="audio/test.mp3",
            ))
            session.commit()
            session.delete(settings)
            with self.assertRaises(IntegrityError):
                session.commit()

    def test_invalid_overlap_is_rejected_by_database(self):
        with Session(self.engine) as session:
            session.add(TranscriberSettings(chunk_duration_seconds=20, chunk_overlap_seconds=20))
            with self.assertRaises(IntegrityError):
                session.commit()


if __name__ == "__main__":
    unittest.main()
