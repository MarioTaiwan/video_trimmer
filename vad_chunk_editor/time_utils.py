from __future__ import annotations


def format_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    total_ms = round(seconds * 1000)
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)

    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"
    return f"{minutes:02d}:{secs:02d}.{millis:03d}"


def parse_time(text: str) -> float:
    """Parse seconds, MM:SS(.sss), or HH:MM:SS(.sss)."""
    value = text.strip().lower()
    if value.endswith("s"):
        value = value[:-1].strip()
    if not value:
        raise ValueError("Time is empty.")

    parts = value.split(":")
    try:
        if len(parts) == 1:
            seconds = float(parts[0])
        elif len(parts) == 2:
            minutes = int(parts[0])
            seconds = minutes * 60 + float(parts[1])
        elif len(parts) == 3:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = hours * 3600 + minutes * 60 + float(parts[2])
        else:
            raise ValueError
    except ValueError as exc:
        raise ValueError(
            "Use seconds, MM:SS.mmm, or HH:MM:SS.mmm."
        ) from exc

    if seconds < 0:
        raise ValueError("Time cannot be negative.")
    return seconds
