# VAD Chunk Editor — Implementation Handoff and Reproduction Brief

This document is intended to let another developer or AI coding session reproduce the current program without relying on the original conversation.

It summarizes the **final design decisions, architecture, required behavior, compatibility fixes, and implementation constraints**.

The target state corresponds to the working **MVP 5.1** implementation.

---

# 1. Product goal

Build a lightweight Windows 11 desktop application for editing spoken videos.

The program should:

```text
Import video
    ↓
Detect speech/non-speech
    ↓
Automatically form chunks
    ↓
Allow rapid manual correction
    ↓
Rearrange/delete/merge/add chunks
    ↓
Generate/edit bilingual subtitles
    ↓
Save/reopen the editing project
    ↓
Export final MP4 with optional burned-in subtitles
```

The application is not intended to be a general Premiere-style nonlinear editor.

Its core use case is rapidly cleaning presentations, lectures, tutorials, and similar spoken recordings.

---

# 2. Technology stack

Use:

```text
Language:       Python 3.11
Desktop GUI:    PySide6 / Qt 6
Video preview:  QMediaPlayer + QVideoWidget
Speech VAD:     silero-vad
Transcription:  faster-whisper
Audio/video:    FFmpeg + FFprobe
Subtitle burn:  ASS/libass through FFmpeg
Packaging dev:  Python virtual environment
Primary OS:     Windows 11
```

Python requirements:

```text
PySide6>=6.8
numpy>=1.26
torch>=2.2
silero-vad[onnx-cpu]>=6.0
onnxruntime>=1.16.1
faster-whisper>=1.1.0
```

FFmpeg must support:

```text
libx264
AAC
filter_complex
ass/libass filter
```

---

# 3. Key architectural decision: everything is non-destructive

Never physically cut the input movie while editing.

The source movie remains unchanged.

Represent the final video as an ordered sequence of source intervals.

Core data object:

```python
@dataclass
class Chunk:
    start: float
    end: float
    vad_start: float | None = None
    vad_end: float | None = None
```

`start` and `end` are the current user-edited source-video boundaries.

`vad_start` and `vad_end` retain the original automatic VAD result.

That distinction is important because the UI supports:

```text
Reset this transition to original VAD boundary
```

Manual chunks use:

```python
vad_start = None
vad_end = None
```

---

# 4. VAD model

First extract 16-kHz mono PCM WAV using FFmpeg.

Then run Silero VAD.

Store the complete speech-region result:

```python
@dataclass
class SpeechRegion:
    start: float
    end: float
```

Do not make the VAD itself decide chunk boundaries.

Instead:

```python
gap = next_speech.start - previous_speech.end

if gap >= minimum_quiet_duration:
    create_new_chunk()
else:
    keep_speech_in_current_chunk()
```

The default minimum quiet duration is:

```text
0.70 s
```

Expose this through **Chunk Settings**.

Changing the quiet-duration threshold should regroup the already saved SpeechRegion list without rerunning Silero.

---

# 5. Main GUI

Use a `QMainWindow`.

Primary toolbar actions:

```text
Open Video
Open Project…
Save Project
Split Chunks
Chunk Settings
Manage Subtitles…
Export Trimmed Video…
```

Do not show Previous/Next Boundary buttons in the toolbar.

Use window keyboard shortcuts:

```text
- = previous transition
+ = next transition
```

The main view contains:

```text
Left:
    video preview
    boundary editor

Right:
    chunk transitions list
    interactive chunk table
```

---

# 6. Boundary/transition editor

A transition represents:

```text
previous chunk end → next chunk start
```

The user needs two independent trim controls:

```text
Previous chunk — end
Next chunk — start
```

Important behavior:

- The two controls are independent.
- Do not constrain one edge based on the other.
- They may intentionally overlap or jump backward if chunks have been reordered.
- Each slider uses a **±10 second local range**.
- For normal VAD-created chunks, center the window on the stored original VAD edge.
- If a manually edited value has moved beyond that range, recenter around the current value so the handle remains representable.

