import json
import logging
import os
from datetime import UTC, datetime
from functools import wraps
from inspect import signature
from math import isfinite

from valutatrade_hub.logging_config import ACTION_LOGGER_NAME

ACTION_FIELDS = ("user_id", "username", "currency_code", "amount")
SECRET_ENV_VARS = ("EXCHANGERATE_API_KEY", "COINGECKO_API_KEY")


def _error_message(error, arguments):
    message = str(error)
    secrets = [arguments.get("password"), *(os.getenv(key) for key in SECRET_ENV_VARS)]
    for secret in secrets:
        if isinstance(secret, str) and secret:
            message = message.replace(secret, "***")
    return message


def _write_action(entry):
    for key, value in entry.items():
        if isinstance(value, float) and not isfinite(value):
            entry[key] = str(value)
    logging.getLogger(ACTION_LOGGER_NAME).info(
        "%s", json.dumps(entry, ensure_ascii=False, default=str)
    )


def log_action(action_name, *, verbose=False):
    result_fields = ("rate", "base")
    if verbose:
        result_fields += ("before", "after", "total")

    def decorator(function):
        parameters = signature(function)

        @wraps(function)
        def wrapper(*args, **kwargs):
            arguments = parameters.bind(*args, **kwargs).arguments
            entry = {
                "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
                "action": action_name,
            }
            entry.update(
                {key: arguments[key] for key in ACTION_FIELDS if key in arguments}
            )

            try:
                result = function(*args, **kwargs)
            except Exception as error:
                entry.update(
                    result="ERROR",
                    error_type=type(error).__name__,
                    error_message=_error_message(error, arguments),
                )
                _write_action(entry)
                raise

            entry["result"] = "OK"
            if isinstance(result, dict):
                entry.update(
                    {key: result[key] for key in result_fields if key in result}
                )
            _write_action(entry)
            return result

        return wrapper

    return decorator
