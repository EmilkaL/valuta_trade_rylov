import os
from dataclasses import dataclass, field
from pathlib import Path

from valutatrade_hub.infra.settings import SettingsLoader

CRYPTO_ID_MAP = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana"}


@dataclass
class ParserConfig:
    COINGECKO_URL: str = "https://api.coingecko.com/api/v3/simple/price"
    EXCHANGERATE_API_URL: str = "https://v6.exchangerate-api.com/v6/{key}/latest/{base}"
    EXCHANGERATE_OPEN_URL: str = "https://open.er-api.com/v6/latest/{base}"
    BASE_FIAT_CURRENCY: str = "USD"
    FIAT_CURRENCIES: tuple[str, ...] = ("EUR", "GBP", "RUB")
    CRYPTO_CURRENCIES: tuple[str, ...] = tuple(CRYPTO_ID_MAP)
    CRYPTO_ID_MAP: dict[str, str] = field(default_factory=CRYPTO_ID_MAP.copy)
    REQUEST_TIMEOUT: int = 10
    RATES_FILE_PATH: Path = field(
        default_factory=lambda: SettingsLoader().get("rates_file")
    )
    HISTORY_FILE_PATH: Path = field(
        default_factory=lambda: SettingsLoader().get("history_file")
    )
    EXCHANGERATE_API_KEY: str = field(
        default_factory=lambda: os.getenv("EXCHANGERATE_API_KEY", "").strip(),
        repr=False,
    )
    COINGECKO_API_KEY: str = field(
        default_factory=lambda: os.getenv("COINGECKO_API_KEY", "").strip(),
        repr=False,
    )