Use millisecond slider resolution:

```python
SLIDER_SCALE = 1000
```

When either slider changes:

1. update the corresponding Chunk field,
2. update the numeric time control,
3. pause video playback,
4. seek QMediaPlayer to that source frame.

Use `QSignalBlocker` while synchronizing slider/spinbox values so feedback loops do not reset the slider handle while dragging.

For Windows Qt Multimedia reliability, seek immediately and then repeat the paused seek after roughly 25 ms using `QTimer.singleShot`.

Provide:

```text
Play original around boundary
Preview resulting cut
```

For Preview resulting cut:

```text
play ~2 s before previous chunk end
seek directly to next chunk start
play ~2 s after it
```

No temporary movie render is required for this preview.

---

# 7. Transition reset

Store `vad_end` for the previous chunk and `vad_start` for the following chunk.

Right-click a transition in the transition list.

Context menu:

```text
Reset this transition to original VAD boundary
```

Reset:

```python
left.end = left.vad_end
right.start = right.vad_start
```

Disable this action if either VAD reference is unavailable.

---

# 8. Interactive chunk table

Use a `QTableWidget` with columns:

```text
Chunk | Start | End | Duration
```

The table is the main structural-editing interface.

## Reorder

The Chunk number is editable.

If row 2 changes from:

```text
2
```

to:

```text
7
```

move the actual Chunk object to index 6 and renumber the displayed sequence.

## Edit extent

Start and End are editable.

Support:

```text
seconds
MM:SS.mmm
HH:MM:SS.mmm
```

Validate:

```text
end > start
start >= 0
end <= source duration
```

## Insert chunk

Always display one empty row after the current chunks.

If Start and End are supplied:

- blank Chunk field → append,
- Chunk number supplied → insert at that output position.

## Context menu

Right-click an existing row:

```text
Merge Chunk N with previous chunk
Merge Chunk N with next chunk
Delete Chunk N
```

Merge behavior should restore the entire source interval between the chunks:

```python
merged.start = min(a.start, b.start)
merged.end = max(a.end, b.end)
```

If both chunks have valid VAD extents, merge those as well.

Otherwise set merged VAD references to `None`.

## Qt ownership trap

Do not call `setItem()` again on an existing `QTableWidgetItem`.

Correct pattern:

```python
item = table.item(row, col)

if item is None:
    item = QTableWidgetItem()
    table.setItem(row, col, item)

item.setText(text)
```

Otherwise Qt can print:

```text
QTableWidget: cannot insert an item that is already owned by another QTableWidget
```

---

# 9. Project save/load

Project extension:

```text
.vceproj
```

Store JSON.

Current project format version:

```text
2
```

Save:

```json
{
  "format": "vad-chunk-editor-project",
  "version": 2,
  "video": {
    "absolute_path": "...",
    "relative_path": "..."
  },
  "minimum_quiet_duration": 0.7,
  "speech_regions": [],
  "chunks": [],
  "subtitles": {}
}
```

For each chunk save:

```json
{
  "start": 10.0,
  "end": 20.0,
  "vad_start": 10.0,
  "vad_end": 20.0
}
```

Save both absolute and relative source-video paths.

When loading:

1. try absolute path,
2. try project-relative path,
3. if neither exists ask the user to locate the source video.

Do not embed the raw video.

---

# 10. Subtitle design: store subtitles in source-video time

This is one of the most important design decisions.

Use:

```python
@dataclass
class SubtitleCue:
    source_start: float
    source_end: float
    text: str
```

Do **not** permanently store final-output subtitle timestamps.

Instead, calculate them from the current chunk list.

Reason:

```text
source video:
    Chunk A = 10–20
    Chunk B = 40–50
```

Suppose:

```text
subtitle A = source 12–14
subtitle B = source 42–44
```

Normal output:

```text
Chunk A → output 0–10
Chunk B → output 10–20

subtitle A → output 2–4
subtitle B → output 12–14
```

If Chunk B is moved first:

