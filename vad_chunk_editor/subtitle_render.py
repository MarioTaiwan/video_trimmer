from __future__ import annotations

import math
from pathlib import Path

from project import Chunk
from subtitles import (
    OutputSubtitleCue,
    SubtitleRenderSettings,
    SubtitleState,
    map_source_cues_to_output,
)


def selected_track_cues(state: SubtitleState, track: str):
    if track == "primary":
        return state.primary_cues
    if track == "translation":
        return state.translation_cues
    return []


def selected_tracks(settings: SubtitleRenderSettings) -> list[str]:
    tracks = [settings.first_track]
    if (
        settings.second_track != "none"
        and settings.second_track != settings.first_track
    ):
        tracks.append(settings.second_track)
    return [track for track in tracks if track in ("primary", "translation")]


def _estimated_text_width(text: str, font_size: int) -> int:
    width = 0.0
    for char in text.replace("\n", " "):
        if char.isspace():
            width += font_size * 0.33
        elif ord(char) > 0x2FF:
            width += font_size * 1.0
        elif char in "MW@#%&":
            width += font_size * 0.82
        else:
            width += font_size * 0.56
    return max(1, round(width))


def _estimated_wrapped_lines(
    text: str,
    font_size: int,
    available_width: int,
    overflow: str,
) -> int:
    if overflow != "wrap":
        return 1

    logical_lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    total = 0

    for line in logical_lines:
        line = line.strip()
        if not line:
            total += 1
            continue

        width = _estimated_text_width(line, font_size)
        total += max(1, math.ceil(width / max(1, available_width)))

    # A subtitle that needs more than three lines is better handled by the
    # running-text option. Capping here prevents the banner from consuming
    # most of the video frame.
    return max(1, min(3, total))


def subtitle_layout_metrics(
    video_width: int,
    video_height: int,
    font_size: int,
    texts: list[str],
    overflow: str = "wrap",
) -> tuple[int, list[int], int, list[int]]:
    """Return subtitle area height, vertical margins, LR margin and line counts.

    The banner/reserved area is based primarily on the selected font size and
    how many lines the actual subtitle content is expected to need. It is no
    longer allocated as a fixed large percentage of the movie height.
    """
    font_size = max(12, int(font_size))
    texts = list(texts) or [""]
    texts = texts[:2]

    margin_lr = max(20, round(video_width * 0.035))
    available_width = max(120, video_width - 2 * margin_lr)

    line_counts = [
        _estimated_wrapped_lines(
            text,
            font_size,
            available_width,
            overflow,
        )
        for text in texts
    ]

    line_height = max(font_size + 4, round(font_size * 1.28))
    vertical_padding = max(8, round(font_size * 0.36))
    track_gap = max(4, round(font_size * 0.18))

    content_height = sum(count * line_height for count in line_counts)
    if len(line_counts) > 1:
        content_height += track_gap * (len(line_counts) - 1)

    requested = 2 * vertical_padding + content_height

    # Keep very large fonts/wrapped subtitles bounded so the content cannot
    # consume essentially the whole picture.
    maximum = max(60, round(video_height * 0.44))
    area_height = max(
        round(font_size * 1.75),
        min(requested, maximum),
    )

    # ASS alignment=2 means bottom-center. MarginV is therefore the distance
    # from the bottom of the frame to the bottom of each track's text block.
    margins: list[int] = [0] * len(line_counts)
    below = vertical_padding

    for index in range(len(line_counts) - 1, -1, -1):
        margins[index] = below
        below += line_counts[index] * line_height
        if index > 0:
            below += track_gap

    return area_height, margins, margin_lr, line_counts


def subtitle_area_height(
    video_height: int,
    font_size: int,
    track_count: int,
    overflow: str = "wrap",
    video_width: int | None = None,
    texts: list[str] | None = None,
) -> int:
    """Compatibility wrapper used by the preview and older callers."""
    width = video_width or round(video_height * 16 / 9)
    sample_texts = list(texts or [""] * max(1, min(2, track_count)))
    area_height, _, _, _ = subtitle_layout_metrics(
        width,
        video_height,
        font_size,
        sample_texts,
        overflow,
    )
    return area_height


