from __future__ import annotations

import json
import os
from pathlib import Path

from project import Chunk, SpeechRegion
from subtitles import SubtitleCue, SubtitleRenderSettings, SubtitleState


PROJECT_FORMAT = "vad-chunk-editor-project"
PROJECT_VERSION = 2


def _safe_relative_path(video_path: str, project_path: str) -> str | None:
    try:
        return os.path.relpath(
            Path(video_path).resolve(),
            Path(project_path).resolve().parent,
        )
    except (OSError, ValueError):
        return None


def save_project_file(
    project_path: str,
    video_path: str,
    minimum_quiet_duration: float,
    speech_regions: list[SpeechRegion],
    chunks: list[Chunk],
    subtitles: SubtitleState,
) -> None:
    path = Path(project_path)
    relative_video = _safe_relative_path(video_path, project_path)

    data = {
        "format": PROJECT_FORMAT,
        "version": PROJECT_VERSION,
        "video": {
            "absolute_path": str(Path(video_path).resolve()),
            "relative_path": relative_video,
        },
        "minimum_quiet_duration": float(minimum_quiet_duration),
        "speech_regions": [
            {"start": float(region.start), "end": float(region.end)}
            for region in speech_regions
        ],
        "chunks": [
            {
                "start": float(chunk.start),
                "end": float(chunk.end),
                "vad_start": (
                    None if chunk.vad_start is None else float(chunk.vad_start)
                ),
                "vad_end": (
                    None if chunk.vad_end is None else float(chunk.vad_end)
                ),
            }
            for chunk in chunks
        ],
        "subtitles": {
            "primary_language": subtitles.primary_language,
            "translation_language": subtitles.translation_language,
            "primary_cues": [
                {
                    "source_start": float(cue.source_start),
                    "source_end": float(cue.source_end),
                    "text": cue.text,
                }
                for cue in subtitles.primary_cues
            ],
            "translation_cues": [
                {
                    "source_start": float(cue.source_start),
                    "source_end": float(cue.source_end),
                    "text": cue.text,
                }
                for cue in subtitles.translation_cues
            ],
            "render_settings": {
                "first_track": subtitles.render_settings.first_track,
                "second_track": subtitles.render_settings.second_track,
                "layout": subtitles.render_settings.layout,
                "font_size": subtitles.render_settings.font_size,
                "overflow": subtitles.render_settings.overflow,
            },
        },
    }

    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_project_file(project_path: str) -> dict:
    path = Path(project_path)
    data = json.loads(path.read_text(encoding="utf-8"))

    if data.get("format") != PROJECT_FORMAT:
        raise ValueError("This is not a VAD Chunk Editor project file.")

    if int(data.get("version", 0)) > PROJECT_VERSION:
        raise ValueError(
            "This project was created by a newer version of the editor."
        )

    video = data.get("video", {})
    absolute = video.get("absolute_path")
    relative = video.get("relative_path")

    resolved_video: str | None = None
    if absolute and Path(absolute).exists():
        resolved_video = str(Path(absolute))
    elif relative:
        candidate = (path.parent / relative).resolve()
        if candidate.exists():
            resolved_video = str(candidate)

    speech_regions = [
        SpeechRegion(float(item["start"]), float(item["end"]))
        for item in data.get("speech_regions", [])
    ]

    chunks = [
        Chunk(
            start=float(item["start"]),
            end=float(item["end"]),
            vad_start=(
                None
                if item.get("vad_start") is None
                else float(item["vad_start"])
            ),
            vad_end=(
                None
                if item.get("vad_end") is None
                else float(item["vad_end"])
            ),
        )
        for item in data.get("chunks", [])
    ]

    subtitle_data = data.get("subtitles", {})
    subtitle_state = SubtitleState(
        primary_language=subtitle_data.get("primary_language", "en"),
        translation_language=subtitle_data.get("translation_language", "zh"),
        primary_cues=[
            SubtitleCue(
                float(item["source_start"]),
                float(item["source_end"]),
                str(item.get("text", "")),
            )
            for item in subtitle_data.get("primary_cues", [])
        ],
        translation_cues=[
            SubtitleCue(
                float(item["source_start"]),
                float(item["source_end"]),
                str(item.get("text", "")),
            )
            for item in subtitle_data.get("translation_cues", [])
        ],
        render_settings=SubtitleRenderSettings(
            first_track=subtitle_data.get("render_settings", {}).get(
                "first_track", "primary"
            ),
            second_track=subtitle_data.get("render_settings", {}).get(
                "second_track", "translation"
            ),
            layout=subtitle_data.get("render_settings", {}).get(
                "layout", "banner"
            ),
            font_size=int(
                subtitle_data.get("render_settings", {}).get("font_size", 36)
            ),
            overflow=subtitle_data.get("render_settings", {}).get(
                "overflow", "wrap"
            ),
        ),
    )

    return {
        "video_path": resolved_video,
        "saved_video_path": absolute,
        "minimum_quiet_duration": float(
            data.get("minimum_quiet_duration", 0.70)
        ),
        "speech_regions": speech_regions,
        "chunks": chunks,
        "subtitles": subtitle_state,
    }
