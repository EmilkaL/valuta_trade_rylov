from datetime import UTC, datetime

from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.parser_service.config import ParserConfig


def utc_timestamp():
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value):
    try:
        timestamp = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=UTC)
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=UTC)
    return timestamp


class RatesStorage:
    def __init__(self, config: ParserConfig | None = None):
        self.config = config if config is not None else ParserConfig()
        self.database = DatabaseManager()

    def save(self, entries, refreshed_at):
        rates_path = self.config.RATES_FILE_PATH
        history_path = self.config.HISTORY_FILE_PATH
        with self.database.lock:
            cache = self.database.read_json(rates_path, {})
            pairs = cache.get("pairs")
            if pairs is None:
                pairs = {
                    name: value
                    for name, value in cache.items()
                    if "_" in name and isinstance(value, dict) and "rate" in value
                }
            history = self.database.read_json(history_path, [])
            known_ids = {entry["id"] for entry in history}
            updated = 0
            history_changed = False

            for entry in entries:
                pair = f"{entry['from_currency']}_{entry['to_currency']}"
                timestamp = entry["timestamp"]
                current = pairs.get(pair, {})
                if _parse_timestamp(timestamp) > _parse_timestamp(
                    current.get("updated_at")
                ):
                    pairs[pair] = {
                        "rate": entry["rate"],
                        "updated_at": timestamp,
                        "source": entry["source"],
                    }
                    updated += 1
                if entry["id"] not in known_ids:
                    history.append(entry)
                    known_ids.add(entry["id"])
                    history_changed = True

            last_refresh = max(
                refreshed_at, cache.get("last_refresh"), key=_parse_timestamp
            )
            if history_changed:
                self.database.write_json(history_path, history)
            self.database.write_json(
                rates_path,
                {
                    "pairs": pairs,
                    "source": "ParserService",
                    "last_refresh": last_refresh,
                },
            )
        return {"updated": updated, "last_refresh": last_refresh}
