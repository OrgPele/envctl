from __future__ import annotations

import json
import sys
from typing import Any

from envctl_engine.config import discover_local_config_state
from envctl_engine.config.persistence import (
    managed_values_from_local_state,
    managed_values_from_payload,
    managed_values_to_payload,
    save_local_config,
)
from envctl_engine.config.wizard_domain import edit_local_config


def run_config_command(runtime: Any, route: object) -> int:
    if bool(route.flags.get("stdin_json")) or bool(route.flags.get("set_values")) or bool(route.passthrough_args):
        return _run_headless_config_command(runtime, route)

    result = edit_local_config(
        base_dir=runtime.config.base_dir,
        env={**runtime.config.raw, **runtime.env},
        emit=getattr(runtime, "_emit", None),
    )
    if result.message:
        print(result.message)
    if result.changed:
        print("Config saved. Restart required for running services to adopt changes.")
    return 0


def _run_headless_config_command(runtime: Any, route: object) -> int:
    local_state = discover_local_config_state(runtime.config.base_dir, runtime.env.get("ENVCTL_CONFIG_FILE"))
    values = managed_values_from_local_state(local_state)

    if bool(route.flags.get("stdin_json")):
        raw = sys.stdin.read()
        try:
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError as exc:
            print(f"Invalid JSON for config --stdin-json: {exc}")
            return 1
        if not isinstance(payload, dict):
            print("Invalid JSON for config --stdin-json: expected an object.")
            return 1
        values = managed_values_from_payload(payload, base_values=values)

    set_tokens: list[str] = []
    raw_set = route.flags.get("set_values")
    if isinstance(raw_set, list):
        set_tokens.extend(str(token) for token in raw_set)
    set_tokens.extend(str(token) for token in route.passthrough_args if "=" in str(token))
    if set_tokens:
        flat_updates: dict[str, object] = {}
        for token in set_tokens:
            if "=" not in token:
                print(f"Invalid config assignment: {token}")
                return 1
            key, value = token.split("=", 1)
            flat_updates[key.strip()] = value.strip()
        values = managed_values_from_payload(flat_updates, base_values=values)

    save_result = save_local_config(local_state=local_state, values=values)
    payload = {
        "saved": True,
        "path": str(save_result.path),
        "ignore_updated": save_result.ignore_updated,
        "ignore_warning": save_result.ignore_warning,
        "config": managed_values_to_payload(values),
    }
    if bool(route.flags.get("json")):
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"Saved startup config: {save_result.path}")
        print("Config saved. Restart required for running services to adopt changes.")
        if save_result.ignore_warning:
            print(save_result.ignore_warning)
    return 0
