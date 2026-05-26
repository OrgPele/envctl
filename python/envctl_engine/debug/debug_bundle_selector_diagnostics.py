from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from envctl_engine.shared.parsing import parse_int


@dataclass(slots=True)
class SelectorDiagnostics:
    inactive_tokens: list[str]
    low_throughput: list[dict[str, object]]
    mouse_double_toggle: bool
    blocked_then_cancel: bool
    key_pipeline_gaps: list[dict[str, object]]
    read_pipeline_gaps: list[dict[str, object]]
    driver_focus_loss: list[dict[str, object]]
    idle_after_activity: list[dict[str, object]]


@dataclass(slots=True)
class SelectorDriverDiagnostics:
    key_totals: dict[str, int]
    key_names: dict[str, Mapping[str, object]]
    non_key_names: dict[str, Mapping[str, object]]
    non_key_totals: dict[str, int]


def analyze_selector_diagnostics(timeline: Sequence[Mapping[str, object]]) -> SelectorDiagnostics:
    selector_activity_counts, selector_key_counts = _selector_activity_counts(timeline)
    latest_ts_mono = max(
        (parse_int(item.get("ts_mono_ns"), 0) for item in timeline if isinstance(item.get("ts_mono_ns"), int)),
        default=0,
    )
    inactive_tokens = _selector_inactive_tokens(
        timeline,
        latest_ts_mono=latest_ts_mono,
        selector_activity_counts=selector_activity_counts,
    )
    low_throughput = _selector_low_throughput(
        timeline,
        latest_ts_mono=latest_ts_mono,
        selector_key_counts=selector_key_counts,
    )
    mouse_double_toggle = _selector_mouse_double_toggle(timeline)
    blocked_then_cancel = _selector_blocked_then_cancel(timeline)
    driver = _selector_driver_diagnostics(timeline)
    app_key_totals = _selector_app_key_totals(timeline)
    key_pipeline_gaps = _selector_key_pipeline_gaps(
        driver_key_totals=driver.key_totals,
        app_key_totals=app_key_totals,
        driver_key_names=driver.key_names,
    )
    read_pipeline_gaps = _selector_read_pipeline_gaps(
        timeline,
        driver_key_totals=driver.key_totals,
        driver_non_key_totals=driver.non_key_totals,
    )
    driver_focus_loss = _selector_driver_focus_loss(driver.non_key_names)
    idle_after_activity = _selector_idle_after_activity(timeline)
    return SelectorDiagnostics(
        inactive_tokens=inactive_tokens,
        low_throughput=low_throughput,
        mouse_double_toggle=mouse_double_toggle,
        blocked_then_cancel=blocked_then_cancel,
        key_pipeline_gaps=key_pipeline_gaps,
        read_pipeline_gaps=read_pipeline_gaps,
        driver_focus_loss=driver_focus_loss,
        idle_after_activity=idle_after_activity,
    )


def selector_token(item: Mapping[str, object]) -> str:
    selector_id = str(item.get("selector_id", "")).strip().lower()
    if selector_id:
        return f"id:{selector_id}"
    prompt = str(item.get("prompt", "")).strip().lower()
    if prompt:
        return f"prompt:{prompt}"
    return ""


def sum_counter_payload(value: object) -> int:
    if not isinstance(value, Mapping):
        return 0
    total = 0
    for raw_count in value.values():
        total += parse_int(raw_count, 0)
    return total


def _selector_activity_counts(
    timeline: Sequence[Mapping[str, object]],
) -> tuple[dict[str, int], dict[str, int]]:
    activity_events = {
        "ui.selector.key",
        "ui.selector.mouse",
        "ui.selector.focus",
        "ui.selector.submit",
    }
    activity_counts: dict[str, int] = {}
    key_counts: dict[str, int] = {}
    for item in timeline:
        event_name = str(item.get("event", "")).strip()
        if event_name not in activity_events:
            continue
        token = selector_token(item)
        if not token:
            continue
        activity_counts[token] = activity_counts.get(token, 0) + 1
        if event_name == "ui.selector.key":
            key_counts[token] = key_counts.get(token, 0) + 1

    for item in timeline:
        event_name = str(item.get("event", "")).strip()
        if event_name not in {"ui.selector.key.summary", "ui.selector.key.snapshot"}:
            continue
        token = selector_token(item)
        if not token:
            continue
        summary_total = sum_counter_payload(item.get("handled_counts"))
        summary_total = max(summary_total, sum_counter_payload(item.get("event_counts")))
        summary_total = max(summary_total, sum_counter_payload(item.get("raw_counts")))
        if event_name == "ui.selector.key.snapshot":
            nav_total = parse_int(item.get("nav_event_counter"), 0)
            summary_total = max(summary_total, nav_total)
        if summary_total > key_counts.get(token, 0):
            key_counts[token] = summary_total
    return activity_counts, key_counts


