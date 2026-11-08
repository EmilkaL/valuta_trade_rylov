import math
import time
from abc import ABC, abstractmethod
from urllib.parse import quote

import requests

from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.parser_service.config import ParserConfig

HTTP_ERRORS = {
    401: "проверьте ключ API",
    403: "доступ запрещён",
    429: "превышен лимит запросов",
}
EXCHANGERATE_ERRORS = {
    "invalid-key": "проверьте ключ API",
    "inactive-account": "подтвердите аккаунт",
    "quota-reached": "превышен лимит запросов",
}


def positive_rate(value):
    if type(value) not in (int, float):
        return None
    try:
        rate = float(value)
    except OverflowError:
        return None
    return rate if math.isfinite(rate) and rate > 0 else None


class BaseApiClient(ABC):
    source = ""

    def __init__(self, config: ParserConfig | None = None):
        self.config = config if config is not None else ParserConfig()
        self.request_meta = {}
        self.rate_meta = {}

    @abstractmethod
    def fetch_rates(self) -> dict[str, float]:
        pass

    def _get_json(self, url, **kwargs):
        started = time.monotonic()
        try:
            response = requests.get(url, timeout=self.config.REQUEST_TIMEOUT, **kwargs)
        except requests.Timeout:
            raise ApiRequestError(f"{self.source}: время ожидания истекло") from None
        except requests.RequestException:
            raise ApiRequestError(f"{self.source}: не удалось подключиться") from None

        status = response.status_code
        if status != 200:
            detail = HTTP_ERRORS.get(status, "не удалось получить курсы")
            raise ApiRequestError(f"{self.source}: HTTP {status}, {detail}")
        try:
            data = response.json()
        except ValueError:
            raise ApiRequestError(f"{self.source}: неверный JSON") from None
        if not isinstance(data, dict):
            raise ApiRequestError(f"{self.source}: неожиданный формат ответа")

        self.request_meta = {
            "request_ms": round((time.monotonic() - started) * 1000),
            "status_code": status,
        }
        etag = getattr(response, "headers", {}).get("ETag")
        if isinstance(etag, str):
            self.request_meta["etag"] = etag
        self.rate_meta = {}
        return data


class CoinGeckoClient(BaseApiClient):
    source = "CoinGecko"

    def fetch_rates(self) -> dict[str, float]:
        base = self.config.BASE_FIAT_CURRENCY
        ids = {
            code: self.config.CRYPTO_ID_MAP[code]
            for code in self.config.CRYPTO_CURRENCIES
        }
        headers = {}
        if self.config.COINGECKO_API_KEY:
            headers["x-cg-demo-api-key"] = self.config.COINGECKO_API_KEY
        data = self._get_json(
            self.config.COINGECKO_URL,
            params={
                "ids": ",".join(ids.values()),
                "vs_currencies": base.lower(),
                "include_last_updated_at": "true",
            },
            headers=headers,
        )

        rates = {}
        for code, coin_id in ids.items():
            quote_data = data.get(coin_id)
            if not isinstance(quote_data, dict):
                continue
            rate = positive_rate(quote_data.get(base.lower()))
            if rate is None:
                continue
            pair = f"{code}_{base}"
            rates[pair] = rate
            self.rate_meta[pair] = {"raw_id": coin_id}
            provider_time = quote_data.get("last_updated_at")
            if type(provider_time) is int:
                self.rate_meta[pair]["provider_timestamp"] = provider_time
        if not rates:
            raise ApiRequestError(f"{self.source}: в ответе нет подходящих курсов")
        return rates


class ExchangeRateApiClient(BaseApiClient):
    source = "ExchangeRate-API"

    def fetch_rates(self) -> dict[str, float]:
        base = self.config.BASE_FIAT_CURRENCY
        key = self.config.EXCHANGERATE_API_KEY
        if key:
            url = self.config.EXCHANGERATE_API_URL.format(
                key=quote(key, safe=""), base=base
            )
        else:
            url = self.config.EXCHANGERATE_OPEN_URL.format(base=base)

        data = self._get_json(url)
        if data.get("result") != "success":
            error = EXCHANGERATE_ERRORS.get(str(data.get("error-type")))
            detail = error or "сервис не вернул курсы"
            raise ApiRequestError(f"{self.source}: {detail}")
        rates_data = data.get("conversion_rates", data.get("rates"))
        if not isinstance(rates_data, dict) or data.get("base_code", base) != base:
            raise ApiRequestError(f"{self.source}: неожиданный формат курсов")

        provider_time = data.get("time_last_update_unix")
        if type(provider_time) is int:
            self.request_meta["provider_timestamp"] = provider_time
        rates = {}
        for code in self.config.FIAT_CURRENCIES:
            rate = positive_rate(rates_data.get(code))
            if rate is not None:
                reversed_rate = positive_rate(1 / rate)
                if reversed_rate is not None:
                    rates[f"{code}_{base}"] = reversed_rate
        if not rates:
            raise ApiRequestError(f"{self.source}: в ответе нет подходящих курсов")
        return rates
