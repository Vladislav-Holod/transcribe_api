from pathlib import Path
from typing import BinaryIO
from uuid import UUID

AUDIO_DIR = Path(__file__).resolve().parents[2] / "data" / "audio"

class AudioStorage:
    def __init__(self,directory: Path = AUDIO_DIR):
        self.directory = directory

    def _path(self,file_uuid: UUID) -> Path:
        return self.directory / str(UUID(str(file_uuid)))

    def save(self,file_uuid: UUID,source: BinaryIO) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path(file_uuid)

        destination = path.open('xb')
        try:
            with destination:
                while True:
                    chunk = source.read(1024*1024)
                    if not chunk:
                        break
                    destination.write(chunk)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return path

    def get_path(self, file_uuid: UUID) -> Path:
        path = self._path(file_uuid)
        if not path.is_file():
            raise FileNotFoundError(f"Аудиофайл {file_uuid} не найден")
        return path

    def delete(self,file_uuid: UUID) -> None:
        self._path(file_uuid).unlink(missing_ok=True)