def _selector_inactive_tokens(
    timeline: Sequence[Mapping[str, object]],
    *,
    latest_ts_mono: int,
    selector_activity_counts: Mapping[str, int],
) -> list[str]:
    inactive: list[str] = []
    for item in timeline:
        if str(item.get("event", "")).strip() != "ui.selector.lifecycle":
            continue
        if str(item.get("phase", "")).strip().lower() != "enter":
            continue
        token = selector_token(item)
        if not token or selector_activity_counts.get(token, 0) > 0:
            continue
        enter_ts = parse_int(item.get("ts_mono_ns"), 0)
        if max(0, latest_ts_mono - enter_ts) >= 1_000_000_000:
            inactive.append(token)
    return inactive


def _selector_low_throughput(
    timeline: Sequence[Mapping[str, object]],
    *,
    latest_ts_mono: int,
    selector_key_counts: Mapping[str, int],
) -> list[dict[str, object]]:
    low_throughput: list[dict[str, object]] = []
    for item in timeline:
        if str(item.get("event", "")).strip() != "ui.selector.lifecycle":
            continue
        if str(item.get("phase", "")).strip().lower() != "enter":
            continue
        token = selector_token(item)
        if not token:
            continue
        enter_ts = parse_int(item.get("ts_mono_ns"), 0)
        observed_window_ns = max(0, latest_ts_mono - enter_ts)
        if observed_window_ns < 2_000_000_000:
            continue
        key_total = selector_key_counts.get(token, 0)
        if key_total <= 1:
            low_throughput.append(
                {
                    "selector": token,
                    "observed_window_ms": round(observed_window_ns / 1_000_000, 1),
                    "key_events": key_total,
                }
            )
    return low_throughput


def _selector_mouse_double_toggle(timeline: Sequence[Mapping[str, object]]) -> bool:
    mouse_events = [
        item
        for item in timeline
        if str(item.get("event", "")).strip() == "ui.selector.mouse" and isinstance(item.get("ts_mono_ns"), int)
    ]
    mouse_events.sort(key=lambda item: parse_int(item.get("ts_mono_ns"), 0))
    last_mouse_by_row: dict[tuple[str, str], int] = {}
    for item in mouse_events:
        token = selector_token(item)
        row_id = str(item.get("row_id", "")).strip()
        if not token or not row_id:
            continue
        ts = parse_int(item.get("ts_mono_ns"), 0)
        key = (token, row_id)
        previous = last_mouse_by_row.get(key)
        if previous is not None and 0 <= ts - previous <= 250_000_000:
            return True
        last_mouse_by_row[key] = ts
    return False


def _selector_blocked_then_cancel(timeline: Sequence[Mapping[str, object]]) -> bool:
    blocked_by_selector: set[str] = set()
    for item in timeline:
        if str(item.get("event", "")).strip() != "ui.selector.submit":
            continue
        token = selector_token(item)
        if not token:
            continue
        if bool(item.get("blocked", False)):
            blocked_by_selector.add(token)
            continue
        if bool(item.get("cancelled", False)) and token in blocked_by_selector:
            return True
    return False


def _selector_driver_diagnostics(timeline: Sequence[Mapping[str, object]]) -> SelectorDriverDiagnostics:
    driver_key_totals: dict[str, int] = {}
    driver_key_names: dict[str, Mapping[str, object]] = {}
    driver_non_key_names: dict[str, Mapping[str, object]] = {}
    driver_non_key_totals: dict[str, int] = {}
    for item in timeline:
        if str(item.get("event", "")).strip() not in {
            "ui.selector.key.driver.summary",
            "ui.selector.key.driver.snapshot",
        }:
            continue
        token = selector_token(item)
        if not token:
            continue
        non_key = item.get("non_key_messages")
        if isinstance(non_key, Mapping):
            non_key_total = sum_counter_payload(non_key)
            if non_key_total >= driver_non_key_totals.get(token, -1):
                driver_non_key_totals[token] = non_key_total
                driver_non_key_names[token] = non_key
        key_total = parse_int(item.get("key_events_total"), 0)
        if key_total <= driver_key_totals.get(token, -1):
            continue
        driver_key_totals[token] = key_total
        names = item.get("key_events_by_name")
        if isinstance(names, Mapping):
            driver_key_names[token] = names
    return SelectorDriverDiagnostics(
        key_totals=driver_key_totals,
        key_names=driver_key_names,
        non_key_names=driver_non_key_names,
        non_key_totals=driver_non_key_totals,
    )


