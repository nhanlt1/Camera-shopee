from __future__ import annotations


def format_minimized_window_title(
    line_a: str, line_b: str, *, max_len: int = 120
) -> str:
    base = "Pack Recorder"
    tail = f"{line_a} | {line_b}".strip()
    if not tail.replace("|", "").strip():
        return base
    s = f"{base} — {tail}"
    return s if len(s) <= max_len else s[: max_len - 1] + "…"