```text
subtitle B → output 2–4
subtitle A → output 12–14
```

No subtitle rewrite is required.

The mapping is computed at display/export time.

---

# 11. Subtitle state

Use:

```python
@dataclass
class SubtitleRenderSettings:
    first_track: str = "primary"
    second_track: str = "translation"
    layout: str = "banner"
    font_size: int = 36
    overflow: str = "wrap"
```

and:

```python
@dataclass
class SubtitleState:
    primary_language: str = "en"
    translation_language: str = "zh"
    primary_cues: list[SubtitleCue]
    translation_cues: list[SubtitleCue]
    render_settings: SubtitleRenderSettings
```

The internally named `primary` track is presented in the UI as:

```text
Original
```

The second track is:

```text
Translation
```

---

# 12. Source-time to output-time subtitle mapping

Iterate through chunks in current output order.

Maintain:

```python
output_cursor = 0
```

For every cue that overlaps a chunk:

```python
overlap_start = max(chunk.start, cue.source_start)
overlap_end   = min(chunk.end, cue.source_end)
```

Skip if duration is negligible.

Final timing:

```python
output_start = output_cursor + overlap_start - chunk.start
output_end   = output_cursor + overlap_end   - chunk.start
```

Then:

```python
output_cursor += chunk.duration
```

This automatically handles:

- trimming,
- deletion,
- reordering,
- duplicated source intervals if manually inserted.

---

# 13. SRT import behavior

SRT export is straightforward because current output times can be calculated.

SRT import is more subtle.

Interpret imported SRT as being timed to the **current edited output timeline**.

Build output ranges for every chunk:

```text
output range 0 → chunk1.duration maps to source chunk1.start → chunk1.end
next range → chunk2
...
```

For every imported subtitle overlap, convert back into source-video time.

If an SRT cue crosses a chunk boundary, split it into source-attached pieces.

This allows:

```text
Export SRT
edit externally
Import SRT
reorder chunks later
```

without losing attachment to the source material.

---

# 14. Subtitle transcription

Use:

```python
from faster_whisper import WhisperModel
```

Current compatibility-first configuration:

```python
WhisperModel(
    "small",
    device="cpu",
    compute_type="int8",
)
```

Run:

```python
model.transcribe(
    video_path,
    language="en" or "zh",
    beam_size=5,
    vad_filter=True,
)
```

Limit language selection in the UI to:

```text
English
Chinese
```

The first run may download the model.

Run transcription in a `QThread` so the GUI remains responsive.

---

# 15. Translation workflow

Do not require a translation API.

Support a practical manual workflow.

Original tab:

```text
Copy Original Text
```

Copy one subtitle per line.

User can paste into Google Translate.

Translation tab:

```text
Paste Translation SRT / Text…
```

If plain text is pasted:

- strip blank lines,
- require exactly one line per currently retained original subtitle,
- assign each translated line the original cue's source start/end.

Also allow a complete translated SRT import.

---

# 16. Subtitle manager UI

Toolbar:

```text
Manage Subtitles…
```

Open a separate `QDialog`.

Controls:

```text
Detection language: English / Chinese
Translation language: Chinese / English
Generate Draft Subtitles
Video Subtitle Appearance…
```

Tabs:

```text
Original
Translation
```

Original actions:

```text
Import / Replace Original SRT…
Paste Original SRT / Text…
Copy Original Text
Export Original SRT…
```

Translation actions:

```text
Import / Replace Translation SRT…
Paste Translation SRT / Text…
Export Translation SRT…
```

Subtitle table:

```text
Chunk | Final Start | Final End | Text
```

Only Text is editable.

---

# 17. Subtitle appearance dialog

Open from Subtitle Manager:

```text
Video Subtitle Appearance…
```

Controls:

```text
First subtitle:
    Original
    Translated

Second subtitle:
    Original
    Translated
    None

Placement:
    Overlay at bottom with semi-transparent banner
    Scale video down and reserve subtitle area below

Font size:
    16–72 px

Long text:
    Line break / wrap
    Running horizontal text
```