def _selector_app_key_totals(timeline: Sequence[Mapping[str, object]]) -> dict[str, int]:
    app_key_totals: dict[str, int] = {}
    for item in timeline:
        event_name = str(item.get("event", "")).strip()
        if event_name not in {"ui.selector.key.summary", "ui.selector.key.snapshot"}:
            continue
        token = selector_token(item)
        if not token:
            continue
        event_counts = sum_counter_payload(item.get("event_counts"))
        handled_counts = sum_counter_payload(item.get("handled_counts"))
        observed = max(event_counts, handled_counts)
        if observed <= app_key_totals.get(token, -1):
            continue
        app_key_totals[token] = observed
    return app_key_totals


def _selector_key_pipeline_gaps(
    *,
    driver_key_totals: Mapping[str, int],
    app_key_totals: Mapping[str, int],
    driver_key_names: Mapping[str, Mapping[str, object]],
) -> list[dict[str, object]]:
    gaps: list[dict[str, object]] = []
    for token, driver_total in driver_key_totals.items():
        app_total = app_key_totals.get(token, 0)
        if driver_total <= app_total:
            continue
        gaps.append(
            {
                "selector": token,
                "driver_key_events": driver_total,
                "app_key_events": app_total,
                "dropped_after_driver": driver_total - app_total,
                "driver_key_names": dict(driver_key_names.get(token, {})),
            }
        )
    return gaps


def _selector_read_pipeline_gaps(
    timeline: Sequence[Mapping[str, object]],
    *,
    driver_key_totals: Mapping[str, int],
    driver_non_key_totals: Mapping[str, int],
) -> list[dict[str, object]]:
    read_totals: dict[str, int] = {}
    escape_totals: dict[str, int] = {}
    for item in timeline:
        if str(item.get("event", "")).strip() not in {
            "ui.selector.key.driver.summary",
            "ui.selector.key.driver.snapshot",
        }:
            continue
        token = selector_token(item)
        if not token:
            continue
        read_bytes = parse_int(item.get("read_bytes"), 0)
        if read_bytes <= read_totals.get(token, -1):
            continue
        read_totals[token] = read_bytes
        escape_totals[token] = parse_int(item.get("escape_bytes"), 0)

    gaps: list[dict[str, object]] = []
    for token, read_bytes in read_totals.items():
        non_key_total = driver_non_key_totals.get(token, 0)
        if non_key_total > 0:
            continue
        escape_bytes = escape_totals.get(token, 0)
        if escape_bytes > 0:
            estimated_key_sequences = escape_bytes
            estimation_method = "escape_bytes"
        else:
            estimated_key_sequences = read_bytes // 3 if read_bytes > 0 else 0
            estimation_method = "read_bytes_div_3"
        driver_total = driver_key_totals.get(token, 0)
        if estimated_key_sequences <= driver_total:
            continue
        gaps.append(
            {
                "selector": token,
                "read_bytes": read_bytes,
                "estimated_key_sequences": estimated_key_sequences,
                "driver_key_events": driver_total,
                "dropped_before_driver_parse": estimated_key_sequences - driver_total,
                "estimation_method": estimation_method,
                "non_key_messages": non_key_total,
            }
        )
    return gaps


def _selector_driver_focus_loss(
    selector_driver_non_key_names: Mapping[str, Mapping[str, object]],
) -> list[dict[str, object]]:
    focus_loss: list[dict[str, object]] = []
    for token, names in selector_driver_non_key_names.items():
        app_blur = parse_int(names.get("AppBlur"), 0)
        app_focus = parse_int(names.get("AppFocus"), 0)
        if app_blur <= 0 or app_focus > 0:
            continue
        focus_loss.append(
            {
                "selector": token,
                "app_blur_events": app_blur,
                "app_focus_events": app_focus,
            }
        )
    return focus_loss


def _selector_idle_after_activity(timeline: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    idle_after_activity: list[dict[str, object]] = []
    for item in timeline:
        if str(item.get("event", "")).strip() != "ui.selector.key.idle_after_activity":
            continue
        token = selector_token(item)
        if not token:
            continue
        idle_ms = parse_int(item.get("idle_ms"), 0)
        nav_events = parse_int(item.get("nav_event_counter"), 0)
        idle_after_activity.append(
            {
                "selector": token,
                "idle_ms": idle_ms,
                "nav_event_counter": nav_events,
                "focused_widget_id": str(item.get("focused_widget_id", "")),
            }
        )
    return idle_after_activity
