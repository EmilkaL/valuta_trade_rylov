class ValutaTradeError(Exception):
    pass


class InsufficientFundsError(ValutaTradeError):
    def __init__(self, available: float, required: float, code: str):
        super().__init__(
            f"Недостаточно средств: доступно {available:.8g} {code}, "
            f"требуется {required:.8g} {code}"
        )


class CurrencyNotFoundError(ValutaTradeError):
    def __init__(self, code: str):
        super().__init__(f"Неизвестная валюта '{code}'")


class ApiRequestError(ValutaTradeError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"Ошибка при обращении к внешнему API: {reason}")
