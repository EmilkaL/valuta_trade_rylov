import json
import os
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock, RLock

from valutatrade_hub.infra.settings import SettingsLoader

if os.name == "nt":
    import msvcrt
else:
    import fcntl


def _lock_file(file):
    if os.name == "nt":
        file.seek(0)
        msvcrt.locking(file.fileno(), msvcrt.LK_LOCK, 1)
    else:
        fcntl.flock(file, fcntl.LOCK_EX)


class DatabaseManager:
    _instance = None
    _instance_lock = Lock()

    def __new__(cls):
        with cls._instance_lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance._thread_lock = RLock()
                instance._file_locked = False
                cls._instance = instance
            return cls._instance

    @property
    @contextmanager
    def lock(self):
        with self._thread_lock:
            if self._file_locked:
                yield
                return

            data_dir = SettingsLoader().get("data_dir")
            data_dir.mkdir(parents=True, exist_ok=True)
            with (data_dir / ".lock").open("a+b") as lock_file:
                _lock_file(lock_file)
                self._file_locked = True
                try:
                    yield
                finally:
                    self._file_locked = False

    def read_json(self, path, default):
        with self.lock:
            try:
                with Path(path).open(encoding="utf-8") as file:
                    return json.load(file)
            except FileNotFoundError:
                return default

    def write_json(self, path, data):
        path = Path(path)
        temporary_path = None
        with self.lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=path.parent,
                    prefix=f".{path.name}.",
                    suffix=".tmp",
                    delete=False,
                ) as file:
                    temporary_path = Path(file.name)
                    json.dump(data, file, ensure_ascii=False, indent=2, allow_nan=False)
                    file.write("\n")
                temporary_path.replace(path)
            finally:
                if temporary_path is not None:
                    temporary_path.unlink(missing_ok=True)
