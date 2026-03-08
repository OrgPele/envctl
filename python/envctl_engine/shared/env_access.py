from __future__ import annotations

from collections.abc import Mapping

from envctl_engine.shared.parsing import parse_bool, parse_float, parse_int


EnvMapping = Mapping[str, str] | None


def str_from_env(env: EnvMapping, key: str) -> str | None:
    if not isinstance(env, Mapping):
        return None
    value = env.get(key)
    if value is None:
        return None
    return str(value)


def bool_from_env(env: EnvMapping, key: str, default: bool) -> bool:
    return parse_bool(str_from_env(env, key), default)


def int_from_env(env: EnvMapping, key: str, default: int) -> int:
    return parse_int(str_from_env(env, key), default)


def float_from_env(env: EnvMapping, key: str, default: float) -> float:
    return parse_float(str_from_env(env, key), default)