Prevent selecting the same track twice.

---

# 18. Subtitle appearance preview

The appearance dialog must show an actual source-video frame.

Pick a random retained source position from the current chunks.

Provide:

```text
Another random frame
```

Extract preview frame using FFmpeg or equivalent, then paint the subtitle preview in Qt.

Changing any appearance control should redraw the preview immediately.

The preview and final export should use the same subtitle-area sizing algorithm.

---

# 19. Subtitle area sizing

Do not allocate a fixed large fraction of the frame.

Compute area height primarily from:

```text
font size
number of selected tracks
estimated wrapped line count
```

Representative algorithm:

```python
line_height = round(font_size * 1.28)
padding = round(font_size * 0.36)
track_gap = round(font_size * 0.18)

height =
    top padding
    + text line heights
    + gap between tracks
    + bottom padding
```

For wrap mode, estimate how many lines the widest subtitle requires.

Cap extreme wrapping to avoid covering most of the image.

Typical 1080p bilingual one-line targets from the working version:

```text
24 px font → ~84 px area
36 px font → ~124 px area
60 px font → ~209 px area
```

The exact value can vary based on text wrapping.

---

# 20. Subtitle rendering modes

## Banner mode

Keep the original output resolution.

Use FFmpeg:

```text
drawbox
```

at the bottom:

```text
black @ approximately 55% opacity
```

Then render subtitles with the ASS filter.

## Below-video mode

Keep the original output resolution.

Scale the movie proportionally so it fits above the subtitle region.

Pad the original output canvas with black.

Render subtitles in the reserved lower area.

Do not change the final output dimensions.

---

# 21. Subtitle rendering format

Generate a temporary ASS document.

Use font:

```text
Microsoft JhengHei
```

This provides reliable Windows English/Chinese glyph coverage.

Create one ASS style per displayed subtitle row.

Use:

```text
white text
dark outline
bottom-center alignment
```

For wrap mode:

```text
ASS WrapStyle 0
```

For running text:

- keep short subtitles centered,
- only animate if estimated text width exceeds available width,
- use an ASS `\move()` override and clip the text to the subtitle area.

Do not render the same selected track twice.

---

# 22. Final FFmpeg export pipeline

Do not render each chunk to separate temporary files.

Use one FFmpeg filter graph.

For each chunk:

```text
[0:v] trim → setpts
[0:a] atrim → asetpts
```

Then:

```text
concat
```

If subtitles are enabled:

```text
concat video
    ↓
banner/pad filter
    ↓
ASS subtitle filter
```

Map:

```text
[outv]
[outa]
```

Current encoding:

```text
-c:v libx264
-preset medium
-crf 18

-c:a aac
-b:a 192k

-movflags +faststart
```

Use FFmpeg's current filter-script loading syntax:

```text
-/filter_complex <scriptfile>
```

Do not use the removed/deprecated:

```text
-filter_complex_script
```

Modern FFmpeg builds can reject it.

---

# 23. VLC duplicate-subtitle trap

Important compatibility issue discovered during testing.

If the burned-in MP4 is:

```text
movie_trimmed.mp4
```

and an external subtitle exists beside it:

```text
movie_trimmed.zh.srt
```

VLC may auto-load that file.

The user then sees:

```text
burned subtitle
+
VLC external subtitle
```

This looks like a rendering duplication bug but is not.

Therefore:

- default SRT filenames should be:

```text
movie_subtitles_en.srt
movie_subtitles_zh.srt
```

- after video export, scan for:

```text
movie_trimmed.srt
movie_trimmed.*.srt
```

and warn that the player may auto-load them.

---

# 24. Windows dependency traps

## onnxruntime

Silero may fail with:

```text
No module named onnxruntime
```

Requirements must explicitly include:

```text
silero-vad[onnx-cpu]>=6.0
onnxruntime>=1.16.1
```

Install using the exact project interpreter:

