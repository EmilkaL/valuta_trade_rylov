from datetime import UTC, datetime
from math import isfinite

from valutatrade_hub.core.exceptions import CurrencyNotFoundError

SETTLEMENT_CURRENCY = "USD"
MIN_CURRENCY_LENGTH = 2
MAX_CURRENCY_LENGTH = 5
MIN_TIMESTAMP = datetime.min.replace(tzinfo=UTC)


def normalize_username(username: str) -> str:
    if not isinstance(username, str) or not username.strip():
        raise ValueError("Имя пользователя не может быть пустым")
    return username.strip()


def normalize_currency_code(code: str) -> str:
    if isinstance(code, str):
        normalized = code.strip().upper()
        if (
            MIN_CURRENCY_LENGTH <= len(normalized) <= MAX_CURRENCY_LENGTH
            and normalized.isascii()
            and normalized.isalnum()
        ):
            return normalized
    raise CurrencyNotFoundError(code)


def is_finite_number(value) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return isfinite(value)
    except OverflowError:
        return False


def validate_amount(amount: float) -> float:
    if not is_finite_number(amount) or amount <= 0:
        raise ValueError("'amount' должен быть положительным числом")
    return float(amount)


def utc_timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def parse_timestamp(timestamp: str | None) -> datetime | None:
    if not isinstance(timestamp, str):
        return None
    try:
        date = datetime.fromisoformat(timestamp)
    except ValueError:
        return None
    return date if date.tzinfo is not None else date.replace(tzinfo=UTC)


def is_fresh_rate(quote: dict, ttl: int) -> bool:
    updated_at = parse_timestamp(quote.get("updated_at"))
    if updated_at is None:
        return False
    return 0 <= (datetime.now(UTC) - updated_at).total_seconds() <= ttl


def _rate_timestamp(quote: dict) -> datetime:
    return parse_timestamp(quote.get("updated_at")) or MIN_TIMESTAMP


def _direct_rate(pairs: dict, from_code: str, to_code: str) -> dict | None:
    quotes = []
    for pair, inverse in (
        (f"{from_code}_{to_code}", False),
        (f"{to_code}_{from_code}", True),
    ):
        record = pairs.get(pair)
        if not isinstance(record, dict):
            continue
        rate = record.get("rate")
        if is_finite_number(rate) and rate > 0:
            rate = 1 / rate if inverse else float(rate)
            if is_finite_number(rate) and rate > 0:
                quotes.append(
                    {
                        "rate": rate,
                        "updated_at": record.get("updated_at"),
                        "source": record.get("source") or "cache",
                    }
                )
    return max(quotes, key=_rate_timestamp, default=None)


def _cross_rate(pairs: dict, from_code: str, to_code: str) -> dict | None:
    first = _direct_rate(pairs, from_code, SETTLEMENT_CURRENCY)
    second = _direct_rate(pairs, SETTLEMENT_CURRENCY, to_code)
    if first is None or second is None:
        return None
    rate = first["rate"] * second["rate"]
    if not is_finite_number(rate) or rate <= 0:
        return None
    times = [parse_timestamp(quote.get("updated_at")) for quote in (first, second)]
    oldest = min(times).isoformat() if all(times) else None
    sources = dict.fromkeys(quote.get("source") or "cache" for quote in (first, second))
    return {"rate": rate, "updated_at": oldest, "source": " + ".join(sources)}


def get_cached_rate(pairs: dict, from_code: str, to_code: str) -> dict | None:
    if from_code == to_code:
        return {"rate": 1.0, "updated_at": utc_timestamp(), "source": "identity"}
    direct = _direct_rate(pairs, from_code, to_code)
    if SETTLEMENT_CURRENCY in (from_code, to_code):
        return direct
    cross = _cross_rate(pairs, from_code, to_code)
    quotes = [quote for quote in (direct, cross) if quote is not None]
    return max(quotes, key=_rate_timestamp, default=None)
