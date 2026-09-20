from __future__ import annotations

from dataclasses import dataclass, field
import re

from project import Chunk


@dataclass
class SubtitleCue:
    # Times are always in the ORIGINAL SOURCE VIDEO timeline.
    source_start: float
    source_end: float
    text: str


@dataclass
class SubtitleRenderSettings:
    # primary = original/detected-language track; translation = translated track
    first_track: str = "primary"
    second_track: str = "translation"
    # banner = overlay on video; below = shrink video and reserve lower area
    layout: str = "banner"
    font_size: int = 36
    # wrap = normal line wrapping; scroll = horizontal marquee for long text
    overflow: str = "wrap"


@dataclass
class SubtitleState:
    primary_language: str = "en"
    translation_language: str = "zh"
    primary_cues: list[SubtitleCue] = field(default_factory=list)
    translation_cues: list[SubtitleCue] = field(default_factory=list)
    render_settings: SubtitleRenderSettings = field(
        default_factory=SubtitleRenderSettings
    )


@dataclass
class OutputSubtitleCue:
    # Times are in the CURRENT FINAL OUTPUT timeline.
    start: float
    end: float
    text: str
    chunk_index: int
    source_start: float
    source_end: float
    source_index: int


def language_name(code: str) -> str:
    return {"en": "English", "zh": "Chinese"}.get(code, code)


def map_source_cues_to_output(
    cues: list[SubtitleCue],
    chunks: list[Chunk],
    minimum_duration: float = 0.02,
) -> list[OutputSubtitleCue]:
    """Map source-timed subtitles through the current ordered chunk list.

    Reordering chunks therefore reorders subtitles automatically, while trims
    clip subtitle timing to the retained source interval.
    """
    result: list[OutputSubtitleCue] = []
    output_cursor = 0.0

    indexed = sorted(
        enumerate(cues),
        key=lambda pair: (pair[1].source_start, pair[1].source_end),
    )

    for chunk_index, chunk in enumerate(chunks):
        for source_index, cue in indexed:
            overlap_start = max(float(chunk.start), float(cue.source_start))
            overlap_end = min(float(chunk.end), float(cue.source_end))

            if overlap_end - overlap_start < minimum_duration:
                continue

            result.append(
                OutputSubtitleCue(
                    start=output_cursor + (overlap_start - chunk.start),
                    end=output_cursor + (overlap_end - chunk.start),
                    text=cue.text,
                    chunk_index=chunk_index,
                    source_start=overlap_start,
                    source_end=overlap_end,
                    source_index=source_index,
                )
            )

        output_cursor += chunk.duration

    return result


def map_output_cues_to_source(
    output_cues: list[SubtitleCue],
    chunks: list[Chunk],
    minimum_duration: float = 0.02,
) -> list[SubtitleCue]:
    """Convert an SRT timed to the final output back into source-video timing.

    A subtitle that crosses a chunk boundary is split so each part remains
    attached to the source interval from which it came.
    """
    ranges: list[tuple[float, float, Chunk]] = []
    cursor = 0.0

    for chunk in chunks:
        ranges.append((cursor, cursor + chunk.duration, chunk))
        cursor += chunk.duration

    result: list[SubtitleCue] = []

    for cue in output_cues:
        for out_start, out_end, chunk in ranges:
            overlap_start = max(cue.source_start, out_start)
            overlap_end = min(cue.source_end, out_end)

            if overlap_end - overlap_start < minimum_duration:
                continue

            source_start = chunk.start + (overlap_start - out_start)
            source_end = chunk.start + (overlap_end - out_start)

            result.append(
                SubtitleCue(
                    source_start=source_start,
                    source_end=source_end,
                    text=cue.text,
                )
            )

    return result


def _parse_srt_timestamp(value: str) -> float:
    match = re.fullmatch(
        r"\s*(\d+):(\d{2}):(\d{2})[,.](\d{1,3})\s*",
        value,
    )
    if not match:
        raise ValueError(f"Invalid SRT timestamp: {value}")

    hours = int(match.group(1))
    minutes = int(match.group(2))
    seconds = int(match.group(3))
    millis_text = match.group(4).ljust(3, "0")[:3]
    millis = int(millis_text)

    return hours * 3600 + minutes * 60 + seconds + millis / 1000.0


def format_srt_timestamp(seconds: float) -> str:
    total_ms = max(0, round(float(seconds) * 1000))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def parse_srt(text: str) -> list[SubtitleCue]:
    """Parse SRT text.

    The returned SubtitleCue objects temporarily use source_start/source_end
    as the SRT timeline. map_output_cues_to_source() then converts them into
    source-video timing.
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []

    blocks = re.split(r"\n\s*\n", normalized)
    cues: list[SubtitleCue] = []

    for block in blocks:
        lines = [line.rstrip() for line in block.split("\n")]
        timing_index = next(
            (i for i, line in enumerate(lines) if "-->" in line),
            None,
        )
        if timing_index is None:
            continue

        timing = lines[timing_index]
        left, right = timing.split("-->", 1)
        start = _parse_srt_timestamp(left)
        end = _parse_srt_timestamp(right.split()[0])

        cue_text = "\n".join(lines[timing_index + 1:]).strip()
        if end <= start or not cue_text:
            continue

        cues.append(SubtitleCue(start, end, cue_text))

    if not cues and "-->" in normalized:
        raise ValueError("The SRT timing lines could not be parsed.")

    return cues


def render_srt(cues: list[OutputSubtitleCue]) -> str:
    blocks: list[str] = []

    for index, cue in enumerate(cues, start=1):
        if not cue.text.strip():
            continue
        blocks.append(
            f"{index}\n"
            f"{format_srt_timestamp(cue.start)} --> "
            f"{format_srt_timestamp(cue.end)}\n"
            f"{cue.text.strip()}"
        )

    return "\n\n".join(blocks) + ("\n" if blocks else "")
