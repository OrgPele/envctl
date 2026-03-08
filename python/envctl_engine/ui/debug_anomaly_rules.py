from __future__ import annotations

from typing import Any


def detect_input_anomalies(
    *,
    raw: str,
    sanitized: str,
    backend: str,
    bytes_read: int | None = None,
) -> list[dict[str, Any]]:
    anomalies: list[dict[str, Any]] = []
    if raw and _repeated_burst_ratio(raw) >= 0.75 and len(raw) >= 4:
        anomalies.append(
            {
                "event": "ui.anomaly.input_repeated_burst",
                "severity": "high",
                "backend": backend,
                "raw_len": len(raw),
            }
        )
    if (bytes_read or 0) > 0 and not sanitized:
        anomalies.append(
            {
                "event": "ui.anomaly.empty_submit_with_bytes",
                "severity": "medium",
                "backend": backend,
                "bytes_read": int(bytes_read or 0),
            }
        )
    if _contains_newline(raw) and not sanitized:
        anomalies.append(
            {
                "event": "ui.anomaly.newline_without_token",
                "severity": "medium",
                "backend": backend,
            }
        )
    return anomalies


def detect_spinner_anomaly(*, command_activity_seen: bool, spinner_started: bool) -> dict[str, Any] | None:
    if spinner_started and not command_activity_seen:
        return {
            "event": "ui.anomaly.spinner_without_command_activity",
            "severity": "medium",
        }
    return None


def detect_state_mismatch_anomaly(
    *,
    state_fingerprint_before: str,
    state_fingerprint_after: str,
    lifecycle_event_seen: bool,
) -> dict[str, Any] | None:
    if state_fingerprint_before != state_fingerprint_after and not lifecycle_event_seen:
        return {
            "event": "ui.anomaly.state_changed_without_lifecycle_event",
            "severity": "high",
            "before": state_fingerprint_before,
            "after": state_fingerprint_after,
        }
    return None


def detect_dispatch_anomaly(*, parse_failed: bool, raw: str, sanitized: str) -> dict[str, Any] | None:
    if parse_failed and (not sanitized or not raw.strip()):
        return {
            "event": "ui.anomaly.dispatch_failed_empty_or_invalid_route",
            "severity": "medium",
        }
    return None


def _contains_newline(text: str) -> bool:
    return "\n" in text or "\r" in text


def _repeated_burst_ratio(text: str) -> float:
    if not text:
        return 0.0
    runs = 1
    current = 1
    best = 1
    previous = text[0]
    for ch in text[1:]:
        if ch == previous:
            current += 1
            if current > best:
                best = current
        else:
            runs += 1
            previous = ch
            current = 1
    _ = runs
    return float(best) / float(max(1, len(text)))

