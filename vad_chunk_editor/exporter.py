from __future__ import annotations

import copy
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from audio import find_ffmpeg
from project import Chunk
from subtitle_render import build_ass_document, subtitle_video_filter
from subtitles import SubtitleState


def find_ffprobe(ffmpeg_path: str) -> str:
    sibling = Path(ffmpeg_path).with_name(
        "ffprobe.exe" if Path(ffmpeg_path).suffix.lower() == ".exe" else "ffprobe"
    )
    if sibling.exists():
        return str(sibling)
    found = shutil.which("ffprobe")
    if found:
        return found
    raise RuntimeError("FFprobe was not found next to FFmpeg or on PATH.")


def probe_video_size(video_path: str, ffmpeg_path: str) -> tuple[int, int]:
    ffprobe = find_ffprobe(ffmpeg_path)
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "json",
            video_path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.decode("utf-8", errors="replace").strip()
            or "FFprobe could not read the video dimensions."
        )
    data = json.loads(result.stdout.decode("utf-8", errors="replace"))
    streams = data.get("streams", [])
    if not streams:
        raise RuntimeError("The source video has no readable video stream.")
    return int(streams[0]["width"]), int(streams[0]["height"])


def build_filter_script(
    chunks: list[Chunk],
    ass_path: str | None = None,
    subtitle_state: SubtitleState | None = None,
    width: int | None = None,
    height: int | None = None,
    subtitle_area_height_px: int | None = None,
) -> str:
    """Build an FFmpeg filter graph for chunk concatenation and subtitles."""
    if not chunks:
        raise ValueError("There are no chunks to export.")

    lines: list[str] = []
    concat_inputs: list[str] = []

    for index, chunk in enumerate(chunks):
        start = max(0.0, float(chunk.start))
        end = max(start, float(chunk.end))
        if end <= start:
            raise ValueError(f"Chunk {index + 1} has zero duration.")

        lines.append(
            f"[0:v:0]trim=start={start:.6f}:end={end:.6f},"
            f"setpts=PTS-STARTPTS[v{index}]"
        )
        lines.append(
            f"[0:a:0]atrim=start={start:.6f}:end={end:.6f},"
            f"asetpts=PTS-STARTPTS[a{index}]"
        )
        concat_inputs.append(f"[v{index}][a{index}]")

    concat_video_label = "basev" if ass_path else "outv"
    lines.append(
        "".join(concat_inputs)
        + f"concat=n={len(chunks)}:v=1:a=1[{concat_video_label}][outa]"
    )

    if ass_path:
        if (
            subtitle_state is None
            or width is None
            or height is None
            or subtitle_area_height_px is None
        ):
            raise ValueError("Subtitle export settings are incomplete.")
        lines.append(
            subtitle_video_filter(
                "basev",
                "outv",
                ass_path,
                subtitle_state.render_settings,
                width,
                height,
                subtitle_area_height_px,
            )
        )

    return ";\n".join(lines)


class ExportWorker(QThread):
    completed = Signal(str)
    failed = Signal(str)
    progress_text = Signal(str)

    def __init__(
        self,
        video_path: str,
        output_path: str,
        chunks: list[Chunk],
        subtitle_state: SubtitleState | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.video_path = video_path
        self.output_path = output_path
        self.chunks = [
            Chunk(c.start, c.end, c.vad_start, c.vad_end) for c in chunks
        ]
        self.subtitle_state = copy.deepcopy(subtitle_state)

    def run(self) -> None:
        script_path: str | None = None
        ass_path: str | None = None

        try:
            ffmpeg = find_ffmpeg()
            width = height = None
            area_height = None
            subtitle_events = 0

            if self.subtitle_state is not None:
                width, height = probe_video_size(self.video_path, ffmpeg)
                ass_text, subtitle_events, area_height = build_ass_document(
                    self.subtitle_state,
                    self.chunks,
                    width,
                    height,
                )

                if subtitle_events:
                    with tempfile.NamedTemporaryFile(
                        mode="w",
                        suffix=".ass",
                        prefix="vad_chunk_subtitles_",
                        encoding="utf-8-sig",
                        delete=False,
                    ) as handle:
                        handle.write(ass_text)
                        ass_path = handle.name

            filter_script = build_filter_script(
                self.chunks,
                ass_path=ass_path,
                subtitle_state=self.subtitle_state,
                width=width,
                height=height,
                subtitle_area_height_px=area_height,
            )

            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".ffscript",
                prefix="vad_chunk_export_",
                encoding="utf-8",
                delete=False,
            ) as handle:
                handle.write(filter_script)
                script_path = handle.name

            if subtitle_events:
                self.progress_text.emit(
                    "Rendering trimmed video and burned-in subtitles with FFmpeg…"
                )
            else:
                self.progress_text.emit("Rendering trimmed video with FFmpeg…")

            command = [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                self.video_path,
                "-/filter_complex",
                script_path,
                "-map",
                "[outv]",
                "-map",
                "[outa]",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "18",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-movflags",
                "+faststart",
                self.output_path,
            ]

            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )

            if result.returncode != 0:
                Path(self.output_path).unlink(missing_ok=True)
                error = result.stderr.decode("utf-8", errors="replace").strip()
                raise RuntimeError(error or "FFmpeg export failed.")

            self.completed.emit(self.output_path)

        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            if script_path:
                Path(script_path).unlink(missing_ok=True)
            if ass_path:
                Path(ass_path).unlink(missing_ok=True)
