import logging

from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.parser_service.api_clients import (
    CoinGeckoClient,
    ExchangeRateApiClient,
    positive_rate,
)
from valutatrade_hub.parser_service.config import ParserConfig
from valutatrade_hub.parser_service.storage import RatesStorage, utc_timestamp

logger = logging.getLogger("valutatrade.parser")


def _valid_code(code):
    return 2 <= len(code) <= 5 and code.isascii() and code.isalnum() and code.isupper()


def _measurements(client, rates, timestamp):
    if not isinstance(rates, dict):
        return []
    entries = []
    for pair, value in rates.items():
        if not isinstance(pair, str):
            continue
        rate = positive_rate(value)
        codes = pair.split("_")
        if rate is None or len(codes) != 2 or not all(map(_valid_code, codes)):
            continue
        request_meta = getattr(client, "request_meta", {})
        rate_meta = getattr(client, "rate_meta", {}).get(pair, {})
        entries.append(
            {
                "id": f"{pair}_{timestamp}",
                "from_currency": codes[0],
                "to_currency": codes[1],
                "rate": rate,
                "timestamp": timestamp,
                "source": client.source,
                "meta": {**request_meta, **rate_meta},
            }
        )
    return entries


class RatesUpdater:
    def __init__(self, clients, storage):
        self.clients = clients
        self.storage = storage

    def run_update(self):
        logger.info("Начато обновление курсов")
        entries = []
        errors = []
        for client in self.clients:
            logger.info("Запрос к %s", client.source)
            try:
                rates = client.fetch_rates()
                measurements = _measurements(client, rates, utc_timestamp())
                if not measurements:
                    raise ApiRequestError(f"{client.source}: нет подходящих курсов")
            except ApiRequestError as error:
                logger.warning("%s", error)
                errors.append(error.reason)
                continue
            entries.extend(measurements)
            logger.info("%s: получено курсов %d", client.source, len(measurements))

        if not entries:
            logger.error("Обновить курсы не удалось")
            reason = " | ".join(errors) or "Не выбраны источники курсов"
            raise ApiRequestError(reason)

        logger.info("Сохранение курсов")
        result = self.storage.save(entries, utc_timestamp())
        logger.info("Обновление завершено. Обновлено курсов %d", result["updated"])
        return {**result, "errors": errors}


def create_updater(source=None):
    config = ParserConfig()
    clients = {
        "coingecko": CoinGeckoClient(config),
        "exchangerate": ExchangeRateApiClient(config),
    }
    if source is None:
        return RatesUpdater(list(clients.values()), RatesStorage(config))
    source = source.strip().lower()
    if source not in clients:
        raise ValueError("Источник должен быть coingecko или exchangerate")
    return RatesUpdater([clients[source]], RatesStorage(config))