def _ass_time(seconds: float) -> str:
    total_cs = max(0, round(float(seconds) * 100))
    hours, rem = divmod(total_cs, 360000)
    minutes, rem = divmod(rem, 6000)
    secs, cs = divmod(rem, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


def _escape_ass_text(text: str) -> str:
    return (
        text.replace("\\", r"\\")
        .replace("{", r"\{")
        .replace("}", r"\}")
        .replace("\r\n", r"\N")
        .replace("\r", r"\N")
        .replace("\n", r"\N")
    )


def _style_line(name: str, font_size: int, margin_lr: int, margin_v: int) -> str:
    return (
        f"Style: {name},Microsoft JhengHei,{font_size},"
        "&H00FFFFFF,&H000000FF,&H00101010,&H00000000,"
        "0,0,0,0,100,100,0,0,1,2,0,2,"
        f"{margin_lr},{margin_lr},{margin_v},1"
    )


def build_ass_document(
    state: SubtitleState,
    chunks: list[Chunk],
    width: int,
    height: int,
) -> tuple[str, int, int]:
    settings = state.render_settings
    tracks = selected_tracks(settings)

    mapped_tracks: list[list[OutputSubtitleCue]] = [
        map_source_cues_to_output(selected_track_cues(state, track), chunks)
        for track in tracks
    ]

    # Size each track from the widest/most demanding cue in that track.
    representative_texts: list[str] = []
    for mapped in mapped_tracks:
        if not mapped:
            representative_texts.append("")
            continue

        if settings.overflow == "wrap":
            representative = max(
                (cue.text for cue in mapped),
                key=lambda text: _estimated_text_width(text, settings.font_size),
            )
        else:
            representative = max(
                (cue.text for cue in mapped),
                key=lambda text: len(text),
            )
        representative_texts.append(representative)

    area_height, margins, margin_lr, _ = subtitle_layout_metrics(
        width,
        height,
        settings.font_size,
        representative_texts,
        settings.overflow,
    )

    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        f"WrapStyle: {0 if settings.overflow == 'wrap' else 2}",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
    ]

    style_names: list[str] = []
    for index, margin_v in enumerate(margins):
        name = "First" if index == 0 else "Second"
        style_names.append(name)
        lines.append(
            _style_line(name, settings.font_size, margin_lr, margin_v)
        )

    lines.extend([
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text",
    ])

    available_width = max(100, width - 2 * margin_lr)
    area_top = height - area_height
    event_count = 0

    for track_index, mapped in enumerate(mapped_tracks):
        style = style_names[min(track_index, len(style_names) - 1)]
        margin_v = margins[min(track_index, len(margins) - 1)]

        for cue in mapped:
            text = _escape_ass_text(cue.text.strip())
            if not text:
                continue

            if (
                settings.overflow == "scroll"
                and _estimated_text_width(cue.text, settings.font_size)
                > available_width
            ):
                estimated = _estimated_text_width(
                    cue.text,
                    settings.font_size,
                )
                y = max(
                    area_top + settings.font_size,
                    height - margin_v - settings.font_size // 2,
                )
                x1 = width + 20
                x2 = -estimated - 20
                override = (
                    r"{\an4\q2"
                    + f"\\clip(0,{area_top},{width},{height})"
                    + f"\\move({x1},{y},{x2},{y})"
                    + "}"
                )
                text = override + text

            lines.append(
                "Dialogue: 0,"
                f"{_ass_time(cue.start)},{_ass_time(cue.end)},"
                f"{style},,0,0,0,,{text}"
            )
            event_count += 1

    return "\n".join(lines) + "\n", event_count, area_height


def escape_filter_path(path: str) -> str:
    return (
        str(Path(path))
        .replace("\\", "/")
        .replace(":", r"\:")
        .replace("'", r"\'")
    )


def subtitle_video_filter(
    input_label: str,
    output_label: str,
    ass_path: str,
    settings: SubtitleRenderSettings,
    width: int,
    height: int,
    area_height: int,
) -> str:
    escaped = escape_filter_path(ass_path)

    if settings.layout == "below":
        video_height = max(2, height - area_height)
        video_height -= video_height % 2
        return (
            f"[{input_label}]"
            f"scale=w=-2:h={video_height},"
            f"pad=w={width}:h={height}:x=(ow-iw)/2:y=0:color=black,"
            f"ass=filename='{escaped}'"
            f"[{output_label}]"
        )

    return (
        f"[{input_label}]"
        f"drawbox=x=0:y=ih-{area_height}:w=iw:h={area_height}:"
        "color=black@0.55:t=fill,"
        f"ass=filename='{escaped}'"
        f"[{output_label}]"
    )
