from __future__ import annotations

import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np
import torch


SAMPLE_RATE = 16_000


class FFmpegNotFoundError(RuntimeError):
    pass


def find_ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise FFmpegNotFoundError(
            "FFmpeg was not found. Install FFmpeg and make sure ffmpeg.exe "
            "is available on your Windows PATH."
        )
    return exe


def extract_audio_to_wav(video_path: str) -> str:
    """Extract mono 16-kHz 16-bit PCM WAV audio to a temporary file."""
    ffmpeg = find_ffmpeg()

    temp = tempfile.NamedTemporaryFile(
        prefix="vad_chunk_editor_",
        suffix=".wav",
        delete=False,
    )
    temp.close()

    command = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        video_path,
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(SAMPLE_RATE),
        "-c:a",
        "pcm_s16le",
        temp.name,
    ]

    try:
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.CalledProcessError as exc:
        Path(temp.name).unlink(missing_ok=True)
        error = exc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"FFmpeg could not extract the audio.\n\n{error}") from exc

    return temp.name


def load_pcm16_mono_wav(path: str) -> torch.Tensor:
    """Load our temporary WAV without relying on torchaudio."""
    with wave.open(path, "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        sample_rate = wav_file.getframerate()
        frames = wav_file.readframes(wav_file.getnframes())

    if channels != 1 or sample_width != 2 or sample_rate != SAMPLE_RATE:
        raise RuntimeError(
            "Unexpected temporary WAV format. Expected mono, 16-bit PCM, 16 kHz."
        )

    samples = np.frombuffer(frames, dtype="<i2").astype(np.float32)
    samples /= 32768.0
    return torch.from_numpy(samples)
