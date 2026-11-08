import argparse
import shlex
import sys

from prettytable import PrettyTable

from valutatrade_hub.core.exceptions import (
    ApiRequestError,
    CurrencyNotFoundError,
    ValutaTradeError,
)
from valutatrade_hub.core.usecases import TradingService
from valutatrade_hub.logging_config import configure_logging
from valutatrade_hub.parser_service.scheduler import schedule_updates
from valutatrade_hub.parser_service.updater import create_updater


class CommandParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def make_parser():
    parser = CommandParser(prog="project", description="ValutaTrade Hub")
    commands = parser.add_subparsers(dest="command", required=True)

    for name, description in (
        ("register", "Создать пользователя"),
        ("login", "Войти в аккаунт"),
    ):
        command = commands.add_parser(name, help=description)
        command.add_argument("--username", required=True)
        command.add_argument("--password", required=True)

    portfolio = commands.add_parser("show-portfolio", help="Показать кошельки")
    portfolio.add_argument("--base")

    deposit = commands.add_parser("deposit", help="Пополнить виртуальный USD-баланс")
    deposit.add_argument("--amount", type=float, required=True)

    for name, description in (("buy", "Купить валюту"), ("sell", "Продать валюту")):
        command = commands.add_parser(name, help=description)
        command.add_argument("--currency", required=True)
        command.add_argument("--amount", type=float, required=True)

    rate = commands.add_parser("get-rate", help="Узнать курс валютной пары")
    rate.add_argument("--from", dest="from_code", required=True)
    rate.add_argument("--to", dest="to_code", required=True)

    rates = commands.add_parser("show-rates", help="Показать курсы из кеша")
    rates.add_argument("--currency")
    rates.add_argument("--top", type=int)
    rates.add_argument("--base")

    for name, description in (
        ("update-rates", "Обновить курсы"),
        ("schedule-rates", "Обновлять курсы по таймеру"),
    ):
        command = commands.add_parser(name, help=description)
        command.add_argument("--source", choices=("coingecko", "exchangerate"))
        if name == "schedule-rates":
            command.add_argument("--interval", type=int, required=True)

    commands.add_parser("history", help="Показать покупки и продажи")
    help_command = commands.add_parser("help", help="Показать справку")
    help_command.add_argument("target", nargs="?")
    commands.add_parser("exit", help="Выйти из программы")
    return parser, commands.choices


def print_table(fields, rows):
    table = PrettyTable(fields)
    table.add_rows(rows)
    print(table)


def print_portfolio(username, portfolio):
    print(f"Портфель пользователя '{username}' (база: {portfolio['base']}):")
    if not portfolio["wallets"]:
        print("Кошельков пока нет. Пополните баланс командой deposit.")
        return

    rows = []
    for wallet in portfolio["wallets"]:
        value = wallet["value"]
        rows.append(
            (
                wallet["currency_code"],
                f"{wallet['balance']:.8g}",
                "нет курса" if value is None else f"{value:,.2f}",
            )
        )
    print_table(["Валюта", "Баланс", portfolio["base"]], rows)
    if any(wallet["value"] is None for wallet in portfolio["wallets"]):
        print("В итог включены кошельки с актуальным курсом. Выполните update-rates.")
    print(f"ИТОГО: {portfolio['total']:,.2f} {portfolio['base']}")


def print_trade(action, trade):
    title = "Покупка" if action == "buy" else "Продажа"
    value_title = "Стоимость покупки" if action == "buy" else "Выручка"
    code, base = trade["currency_code"], trade["base"]
    print(
        f"{title} выполнена: {trade['amount']:.8g} {code} "
        f"по курсу {trade['rate']:,.8g} {base}/{code}"
    )
    print(f"Кошелёк {code}: было {trade['before']:.8g}, стало {trade['after']:.8g}")
    print(f"{value_title}: {trade['total']:,.2f} {base}")


def print_rates(result):
    print(f"Кеш курсов. Последнее обновление: {result['last_refresh']}")
    print_table(
        ["Валюта", result["base"], "Обновлено", "Источник", "Статус"],
        [
            (
                row["currency_code"],
                f"{row['rate']:.8g}",
                row["updated_at"],
                row["source"],
                "устарел" if row["stale"] else "актуален",
            )
            for row in result["rows"]
        ],
    )


