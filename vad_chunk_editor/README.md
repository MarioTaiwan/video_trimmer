# VAD Chunk Editor — MVP 5.1

MVP 5 burns the managed subtitle tracks directly into the exported MP4 and
adds a visual subtitle-appearance editor with a random-frame preview.

## Subtitle appearance

Open:

```text
Manage Subtitles… → Video Subtitle Appearance…
```

The dialog provides:

- **First subtitle:** Original or Translated
- **Second subtitle:** Original, Translated, or None
- **Placement:**
  - overlay at the bottom with a semi-transparent banner, or
  - shrink the video proportionally and reserve a black subtitle area below it
- **Font size:** 16–72 px
- **Long text:**
  - normal line wrapping, or
  - running text / horizontal marquee

When running text is selected, only subtitles that are too wide for the
available region scroll. Short subtitles remain centered.

The preview uses a randomly selected retained source frame. **Another random
frame** chooses a different frame. Changes to track order, placement, font
size, and overflow behavior are shown immediately in the preview.

## Export behavior

**Export Trimmed Video…** now:

1. trims and concatenates the current chunk sequence,
2. maps source-timed subtitles to the final edited timeline,
3. burns the selected subtitle tracks into the video,
4. outputs H.264/AAC MP4.

Subtitle timing therefore still follows chunk movement and trimming. Moving a
chunk also moves its subtitles in the burned-in export.

### Banner mode

The output keeps the original frame size. A semi-transparent dark banner is
placed over the lower part of the video and the subtitles are rendered inside
it.

### Subtitles-below mode

The output keeps the original frame size, but the video itself is scaled down
proportionally and centered in the upper portion. The lower portion becomes a
black subtitle area.

## Original and translated tracks

The previously named Primary track is shown as **Original** in the subtitle
manager. Internally it is still the detected-language track.

The subtitle appearance settings are stored in the `.vceproj` project file, so
reopening a project restores the chosen track order, placement, font size, and
text overflow mode.

## Existing features retained

- save/open `.vceproj` projects
- Split Chunks using Silero VAD
- configurable quiet-duration threshold
- ±10 s independent boundary sliders
- preview frame while trimming
- reset transition to original VAD result
- reorder/edit/insert/delete/merge chunks
- `-` and `+` transition navigation
- Whisper subtitle generation in English or Chinese
- original and translated SRT import/paste/edit/export
- final video export

## Installation

No new Python dependency is required beyond MVP 4. If installing fresh:

```text
install_windows.bat
```

If updating an older environment:

```text
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

The FFmpeg build must include the `ass`/libass subtitle filter. The full Gyan
FFmpeg package installed through WinGet normally includes it.


## MVP 5.1 subtitle rendering fixes

### Subtitle banner height

The subtitle banner/reserved area is no longer based on a large fixed
percentage of the video height.

Its height now follows:

- selected font size,
- one versus two subtitle tracks,
- estimated wrapped line count of the actual subtitle text.

For ordinary one-line bilingual subtitles, the banner is therefore much
shallower. Increasing the font size increases the banner proportionally.
Long wrapped subtitles can request additional lines, up to a bounded limit.

The live appearance preview uses the same sizing calculation as final export.

### Why a subtitle could appear twice in VLC

If a burned-in export is named:

```text
movie_trimmed.mp4
```

and the same folder contains:

```text
movie_trimmed.zh.srt
```

VLC commonly auto-loads that SRT. The result is:

1. the large/styled subtitle burned into the video by this program, plus
2. VLC's own smaller external subtitle rendering.

That second subtitle is not burned into the movie.

To reduce this problem, new SRT exports now default to names such as:

```text
movie_subtitles_zh.srt
movie_subtitles_en.srt
```

rather than sharing the `movie_trimmed` basename.

When video export finishes, the program also checks for matching sidecar SRT
files and warns if a player may auto-load them.
