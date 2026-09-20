from __future__ import annotations

from pathlib import Path

import torch
from PySide6.QtCore import QThread, Signal

from audio import extract_audio_to_wav, load_pcm16_mono_wav
from project import SpeechRegion


class VADWorker(QThread):
    finished_regions = Signal(object)
    failed = Signal(str)
    progress_text = Signal(str)

    def __init__(self, video_path: str, parent=None):
        super().__init__(parent)
        self.video_path = video_path

    def run(self) -> None:
        temp_wav: str | None = None

        try:
            self.progress_text.emit("Extracting audio with FFmpeg…")
            temp_wav = extract_audio_to_wav(self.video_path)

            self.progress_text.emit("Loading audio…")
            wav = load_pcm16_mono_wav(temp_wav)

            self.progress_text.emit("Loading Silero VAD…")
            torch.set_num_threads(1)

            from silero_vad import load_silero_vad, get_speech_timestamps

            model = load_silero_vad()

            self.progress_text.emit("Detecting speech…")
            timestamps = get_speech_timestamps(
                wav,
                model,
                sampling_rate=16_000,
                return_seconds=True,
            )

            regions = [
                SpeechRegion(float(item["start"]), float(item["end"]))
                for item in timestamps
                if float(item["end"]) > float(item["start"])
            ]

            self.finished_regions.emit(regions)

        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            if temp_wav:
                Path(temp_wav).unlink(missing_ok=True)
