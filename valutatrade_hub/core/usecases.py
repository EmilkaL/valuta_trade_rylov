from decimal import Decimal

from valutatrade_hub.core.currencies import CURRENCIES, CryptoCurrency, get_currency
from valutatrade_hub.core.exceptions import (
    ApiRequestError,
    InsufficientFundsError,
    ValutaTradeError,
)
from valutatrade_hub.core.models import Portfolio, User
from valutatrade_hub.core.utils import (
    SETTLEMENT_CURRENCY,
    get_cached_rate,
    is_finite_number,
    is_fresh_rate,
    normalize_username,
    utc_timestamp,
    validate_amount,
)
from valutatrade_hub.decorators import log_action
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.infra.settings import SettingsLoader
from valutatrade_hub.parser_service.updater import create_updater


class TradingService:
    def __init__(self):
        self.settings = SettingsLoader()
        self.database = DatabaseManager()

    def _read_records(self, setting: str) -> list[dict]:
        records = self.database.read_json(self.settings.get(setting), [])
        if not isinstance(records, list):
            raise ValutaTradeError("Некорректный формат файла с данными")
        return records

    def register(self, username: str, password: str) -> User:
        username = normalize_username(username)
        with self.database.lock:
            users = self._read_records("users_file")
            if any(record["username"] == username for record in users):
                raise ValutaTradeError(f"Имя пользователя '{username}' уже занято")
            portfolios = self._read_records("portfolios_file")
            last_id = max(
                (record["user_id"] for record in users + portfolios), default=0
            )
            user = User.create(last_id + 1, username, password)
            self._save_portfolio(portfolios, Portfolio(user))
            try:
                self.database.write_json(
                    self.settings.get("users_file"), [*users, user.to_dict()]
                )
            except (OSError, ValueError):
                self.database.write_json(
                    self.settings.get("portfolios_file"), portfolios
                )
                raise
            return user

    def login(self, username: str, password: str) -> User:
        username = normalize_username(username)
        users = self._read_records("users_file")
        record = next((item for item in users if item["username"] == username), None)
        if record is None:
            raise ValutaTradeError(f"Пользователь '{username}' не найден")
        user = User.from_dict(record)
        if not user.verify_password(password):
            raise ValutaTradeError("Неверный пароль")
        return user

    def _load_portfolio(self, user_id: int) -> tuple[list[dict], Portfolio]:
        if user_id is None:
            raise ValutaTradeError("Сначала выполните login")
        users = self._read_records("users_file")
        user = next((record for record in users if record["user_id"] == user_id), None)
        if user is None:
            raise ValutaTradeError("Пользователь не найден. Выполните login")
        portfolios = self._read_records("portfolios_file")
        record = next((item for item in portfolios if item["user_id"] == user_id), {})
        return portfolios, Portfolio.from_dict(User.from_dict(user), record)

    def _save_portfolio(self, portfolios: list[dict], portfolio: Portfolio) -> None:
        others = [item for item in portfolios if item["user_id"] != portfolio.user_id]
        self.database.write_json(
            self.settings.get("portfolios_file"), [*others, portfolio.to_dict()]
        )

    def deposit(self, user_id: int, amount: float) -> float:
        amount = validate_amount(amount)
        with self.database.lock:
            portfolios, portfolio = self._load_portfolio(user_id)
            wallet = portfolio.add_currency(SETTLEMENT_CURRENCY)
            wallet.deposit(amount)
            self._save_portfolio(portfolios, portfolio)
            return wallet.balance

    @log_action("BUY", verbose=True)
    def buy(self, user_id: int, currency_code: str, amount: float) -> dict:
        return self._trade(user_id, currency_code, amount, "BUY")

    @log_action("SELL", verbose=True)
    def sell(self, user_id: int, currency_code: str, amount: float) -> dict:
        return self._trade(user_id, currency_code, amount, "SELL")

    def _trade(
        self, user_id: int, currency_code: str, amount: float, action: str
    ) -> dict:
        amount = validate_amount(amount)
        code = get_currency(currency_code).code
        if code == SETTLEMENT_CURRENCY:
            raise ValutaTradeError("Пополните расчётный кошелёк USD командой deposit")

        with self.database.lock:
            portfolios, portfolio = self._load_portfolio(user_id)
            wallet = portfolio.get_wallet(code)
            before = wallet.balance if wallet is not None else 0.0
            if action == "SELL" and amount > before:
                raise InsufficientFundsError(before, amount, code)
            quote = self.get_rate(code, SETTLEMENT_CURRENCY)
            rate = quote["rate"]
            total = float(Decimal(str(amount)) * Decimal(str(rate)))
            if not is_finite_number(total) or total <= 0:
                raise ValueError("Не удалось рассчитать стоимость сделки")

            usd = portfolio.add_currency(SETTLEMENT_CURRENCY)
            if action == "BUY":
                usd.withdraw(total)
                wallet = portfolio.add_currency(code)
                wallet.deposit(amount)
            else:
                wallet.withdraw(amount)
                usd.deposit(total)

            trade = {
                "action": action,
                "timestamp": utc_timestamp(),
                "currency_code": code,
                "amount": amount,
                "rate": rate,
                "base": SETTLEMENT_CURRENCY,
                "before": before,
                "after": wallet.balance,
                "total": total,
            }
            portfolio.record_transaction(trade)
            self._save_portfolio(portfolios, portfolio)
            return trade

    def history(self, user_id: int) -> list[dict]:
        _, portfolio = self._load_portfolio(user_id)
        return portfolio.transactions

    def _read_rates(self) -> tuple[dict, str | None]:
        cache = self.database.read_json(self.settings.get("rates_file"), {})
        if not isinstance(cache, dict):
            raise ValutaTradeError("Некорректный формат кеша курсов")
        pairs = cache.get("pairs", cache)
        if not isinstance(pairs, dict):
            raise ValutaTradeError("Некорректный формат кеша курсов")
        return pairs, cache.get("last_refresh")

    def show_portfolio(self, user_id: int, base: str | None = None) -> dict:
        _, portfolio = self._load_portfolio(user_id)
        base = self._base_code(base)
        pairs, _ = self._read_rates()
        exchange_rates = {}
        for code, wallet in portfolio.wallets.items():
            if code == base or wallet.balance == 0:
                continue
            quote = get_cached_rate(pairs, code, base)
            if quote is not None and self._is_fresh(quote):
                exchange_rates[code] = quote["rate"]
        return {
            "base": base,
            "total": portfolio.get_total_value(base, exchange_rates),
            "wallets": portfolio.wallet_values(base, exchange_rates),
        }

    def _base_code(self, base: str | None) -> str:
        if base is None:
            base = self.settings.get("base_currency", SETTLEMENT_CURRENCY)
        return get_currency(base).code

    def _is_fresh(self, quote: dict) -> bool:
        return is_fresh_rate(quote, self.settings.get("rates_ttl_seconds"))

    def get_rate(self, from_code: str, to_code: str) -> dict:
        from_currency = get_currency(from_code)
        to_currency = get_currency(to_code)
        from_code, to_code = from_currency.code, to_currency.code
        pairs, _ = self._read_rates()
        quote = get_cached_rate(pairs, from_code, to_code)
        if quote is not None and self._is_fresh(quote):
            return quote

        sources = {
            "coingecko" if isinstance(currency, CryptoCurrency) else "exchangerate"
            for currency in (from_currency, to_currency)
            if currency.code != SETTLEMENT_CURRENCY
        }
        source = next(iter(sources)) if len(sources) == 1 else None
        status = "устарел" if quote is not None else "недоступен"
        message = f"Курс {from_code}→{to_code} {status}. Выполните update-rates"
        try:
            create_updater(source).run_update()
        except ApiRequestError as error:
            raise ApiRequestError(f"{message}. {error.reason}") from error

        pairs, _ = self._read_rates()
        quote = get_cached_rate(pairs, from_code, to_code)
        if quote is None or not self._is_fresh(quote):
            raise ApiRequestError(message)
        return quote

    def show_rates(
        self,
        currency_code: str | None = None,
        top: int | None = None,
        base: str | None = None,
    ) -> dict:
        base = self._base_code(base)
        pairs, last_refresh = self._read_rates()
        codes = {
            code
            for pair, quote in pairs.items()
            if isinstance(quote, dict) and "_" in pair
            for code in pair.split("_", 1)
        } & CURRENCIES.keys()
        if not codes:
            raise ValutaTradeError(
                "Локальный кеш курсов пуст. Выполните 'update-rates' для загрузки"
            )
        if currency_code is not None:
            currency_code = get_currency(currency_code).code
            codes = {currency_code}
        else:
            codes.discard(base)
        if top is not None:
            if type(top) is not int or top <= 0:
                raise ValueError("'top' должен быть положительным целым числом")
            codes = {
                code for code in codes if isinstance(CURRENCIES[code], CryptoCurrency)
            }

        rows = []
        for code in sorted(codes):
            quote = get_cached_rate(pairs, code, base)
            if quote is not None:
                rows.append(
                    {
                        **quote,
                        "currency_code": code,
                        "stale": not self._is_fresh(quote),
                    }
                )
        if currency_code is not None and not rows:
            raise ValutaTradeError(f"Курс для '{currency_code}' не найден в кеше")
        if top is not None:
            rows = sorted(rows, key=lambda row: row["rate"], reverse=True)[:top]
        return {"base": base, "last_refresh": last_refresh, "rows": rows}
