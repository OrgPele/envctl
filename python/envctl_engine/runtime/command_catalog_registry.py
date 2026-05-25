from __future__ import annotations


def unique_tokens(*, registry_name: str, tokens: tuple[str, ...]) -> set[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for token in tokens:
        if token in seen and token not in duplicates:
            duplicates.append(token)
            continue
        seen.add(token)
    if duplicates:
        joined = ", ".join(duplicates)
        raise RuntimeError(f"Duplicate tokens in {registry_name}: {joined}")
    return seen


def unique_mapping(*, registry_name: str, pairs: tuple[tuple[str, str], ...]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    duplicates: list[str] = []
    for key, value in pairs:
        if key in mapping:
            if key not in duplicates:
                duplicates.append(key)
            continue
        mapping[key] = value
    if duplicates:
        joined = ", ".join(duplicates)
        raise RuntimeError(f"Duplicate keys in {registry_name}: {joined}")
    return mapping
