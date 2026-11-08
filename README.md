# ValutaTrade Hub

Консольный симулятор обмена валют. В нём можно завести аккаунт, покупать и продавать валюту на виртуальный баланс и смотреть историю сделок.

## Установка и запуск

Нужны Python 3.12 и `uv`.

```sh
uv sync --locked
uv run project
```

## Команды

После регистрации (`register`) и входа (`login`) пополни баланс через `deposit --amount 1000`. Команда `buy --currency EUR --amount 20` покупает 20 евро, а `show-portfolio --base USD` показывает стоимость портфеля в долларах. Остальные команды есть в `help`.

## Курсы

`update-rates` запускает Parser Service. Курсы криптовалют загружаются из CoinGecko, фиатных валют из ExchangeRate-API. Команда `show-rates --currency EUR` показывает курс евро из кеша.

Ключи задаются через переменные окружения `EXCHANGERATE_API_KEY` и `COINGECKO_API_KEY`. Без ключа ExchangeRate-API используется открытый доступ.

Кеш хранится в `data/rates.json` и по умолчанию действует 300 секунд. Срок можно изменить в `pyproject.toml`. Если курс устарел, приложение запрашивает новый перед сделкой.

[Rates By Exchange Rate API](https://www.exchangerate-api.com)

## Структура

- `valutatrade_hub/core/` содержит модели и операции с портфелем.
- `valutatrade_hub/cli/` разбирает команды и печатает результат.
- `valutatrade_hub/infra/` отвечает за настройки и работу с JSON.
- `valutatrade_hub/parser_service/` загружает курсы.
- `data/` хранит пользователей, портфели, кеш и историю курсов.

[Демонстрация](https://asciinema.org/a/xIpzBPaifBarAFgM)