def print_history(history):
    if not history:
        print("Сделок пока нет.")
        return
    print_table(
        ["Время", "Операция", "Валюта", "Количество", "Сумма в USD"],
        [
            (
                row["timestamp"],
                row["action"],
                row["currency_code"],
                f"{row['amount']:.8g}",
                f"{row['total']:,.2f}",
            )
            for row in history
        ],
    )


class Console:
    def __init__(self):
        self.parser, self.commands = make_parser()
        self.service = TradingService()
        self.user = None

    def _current_user(self):
        if self.user is None:
            raise ValutaTradeError("Сначала выполните login.")
        return self.user

    def execute(self, tokens):
        args = self.parser.parse_args(tokens)
        match args.command:
            case "register":
                user = self.service.register(args.username, args.password)
                print(
                    f"Пользователь '{user.username}' зарегистрирован "
                    f"(id={user.user_id})."
                )
                print(f"Войдите: login --username {user.username} --password ****")
            case "login":
                self.user = self.service.login(args.username, args.password)
                print(f"Вы вошли как '{self.user.username}'")
            case "show-portfolio":
                user = self._current_user()
                portfolio = self.service.show_portfolio(user.user_id, args.base)
                print_portfolio(user.username, portfolio)
            case "deposit":
                user = self._current_user()
                balance = self.service.deposit(user.user_id, args.amount)
                print(f"Виртуальный баланс: {balance:,.2f} USD")
            case "buy" | "sell":
                user_id = self._current_user().user_id
                operation = (
                    self.service.buy if args.command == "buy" else self.service.sell
                )
                trade = operation(user_id, args.currency, args.amount)
                print_trade(args.command, trade)
            case "get-rate":
                result = self.service.get_rate(args.from_code, args.to_code)
                source = args.from_code.strip().upper()
                target = args.to_code.strip().upper()
                updated = result["updated_at"] or "фиксированный"
                rate = result["rate"]
                print(f"Курс {source} → {target}: {rate:.8g} (обновлено: {updated})")
                print(f"Обратный курс {target} → {source}: {1 / rate:.8g}")
            case "show-rates":
                print_rates(self.service.show_rates(args.currency, args.top, args.base))
            case "update-rates":
                result = create_updater(args.source).run_update()
                print(
                    f"Обновлено курсов: {result['updated']}. "
                    f"Последнее обновление: {result['last_refresh']}"
                )
                for error in result["errors"]:
                    print(error)
            case "schedule-rates":
                print("Обновление по таймеру запущено. Для остановки нажмите Ctrl+C.")
                schedule_updates(args.interval, args.source)
            case "history":
                print_history(self.service.history(self._current_user().user_id))
            case "help":
                if args.target is None:
                    self.parser.print_help()
                elif args.target in self.commands:
                    self.commands[args.target].print_help()
                else:
                    raise ValueError(f"Неизвестная команда '{args.target}'")

    def run(self):
        print("ValutaTrade Hub. Введите help, чтобы посмотреть команды.")
        while True:
            try:
                tokens = shlex.split(input("> "))
                if tokens == ["exit"]:
                    return
                if tokens:
                    self.execute(tokens)
            except (EOFError, KeyboardInterrupt):
                print()
                return
            except (ValutaTradeError, ValueError, OSError) as error:
                report_error(error)
            except SystemExit:
                continue


def report_error(error):
    print(f"Ошибка: {error}")
    if isinstance(error, CurrencyNotFoundError):
        print("Справка по курсам: help get-rate.")
    elif isinstance(error, ApiRequestError):
        print("Проверьте сеть или повторите попытку позже.")


def main():
    try:
        configure_logging()
        console = Console()
        if sys.argv[1:]:
            console.execute(sys.argv[1:])
        else:
            console.run()
    except (ValutaTradeError, ValueError, OSError) as error:
        report_error(error)
        return 1
    except KeyboardInterrupt:
        print()
        return 130
    return 0
