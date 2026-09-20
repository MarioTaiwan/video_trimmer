from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass
class SpeechRegion:
    start: float
    end: float


@dataclass
class Chunk:
    start: float
    end: float
    # These remain unchanged when a user trims a VAD-created chunk.
    # Manually inserted chunks have no original VAD extent.
    vad_start: float | None = None
    vad_end: float | None = None

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


def build_chunks(
    speech_regions: Iterable[SpeechRegion],
    minimum_quiet_duration: float,
) -> list[Chunk]:
    """Group VAD speech regions into chunks.

    A new chunk starts only when the non-speech gap between two consecutive
    speech regions is >= minimum_quiet_duration.
    """
    regions = sorted(speech_regions, key=lambda r: r.start)
    if not regions:
        return []

    threshold = max(0.0, float(minimum_quiet_duration))

    chunks: list[Chunk] = []
    current_start = regions[0].start
    current_end = regions[0].end

    for region in regions[1:]:
        gap = region.start - current_end

        if gap >= threshold:
            chunks.append(
                Chunk(
                    current_start,
                    current_end,
                    vad_start=current_start,
                    vad_end=current_end,
                )
            )
            current_start = region.start
            current_end = region.end
        else:
            current_end = max(current_end, region.end)

    chunks.append(
        Chunk(
            current_start,
            current_end,
            vad_start=current_start,
            vad_end=current_end,
        )
    )
    return chunks


def move_chunk(chunks: list[Chunk], source_index: int, target_index: int) -> int:
    if not 0 <= source_index < len(chunks):
        raise IndexError("Chunk does not exist.")
    if not 0 <= target_index < len(chunks):
        raise IndexError("Target chunk position does not exist.")
    if source_index == target_index:
        return target_index

    chunk = chunks.pop(source_index)
    chunks.insert(target_index, chunk)
    return target_index


def insert_chunk(
    chunks: list[Chunk],
    target_index: int,
    start: float,
    end: float,
) -> int:
    if end <= start:
        raise ValueError("Chunk end must be later than chunk start.")
    target_index = max(0, min(int(target_index), len(chunks)))
    # A manually inserted chunk has no original VAD position.
    chunks.insert(
        target_index,
        Chunk(float(start), float(end), vad_start=None, vad_end=None),
    )
    return target_index


def delete_chunk(chunks: list[Chunk], chunk_index: int) -> None:
    if not 0 <= chunk_index < len(chunks):
        raise IndexError("Chunk does not exist.")
    del chunks[chunk_index]


def _merged_vad_extent(a: Chunk, b: Chunk) -> tuple[float | None, float | None]:
    # If either side was manually created, do not claim the merged interval
    # has a trustworthy original VAD extent.
    if (
        a.vad_start is None
        or a.vad_end is None
        or b.vad_start is None
        or b.vad_end is None
    ):
        return None, None

    return min(a.vad_start, b.vad_start), max(a.vad_end, b.vad_end)


def merge_chunk_with_previous(chunks: list[Chunk], chunk_index: int) -> int:
    """Merge a chunk with its previous output neighbor."""
    if chunk_index <= 0 or chunk_index >= len(chunks):
        raise IndexError(
            "A chunk can only be merged with an existing previous chunk."
        )

    previous = chunks[chunk_index - 1]
    current = chunks[chunk_index]
    vad_start, vad_end = _merged_vad_extent(previous, current)

    previous.start = min(previous.start, current.start)
    previous.end = max(previous.end, current.end)
    previous.vad_start = vad_start
    previous.vad_end = vad_end

    del chunks[chunk_index]
    return chunk_index - 1


def merge_chunk_with_next(chunks: list[Chunk], chunk_index: int) -> int:
    if chunk_index < 0 or chunk_index >= len(chunks) - 1:
        raise IndexError(
            "A chunk can only be merged with an existing next chunk."
        )

    current = chunks[chunk_index]
    following = chunks[chunk_index + 1]
    vad_start, vad_end = _merged_vad_extent(current, following)

    current.start = min(current.start, following.start)
    current.end = max(current.end, following.end)
    current.vad_start = vad_start
    current.vad_end = vad_end

    del chunks[chunk_index + 1]
    return chunk_index
