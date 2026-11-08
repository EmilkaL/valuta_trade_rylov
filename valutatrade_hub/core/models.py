from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from secrets import compare_digest, token_hex

from valutatrade_hub.core.exceptions import InsufficientFundsError
from valutatrade_hub.core.utils import (
    SETTLEMENT_CURRENCY,
    is_finite_number,
    normalize_currency_code,
    normalize_username,
    validate_amount,
)

MIN_PASSWORD_LENGTH = 4
SALT_BYTES = 16


class User:
    def __init__(
        self,
        user_id: int,
        username: str,
        hashed_password: str,
        salt: str,
        registration_date: datetime,
    ):
        self._user_id = user_id
        self.username = username
        self._hashed_password = hashed_password
        self._salt = salt
        self._registration_date = registration_date

    @property
    def user_id(self) -> int:
        return self._user_id

    @property
    def username(self) -> str:
        return self._username

    @username.setter
    def username(self, value: str) -> None:
        self._username = normalize_username(value)

    @property
    def hashed_password(self) -> str:
        return self._hashed_password

    @property
    def salt(self) -> str:
        return self._salt

    @property
    def registration_date(self) -> datetime:
        return self._registration_date

    @staticmethod
    def _password_hash(password: str, salt: str) -> str:
        return sha256((password + salt).encode("utf-8")).hexdigest()

    @classmethod
    def _new_password(cls, password: str) -> tuple[str, str]:
        if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
            raise ValueError(
                f"Пароль должен быть не короче {MIN_PASSWORD_LENGTH} символов"
            )
        salt = token_hex(SALT_BYTES)
        return cls._password_hash(password, salt), salt

    @classmethod
    def create(cls, user_id: int, username: str, password: str) -> "User":
        hashed_password, salt = cls._new_password(password)
        return cls(user_id, username, hashed_password, salt, datetime.now(UTC))

    def change_password(self, new_password: str) -> None:
        self._hashed_password, self._salt = self._new_password(new_password)

    def verify_password(self, password: str) -> bool:
        return isinstance(password, str) and compare_digest(
            self._hashed_password, self._password_hash(password, self._salt)
        )

    def get_user_info(self) -> dict:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "registration_date": self.registration_date.isoformat(),
        }

    def to_dict(self) -> dict:
        return {
            **self.get_user_info(),
            "hashed_password": self.hashed_password,
            "salt": self.salt,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "User":
        return cls(
            data["user_id"],
            data["username"],
            data["hashed_password"],
            data["salt"],
            datetime.fromisoformat(data["registration_date"]),
        )


class Wallet:
    def __init__(self, currency_code: str, balance: float = 0.0):
        self.currency_code = normalize_currency_code(currency_code)
        self.balance = balance

    @property
    def balance(self) -> float:
        return self._balance

    @balance.setter
    def balance(self, value: float) -> None:
        if not is_finite_number(value) or value < 0:
            raise ValueError("Баланс должен быть неотрицательным числом")
        self._balance = float(value)

    def deposit(self, amount: float) -> None:
        amount = validate_amount(amount)
        self.balance = float(Decimal(str(self.balance)) + Decimal(str(amount)))

    def withdraw(self, amount: float) -> None:
        amount = validate_amount(amount)
        if amount > self.balance:
            raise InsufficientFundsError(self.balance, amount, self.currency_code)
        self.balance = float(Decimal(str(self.balance)) - Decimal(str(amount)))

    def get_balance_info(self) -> str:
        return f"{self.currency_code}: {self.balance:.8g}"


class Portfolio:
    def __init__(
        self,
        user: User,
        wallets: dict[str, Wallet] | None = None,
        transactions: list[dict] | None = None,
    ):
        self._user = user
        self._user_id = user.user_id
        self._wallets = {
            wallet.currency_code: wallet for wallet in (wallets or {}).values()
        }
        self._transactions = [record.copy() for record in transactions or []]

    @property
    def user(self) -> User:
        return self._user

    @property
    def user_id(self) -> int:
        return self._user_id

    @property
    def wallets(self) -> dict[str, Wallet]:
        return self._wallets.copy()

    @property
    def transactions(self) -> list[dict]:
        return [record.copy() for record in self._transactions]

    def get_wallet(self, currency_code: str) -> Wallet | None:
        return self._wallets.get(normalize_currency_code(currency_code))

    def add_currency(self, currency_code: str) -> Wallet:
        code = normalize_currency_code(currency_code)
        if code not in self._wallets:
            self._wallets[code] = Wallet(code)
        return self._wallets[code]

    def wallet_values(self, base_currency: str, exchange_rates: dict) -> list[dict]:
        base_currency = normalize_currency_code(base_currency)
        values = []
        for code, wallet in self._wallets.items():
            rate = 1.0 if code == base_currency else exchange_rates.get(code)
            value = wallet.balance * rate if rate is not None else None
            if wallet.balance == 0:
                value = 0.0
            elif not is_finite_number(value):
                value = None
            values.append(
                {"currency_code": code, "balance": wallet.balance, "value": value}
            )
        return values

    def get_total_value(
        self,
        base_currency: str = SETTLEMENT_CURRENCY,
        exchange_rates: dict | None = None,
    ) -> float:
        values = self.wallet_values(base_currency, exchange_rates or {})
        return sum((row["value"] for row in values if row["value"] is not None), 0.0)

    def record_transaction(self, record: dict) -> None:
        self._transactions.append(record.copy())

    def to_dict(self) -> dict:
        wallets = {
            code: {"balance": wallet.balance} for code, wallet in self._wallets.items()
        }
        return {
            "user_id": self.user_id,
            "wallets": wallets,
            "transactions": self.transactions,
        }

    @classmethod
    def from_dict(cls, user: User, data: dict) -> "Portfolio":
        wallets = {
            code: Wallet(code, wallet["balance"])
            for code, wallet in data.get("wallets", {}).items()
        }
        return cls(user, wallets, data.get("transactions"))
