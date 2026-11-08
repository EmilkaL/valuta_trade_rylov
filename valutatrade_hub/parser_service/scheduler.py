import logging
import time

from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.parser_service.updater import create_updater

logger = logging.getLogger("valutatrade.parser")


def schedule_updates(interval, source=None):
    if type(interval) is not int or interval <= 0:
        raise ValueError("Интервал обновления должен быть положительным целым числом")
    updater = create_updater(source)
    while True:
        try:
            updater.run_update()
        except ApiRequestError as error:
            logger.warning("Обновление по расписанию: %s", error)
        time.sleep(interval)
