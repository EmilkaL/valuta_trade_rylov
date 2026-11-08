import os
import tomllib
from pathlib import Path
from threading import Lock

DEFAULT_SETTINGS = {
    "data_dir": "data",
    "logs_dir": "logs",
    "rates_ttl_seconds": 300,
    "base_currency": "USD",
    "log_level": "INFO",
    "log_max_bytes": 1_000_000,
    "log_backup_count": 3,
    "action_log_format": "%(message)s",
    "parser_log_format": "%(asctime)s %(levelname)s %(message)s",
}

DATA_FILES = {
    "users_file": "users.json",
    "portfolios_file": "portfolios.json",
    "rates_file": "rates.json",
    "history_file": "exchange_rates.json",
}


class SettingsLoader:
    _instance = None
    _instance_lock = Lock()

    def __new__(cls):
        with cls._instance_lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance.reload()
                cls._instance = instance
            return cls._instance

    def get(self, key, default=None):
        return self._settings.get(key, default)

    def reload(self):
        settings = DEFAULT_SETTINGS.copy()
        try:
            with Path("pyproject.toml").open("rb") as file:
                project = tomllib.load(file)
        except FileNotFoundError:
            project = {}
        settings.update(project.get("tool", {}).get("valutatrade", {}))

        data_dir = os.getenv("VALUTATRADE_DATA_DIR", settings["data_dir"])
        logs_dir = os.getenv("VALUTATRADE_LOG_DIR", settings["logs_dir"])
        ttl = os.getenv("VALUTATRADE_RATES_TTL_SECONDS", settings["rates_ttl_seconds"])
        settings["data_dir"] = Path(data_dir).expanduser()
        settings["logs_dir"] = Path(logs_dir).expanduser()
        settings["rates_ttl_seconds"] = int(ttl)
        if settings["rates_ttl_seconds"] <= 0:
            raise ValueError("Срок действия кеша должен быть больше нуля.")

        for key, filename in DATA_FILES.items():
            path = settings.get(key, settings["data_dir"] / filename)
            settings[key] = Path(path).expanduser()

        self._settings = settings
