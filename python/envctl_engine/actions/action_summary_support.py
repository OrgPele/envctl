from __future__ import annotations

import re

from envctl_engine.test_output.parser_base import strip_ansi


def migrate_failure_headline(error_output: str) -> str:
    lines = format_summary_error_lines(error_output)
    headline = migrate_failure_headline_from_lines(lines)
    return headline or "Command failed."


def migrate_failure_headline_from_lines(lines: list[str]) -> str:
    if not lines:
        return ""
    has_exception = any(is_exception_start(line) for line in lines)
    for line in lines:
        if is_exception_start(line):
            return line
    for line in lines:
        if line == "Traceback (most recent call last):":
            continue
        if has_exception and line.startswith('File "'):
            continue
        if is_captured_output_header(line):
            continue
        if is_exception_context_marker(line):
            continue
        return line
    return lines[0]


def format_summary_error_lines(error_text: str) -> list[str]:
    cleaned = strip_ansi(error_text)
    lines: list[str] = []
    for raw_line in cleaned.splitlines():
        compact = compact_summary_line(raw_line)
        if compact:
            lines.append(compact)
    if not lines:
        return []

    max_lines = 60
    if len(lines) <= max_lines:
        return lines
    structured = structured_summary_lines(lines)
    if not structured:
        structured = lines[:]
    merged = structured[:]
    seen = set(merged)
    for line in lines:
        if len(merged) >= max_lines:
            break
        if line in seen:
            continue
        merged.append(line)
        seen.add(line)
    if len(lines) > len(merged):
        merged.append(f"... ({len(lines) - len(merged)} more lines omitted)")
    return merged[: max_lines + 1]


def compact_summary_line(line: str) -> str:
    stripped = line.strip()
    if not stripped:
        return ""
    if re.fullmatch(r"[-=]{6,}", stripped):
        return ""
    if looks_like_terminal_chrome(stripped):
        return ""
    stripped = re.sub(r"( not found in )(['\"]).*", r"\1<omitted output>", stripped)
    stripped = re.sub(r"( not found: )(['\"]).*", r"\1<omitted output>", stripped)
    stripped = re.sub(r"(result(?:ed)? in )(['\"]).*", r"\1<omitted output>", stripped, flags=re.IGNORECASE)
    if len(stripped) > 220:
        stripped = f"{stripped[:217].rstrip()}..."
    return stripped


def structured_summary_lines(lines: list[str]) -> list[str]:
    assembled: list[str] = []
    seen: set[str] = set()

    def append_block(block: list[str], *, allow_gap: bool = False) -> None:
        nonlocal assembled
        block = [line for line in block if line]
        if not block:
            return
        if allow_gap and assembled and assembled[-1] != "...":
            assembled.append("...")
        for line in block:
            if line in seen:
                continue
            assembled.append(line)
            seen.add(line)

    traceback_header = next((line for line in lines if line.startswith("Traceback (most recent call last):")), "")
    if traceback_header:
        append_block([traceback_header])

    for block in user_code_frame_blocks(lines):
        append_block(block, allow_gap=bool(assembled))

    context_markers = exception_context_markers(lines)
    if context_markers:
        append_block(context_markers, allow_gap=bool(assembled))

    exception_body = exception_body_block(lines)
    if exception_body:
        append_block(exception_body, allow_gap=bool(assembled))

    captured_blocks = captured_output_blocks(lines)
    for block in captured_blocks:
        append_block(block, allow_gap=bool(assembled))

    max_lines = 24
    if assembled:
        return assembled[:max_lines]
    return []


def user_code_frame_blocks(lines: list[str]) -> list[list[str]]:
    blocks: list[list[str]] = []
    file_indexes = [index for index, line in enumerate(lines) if line.startswith('File "')]
    for index in file_indexes:
        if not is_user_code_frame(lines[index]):
            continue
        block = [lines[index]]
        cursor = index + 1
        while cursor < len(lines):
            line = lines[cursor]
            if line.startswith('File "') or is_captured_output_header(line):
                break
            if is_exception_start(line):
                break
            block.append(line)
            cursor += 1
        blocks.append(block[:3])
    return blocks


def exception_body_block(lines: list[str]) -> list[str]:
    start = -1
    for index in range(len(lines) - 1, -1, -1):
        if is_exception_start(lines[index]):
            start = index
            break
    if start < 0:
        return []
    block = [lines[start]]
    cursor = start + 1
    while cursor < len(lines):
        line = lines[cursor]
        if line.startswith('File "') or is_captured_output_header(line):
            break
        block.append(line)
        cursor += 1
    return block[:5]


def captured_output_blocks(lines: list[str]) -> list[list[str]]:
    blocks: list[list[str]] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not is_captured_output_header(line):
            index += 1
            continue
        block = [line]
        cursor = index + 1
        while cursor < len(lines):
            candidate = lines[cursor]
            if is_captured_output_header(candidate):
                break
            if candidate.startswith('File "') and is_user_code_frame(candidate):
                break
            if candidate == "Traceback (most recent call last):":
                break
            if is_exception_context_marker(candidate):
                break
            block.append(candidate)
            cursor += 1
        blocks.append(block[:5])
        index = cursor
    return blocks


def exception_context_markers(lines: list[str]) -> list[str]:
    return [line for line in lines if is_exception_context_marker(line)][:3]


def is_user_code_frame(line: str) -> bool:
    match = re.match(r'^File "([^"]+)"', line)
    if match is None:
        return False
    path = match.group(1)
    stdlib_markers = (
        "/Cellar/python@",
        "/Frameworks/Python.framework/",
        "/lib/python",
        "/site-packages/",
        "/asyncio/",
        "/unittest/",
    )
    return not any(marker in path for marker in stdlib_markers)


def is_exception_start(line: str) -> bool:
    return bool(
        re.match(
            r"^(?:AssertionError|[A-Za-z_][\w.]*(?:Error|Exception|Failure|Exit|Interrupt|Warning))(?:\b|:)",
            line,
        )
    )


def is_exception_context_marker(line: str) -> bool:
    lowered = line.strip().lower()
    return "during handling of the above exception" in lowered or "the above exception was the direct cause" in lowered


def is_captured_output_header(line: str) -> bool:
    lowered = line.strip().lower()
    return (
        lowered.startswith("captured stdout")
        or lowered.startswith("captured stderr")
        or lowered.startswith("captured log")
        or lowered in {"stdout:", "stderr:"}
    )


def looks_like_terminal_chrome(line: str) -> bool:
    if "RESULT_SERVICES=" in line or "Run tests for" in line or "Filter targets..." in line:
        return True
    box_chars = "╭╮╰╯│▊▎▔▁▄▅▇"
    box_count = sum(1 for char in line if char in box_chars)
    if box_count >= 4:
        return True
    if len(line) >= 40 and sum(1 for char in line if char == " ") > len(line) * 0.55 and box_count >= 1:
        return True
    return False
