from __future__ import annotations


def matches_blast_container(*, image: str, name: str) -> bool:
    image_l = image.lower()
    name_l = name.lower()
    return any(token in name_l or token in image_l for token in ("supabase", "n8n", "redis", "postgres"))