```bat
.venv\Scripts\python.exe -m pip install "silero-vad[onnx-cpu]" onnxruntime
```

## faster_whisper

Package installation name:

```text
faster-whisper
```

Python import:

```python
from faster_whisper import WhisperModel
```

If missing:

```bat
.venv\Scripts\python.exe -m pip install faster-whisper
```

## Python environment mismatch

Always invoke pip via:

```bat
.venv\Scripts\python.exe -m pip ...
```

Do not assume a plain `pip` command targets the same environment.

---

# 25. FFmpeg installation assumptions

Recommended Windows install:

```bat
winget install --id Gyan.FFmpeg -e
```

Check:

```bat
ffmpeg -version
ffprobe -version
ffmpeg -filters | findstr ass
```

The editor relies on FFprobe to determine source video dimensions during subtitle export.

---

# 26. Current module map

```text
main.py
    QApplication entry point

main_window.py
    Main editor window
    toolbar
    player
    project save/load
    transition list
    chunk operations
    subtitle-manager launch
    video export

project.py
    SpeechRegion
    Chunk
    chunk grouping
    move/insert/delete/merge helpers

project_io.py
    .vceproj JSON persistence

audio.py
    FFmpeg path lookup
    extract 16-kHz mono PCM WAV
    WAV → torch tensor

vad.py
    QThread Silero VAD worker

boundary_editor.py
    independent ±10 s transition edge controls
    source-frame preview request
    original/cut playback preview

chunk_table.py
    editable chunk number/start/end
    insert row
    merge/delete right-click menu

settings_dialog.py
    minimum quiet-duration setting

subtitles.py
    SubtitleCue
    SubtitleState
    SubtitleRenderSettings
    source ↔ output timing mapping
    SRT parsing/writing

subtitle_manager.py
    faster-whisper worker
    subtitle track table/editor
    SRT import/export
    plain-text translation paste

subtitle_style_dialog.py
    subtitle appearance configuration
    random source-frame preview

subtitle_render.py
    ASS generation
    subtitle layout metrics
    banner/below-video FFmpeg filters
    wrap/running-text behavior

exporter.py
    FFprobe dimensions
    FFmpeg filter graph
    final H.264/AAC export

time_utils.py
    parse_time
    format_time

requirements.txt
install_windows.bat
run_windows.bat
```

---

# 27. Important behavior to preserve when refactoring

Do not accidentally break these properties:

```text
1. Changing VAD quiet threshold does not require rerunning VAD.
2. Original VAD boundary values survive normal manual trimming.
3. Reordering chunks changes output order, not source times.
4. Subtitles stay attached to source times.
5. SRT export always reflects the current final timeline.
6. Imported final-timeline SRT is converted back to source timing.
7. Each boundary slider is independent.
8. Slider movement updates the actual preview frame.
9. Manual chunks have no valid VAD reset point.
10. Video export always uses the current displayed chunk order.
11. Burned subtitles follow reordered chunks.
12. Subtitle preview sizing and export sizing should match.
```

---

# 28. Suggested regression tests

At minimum test the following after significant changes.

### Chunk grouping

Input:

```text
speech 0–2
speech 2.3–4
speech 5.2–8
threshold = 0.7
```

Expected:

```text
chunk 0–4
chunk 5.2–8
```

### Chunk reorder

```text
A, B, C
move A → position 3
```

Expected:

```text
B, C, A
```

### Subtitle reorder

Source:

```text
Chunk A 10–20
Chunk B 40–50

cue A 12–14
cue B 42–44
```

Normal output:

```text
A 2–4
B 12–14
```

Reordered B,A:

```text
B 2–4
A 12–14
```

### SRT round-trip

```text
source cues
→ final timeline SRT
→ parse SRT
→ convert to source time
```

Expected source times should match within millisecond rounding.

### Project round-trip

Save then reopen:

```text
video path
quiet threshold
speech regions
chunk list
VAD references
primary subtitles
translation subtitles
appearance settings
```

All should survive.

### Subtitle ASS event count

With:

```text
1 original cue
1 translation cue
```

and both tracks selected, ASS should contain:

```text
2 dialogue events
```

not duplicates.

### Subtitle banner size

At 1080p with two short one-line cues:

```text
24 px < 36 px < 60 px banner height
```

and a normal 36 px banner should remain substantially below 20% of frame height.

---

# 29. Potential next improvements

These are not required for reproducing the current program, but are logical future work:

```text
Undo/redo
Autosave
GPU Whisper selection
Whisper model selection
Automatic translation API
Subtitle cue split/merge controls
Waveform visualization around transitions
Frame-step buttons
Proxy media for large/high-resolution video
Hardware-accelerated export
Progress percentage from FFmpeg
Soft-subtitle MP4/MKV export in addition to burn-in
Packaging as a standalone .exe
Unit/integration test suite
GitHub Actions build
```

---

# 30. Copy-paste reproduction prompt

The following prompt can be supplied to a fresh coding session together with this document if the existing source files are unavailable.

```text
Build a Windows 11 desktop application called "VAD Chunk Editor" using
Python 3.11 and PySide6.

Purpose:
The program edits spoken videos by detecting quiet periods, automatically
forming source-video chunks, allowing manual correction/reordering, managing
English/Chinese subtitles, and exporting a final MP4.

Use:
- PySide6 / Qt 6
- QMediaPlayer + QVideoWidget
- FFmpeg + FFprobe
- silero-vad
- torch
- onnxruntime
- faster-whisper

Required modules should be separated approximately as:
main.py, main_window.py, project.py, project_io.py, audio.py, vad.py,
boundary_editor.py, chunk_table.py, settings_dialog.py, subtitles.py,
subtitle_manager.py, subtitle_style_dialog.py, subtitle_render.py,
exporter.py, time_utils.py.

DATA MODEL

SpeechRegion:
    start: float
    end: float

Chunk:
    start: float
    end: float
    vad_start: float | None
    vad_end: float | None

SubtitleCue:
    source_start: float
    source_end: float
    text: str

SubtitleState:
    primary_language (English/Chinese)
    translation_language
    primary_cues
    translation_cues
    render_settings

SubtitleRenderSettings:
    first_track: primary|translation
    second_track: primary|translation|none
    layout: banner|below
    font_size: 16..72
    overflow: wrap|scroll

VAD

Extract 16-kHz mono PCM WAV with FFmpeg.
Run Silero VAD once and retain all detected SpeechRegion objects.
Chunks are formed by comparing the gap between consecutive speech regions to a
user-set minimum quiet duration, default 0.70 s.
Changing this threshold should regroup stored VAD timestamps without rerunning
the model.

MAIN UI

Toolbar:
Open Video
Open Project…
Save Project
Split Chunks
Chunk Settings
Manage Subtitles…
Export Trimmed Video…

Use '-' for previous transition and '+' for next transition rather than toolbar
buttons.

Main left area:
video preview
boundary editor

Main right area:
transition list
interactive chunk table

BOUNDARY EDITOR

For every transition show:
Previous chunk — end
Next chunk — start

Both sliders must be independent and each operate in a local ±10 s window.
Use millisecond slider resolution.

Clicking/dragging either slider must:
- update the chunk
- update its numeric time
- pause playback
- show the corresponding source frame in QMediaPlayer

Use QSignalBlocker to avoid feedback loops.
On Windows, repeat the paused seek about 25 ms later using QTimer.singleShot.

Buttons:
Play original around boundary
Preview resulting cut

Right-click a transition:
Reset this transition to original VAD boundary

CHUNK TABLE

Columns:
Chunk | Start | End | Duration

Chunk number is editable and moves the chunk to that output position.
Start and End are editable.
Accepted times: seconds, MM:SS.mmm, HH:MM:SS.mmm.

Always add one empty row after the final chunk.
Entering Start/End creates a new chunk.
Optional Chunk number chooses insertion position.

Right-click:
Merge Chunk N with previous chunk
Merge Chunk N with next chunk
Delete Chunk N

When refreshing a QTableWidget, do not call setItem again on an item already
owned by the table.

PROJECTS

Save human-readable JSON .vceproj files.
Store:
- absolute raw video path
- relative raw video path
- minimum quiet duration
- SpeechRegion list
- complete current chunk list including vad_start/vad_end
- original and translation subtitle cues
- subtitle languages
- subtitle appearance settings

On project load, resolve absolute path, then relative path, then ask the user to
locate the raw movie.

SUBTITLES

Keep all subtitle cues internally in ORIGINAL SOURCE VIDEO TIME.

Map source subtitle cues into the final timeline dynamically using the current
ordered chunks. This is essential so subtitles move when chunks are reordered.

Generate Original subtitles using:
WhisperModel("small", device="cpu", compute_type="int8")
language choices only English or Chinese
beam_size=5
vad_filter=True

Run Whisper in a QThread.

Subtitle manager tabs:
Original
Translation

Original:
Import / Replace Original SRT…
Paste Original SRT / Text…
Copy Original Text
Export Original SRT…

Translation:
Import / Replace Translation SRT…
Paste Translation SRT / Text…
Export Translation SRT…

For plain translation text, require one translated line per retained Original
subtitle and copy its source timing.

Imported SRT is assumed to be timed to the current FINAL timeline. Convert
those times back into source-video timing so future chunk reordering still
works. Split cues if necessary across chunk boundaries.

Export SRT using current final-output timing.

Default SRT filenames:
movie_subtitles_en.srt
movie_subtitles_zh.srt

Do not default to movie_trimmed.zh.srt because VLC may auto-load it beside
movie_trimmed.mp4 and visually duplicate burned-in subtitles.

SUBTITLE APPEARANCE

Add "Video Subtitle Appearance…" to subtitle manager.

Controls:
First subtitle: Original or Translated
Second subtitle: Original, Translated, or None
Placement:
    semi-transparent banner overlay
    subtitles below scaled-down video
Font size 16–72 px
Long text:
    wrap
    horizontal running text

Prevent same track being selected twice.

Show a live preview on a random retained source frame.
Provide "Another random frame".

Subtitle area height must scale with selected font size, track count, and
estimated wrapped line count. Do not use a fixed large percentage of frame
height.

Use Microsoft JhengHei for English/Chinese subtitle rendering.

In scroll mode, short subtitles stay centered; only over-wide text scrolls.

VIDEO EXPORT

Use one FFmpeg filter graph:
trim video/audio per chunk
reset timestamps
concat in current chunk order
optional banner/padding
burn temporary ASS subtitle file

Use FFmpeg current syntax:
-/filter_complex <script file>

Do not use filter_complex_script.

Encode:
libx264
preset medium
CRF 18
AAC 192k
+faststart

For banner mode:
keep original resolution
draw semi-transparent dark box at bottom
burn ASS text

For below-video mode:
keep original output resolution
scale video proportionally into upper area
pad lower region black
burn ASS text there

After export, warn if matching external SRT files exist beside the MP4 because
VLC may auto-load them.

REQUIREMENTS

PySide6>=6.8
numpy>=1.26
torch>=2.2
silero-vad[onnx-cpu]>=6.0
onnxruntime>=1.16.1
faster-whisper>=1.1.0

WINDOWS INSTALL

Use Python 3.11.
Recommend:
winget install Python.Python.3.11
winget install --id Gyan.FFmpeg -e

Create .venv and always install packages using:
.venv\Scripts\python.exe -m pip install -r requirements.txt

Include install_windows.bat and run_windows.bat.

Preserve all non-destructive behavior. The raw movie must never be modified.
```

---

# 31. Final implementation principle

The central concept is:

```text
source video time = truth
```

Chunks define which source intervals survive and in what order.

Subtitles stay attached to source time.

The final output timeline is a projection of those two data structures.

That model is what makes trimming, reordering, project persistence, SRT import/export, and burned subtitle rendering remain consistent as the edit changes.
