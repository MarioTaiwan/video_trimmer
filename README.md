# VAD Chunk Editor

A Windows desktop video editor for quickly removing pauses from spoken video, reviewing and correcting automatically detected cuts, rearranging clips, generating/editing bilingual subtitles, and exporting the finished video.

The editor is designed around a simple workflow:

```text
Raw video
   ↓
Voice Activity Detection
   ↓
Automatic chunks
   ↓
Review / trim / merge / reorder / delete
   ↓
Generate or import subtitles
   ↓
Optional translation
   ↓
Export final MP4 with burned-in subtitles
```

The program is intentionally focused on spoken presentations, lectures, tutorials, and similar material where silence detection can provide a useful first edit.

---

## Features

### Automatic chunk creation

The editor uses **Silero VAD** to detect speech and non-speech regions.

A user-defined setting determines how long a quiet interval must be before it becomes a chunk boundary.

For example:

```text
Speech ─────────┐       ┌──────── Speech
                │ quiet │
                └───────┘
                   0.4 s
```

With a minimum quiet duration of `0.70 s`, this remains one chunk.

```text
Speech ─────────┐                 ┌──────── Speech
                │      quiet      │
                └─────────────────┘
                       1.5 s
```

This creates a new chunk.

The VAD pass only needs to run once. Changing the quiet-duration threshold later can regroup the stored VAD regions without analyzing the complete movie again.

---

## Interactive boundary editing

Each transition between neighboring chunks has two independent trim controls:

```text
Previous chunk end            Next chunk start
          ↓                           ↓
██████████│.........................│██████████
```

The controls are intentionally independent.

Each slider operates in a local **±10 second range** around its original VAD edge, allowing precise editing without spanning the entire video duration.

When either slider is clicked or dragged:

- the corresponding time value updates,
- the video pauses,
- the preview seeks to the corresponding source frame.

The transition editor also provides:

- **Play original around boundary**
- **Preview resulting cut**

Right-click a transition to restore:

```text
Reset this transition to original VAD boundary
```

The original VAD start/end values are stored separately from subsequent manual edits.

---

## Chunk editing

The **Chunk extents & order** table is the main structural editor.

```text
Chunk | Start       | End         | Duration
1     | 00:01.600   | 01:21.900   | 80.300 s
2     | 01:24.000   | 01:43.800   | 19.800 s
3     | 01:50.100   | 02:17.800   | 27.700 s
...
      |             |             |
```

The final empty row is used to insert a new chunk.

### Reorder a chunk

Edit the number in the **Chunk** column.

For example:

```text
3 → 7
```

moves that chunk to output position 7.

### Change a chunk manually

Edit its **Start** or **End** cell.

Accepted time formats include:

```text
83.250
01:23.250
00:01:23.250
```

### Insert a new chunk

Use the empty row below the final chunk.

Enter:

```text
Start = 04:20.000
End   = 04:31.500
```

Leave the Chunk number blank to append it.

Enter a Chunk number as well to insert it at that output position.

### Merge or delete chunks

Right-click a chunk for:

```text
Merge Chunk N with previous chunk
Merge Chunk N with next chunk
Delete Chunk N
```

Merging creates one continuous source interval covering both chunks and restores the original material between them.

---

## Keyboard shortcuts

The toolbar is intentionally kept simple.

```text
-     Previous transition
+     Next transition
Ctrl+O  Open video
Ctrl+S  Save project
```

---

# Projects

Editing sessions can be saved as:

```text
*.vceproj
```

A project stores:

- raw video path,
- a relative video path when possible,
- quiet-duration threshold,
- original VAD speech regions,
- current chunk order,
- manually edited chunk start/end values,
- original VAD boundary values,
- original subtitle track,
- translated subtitle track,
- subtitle language settings,
- subtitle appearance settings.

The raw video itself is **not copied** into the project file.

If the movie has moved since the project was saved, the editor asks you to locate it.

Because the original VAD result is stored, reopening a project does not require rerunning speech detection.

---

# Subtitle management

Open:

```text
Manage Subtitles…
```

The subtitle system supports two tracks:

```text
Original
Translation
```

Supported recognition languages are currently:

- English
- Chinese

The original track can be generated automatically with **faster-whisper**.

---

## Generate draft subtitles

Select the recognition language and choose:

```text
Generate Draft Subtitles
```

The current implementation uses:

```text
faster-whisper
model: small
device: CPU
compute type: int8
```

The first transcription may download the Whisper model and therefore may require an Internet connection.

The program transcribes the raw source movie and stores subtitle timestamps in **source-video time**.

This is an important design feature.

If a chunk is moved from position 8 to position 2, its subtitles move with it automatically.

If a chunk is trimmed, subtitles outside the retained region disappear or are clipped appropriately.

---

## Edit subtitles

Subtitle text can be edited directly in the subtitle table.

The displayed times correspond to the current final edited timeline even though the underlying subtitle cues remain attached to the original source-video timestamps.

---

## Import SRT

Both Original and Translation tracks support:

```text
Import / Replace ... SRT…
```

Imported SRT files are interpreted as being timed to the **current final edited movie**.

The editor maps those final-output times back into the original source-video timeline so that later chunk movement still works correctly.

---

## Copy/paste translation workflow

A convenient manual translation workflow is:

```text
Generate Original subtitles
        ↓
Copy Original Text
        ↓
Paste into Google Translate
        ↓
Copy translated lines
        ↓
Paste Translation SRT / Text…
```

When plain translated text is pasted, there must be one translated line for each currently retained original subtitle.

The translation inherits the source timing of the corresponding original cue.

A complete translated SRT can also be imported instead.

---

## Export SRT

Each subtitle track can be exported separately.

New SRT files default to names such as:

```text
movie_subtitles_en.srt
movie_subtitles_zh.srt
```

rather than sharing the same basename as the burned-in MP4.

This avoids video players such as VLC automatically loading the external SRT and displaying a subtitle a second time over the subtitle already burned into the video.

---

# Subtitle appearance

Open:

```text
Manage Subtitles…
    → Video Subtitle Appearance…
```

The appearance editor provides a live preview using a retained frame from the source movie.

Use **Another random frame** to choose another preview frame.

The following options are available.

### First subtitle

```text
Original
Translated
```

### Second subtitle

```text
Original
Translated
None
```

The same track cannot be displayed twice.

### Placement

**Banner overlay**

The video keeps its full size and a semi-transparent dark banner is drawn over the bottom of the image.

**Subtitles below video**

The output keeps the original video resolution, but the movie image is scaled down proportionally and placed in the upper portion of the frame. The lower area is reserved for subtitles.

### Font size

```text
16–72 px
```

The height of the subtitle area is calculated from:

- selected font size,
- number of subtitle tracks,
- estimated wrapped line count.

It is not a fixed fraction of the video height.

### Long text

**Line break**

Long text wraps over multiple lines.

**Running text**

Short subtitles remain centered.

Only text that is wider than the available subtitle region becomes a horizontal marquee.

---

# Video export

Choose:

```text
Export Trimmed Video…
```

The exporter:

1. trims every retained chunk from the original movie,
2. concatenates the chunks in the displayed order,
3. maps subtitles onto the resulting final timeline,
4. optionally burns the selected subtitle tracks into the image,
5. writes a new MP4.

Current output settings are:

```text
Video: H.264 / libx264
Preset: medium
CRF: 18

Audio: AAC
Bitrate: 192 kb/s

Container: MP4
Fast-start metadata enabled
```

All cuts are decoded and re-encoded, so trim points are not limited to source keyframes.

---

# Installation on Windows 11

## 1. Install Python 3.11

Open Windows Terminal or Command Prompt:

```bat
winget install Python.Python.3.11
```

Close the terminal, open a new one, then verify:

```bat
py -3.11 --version
```

You should see:

```text
Python 3.11.x
```

---

## 2. Install FFmpeg

The easiest method is:

```bat
winget install --id Gyan.FFmpeg -e
```

Close and reopen the terminal, then verify:

```bat
ffmpeg -version
```

Also verify FFprobe:

```bat
ffprobe -version
```

For burned-in subtitles, the FFmpeg build must provide the ASS/libass filter.

Check with:

```bat
ffmpeg -filters | findstr ass
```

You should see an `ass` filter in the output.

---

## 3. Install the Python environment

Extract the project to a normal folder, for example:

```text
C:\Users\YourName\Documents\vad_chunk_editor
```

Do not run it directly from inside a ZIP archive.

Then double-click:

```text
install_windows.bat
```

The installer creates:

```text
.venv\
```

and installs the required Python packages.

Current requirements include:

```text
PySide6>=6.8
numpy>=1.26
torch>=2.2
silero-vad[onnx-cpu]>=6.0
onnxruntime>=1.16.1
faster-whisper>=1.1.0
```

---

## 4. Start the editor

Double-click:

```text
run_windows.bat
```

or run:

```bat
.venv\Scripts\python.exe main.py
```

---

# Updating an existing installation

After replacing the program files with a newer version, update the environment with:

```bat
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Then run:

```text
run_windows.bat
```

---

# Typical workflow

1. Open a raw video.
2. Adjust **Chunk Settings** if desired.
3. Click **Split Chunks**.
4. Review transitions.
5. Fine-tune previous-chunk end and next-chunk start.
6. Merge/delete/reorder/insert chunks as required.
7. Save the project.
8. Open **Manage Subtitles…**.
9. Generate or import Original subtitles.
10. Correct subtitle text.
11. Add Translation subtitles if desired.
12. Adjust **Video Subtitle Appearance…**.
13. Save the project again.
14. Export the final trimmed MP4.
15. Optionally export Original and Translation SRT files separately.

---

# Troubleshooting

## `No module named onnxruntime`

This normally means the package was installed into a different Python environment.

From inside the project folder run:

```bat
.venv\Scripts\python.exe -m pip install "silero-vad[onnx-cpu]" onnxruntime
```

Verify:

```bat
.venv\Scripts\python.exe -c "import onnxruntime; print(onnxruntime.__version__)"
```

---

## `No module named faster_whisper`

Install it into the project's virtual environment:

```bat
.venv\Scripts\python.exe -m pip install faster-whisper
```

Verify:

```bat
.venv\Scripts\python.exe -c "from faster_whisper import WhisperModel; print('faster-whisper OK')"
```

---

## FFmpeg is not found

Check:

```bat
ffmpeg -version
```

If Windows says the command is not recognized, reinstall FFmpeg:

```bat
winget install --id Gyan.FFmpeg -e
```

Then close and reopen the terminal.

---

## `Unrecognized option 'filter_complex_script'`

That message indicates an old version of this application is being used with a newer FFmpeg build.

Current versions use FFmpeg's file-loading syntax:

```text
-/filter_complex
```

Update to the current application version.

---

## Subtitle export fails because the `ass` filter is missing

Check:

```bat
ffmpeg -filters | findstr ass
```

If no ASS filter appears, install a full FFmpeg build with libass support.

The full Gyan FFmpeg build installed through WinGet normally provides it.

---

## A subtitle appears twice in VLC

One subtitle may be burned into the movie while VLC automatically loads a matching external `.srt`.

For example:

```text
movie_trimmed.mp4
movie_trimmed.zh.srt
```

In VLC choose:

```text
Subtitle → Sub Track → Disable
```

or rename/move the external SRT.

The editor now warns when matching sidecar SRT files are found.

---

## Video preview seeks to an approximate frame

Qt Multimedia preview seeking can depend on the source codec and keyframe structure.

The editor repeats paused seek requests to improve frame refresh behavior, but the final FFmpeg export performs decoded/re-encoded trimming and is more accurate than the preview.

---

## The Whisper model does not start downloading

The first draft-subtitle generation may require Internet access.

If the machine is behind a proxy/firewall, test installation first:

```bat
.venv\Scripts\python.exe -c "from faster_whisper import WhisperModel; print('Whisper import OK')"
```

If the import works but model loading fails, check Internet access and firewall/proxy rules.

---

# Project structure

```text
main.py
    Application entry point

main_window.py
    Main window, toolbar, project management, preview, export orchestration

project.py
    SpeechRegion and Chunk data model
    Chunk grouping, moving, inserting, deleting and merging

project_io.py
    .vceproj serialization and loading

audio.py
    FFmpeg audio extraction and WAV loading

vad.py
    Silero VAD background worker

boundary_editor.py
    Local ±10 s boundary trim controls and frame preview requests

chunk_table.py
    Interactive chunk order/start/end editor

settings_dialog.py
    Quiet-duration settings

subtitles.py
    Subtitle data model
    SRT parsing/export
    Source-time ↔ final-output-time mapping

subtitle_manager.py
    Whisper generation
    Original/Translation editing
    SRT import/export
    copy/paste translation workflow

subtitle_style_dialog.py
    Subtitle appearance controls and random-frame preview

subtitle_render.py
    ASS generation
    subtitle banner sizing
    wrapping/running-text behavior
    FFmpeg subtitle video-filter construction

exporter.py
    Final FFmpeg trim/concatenate/subtitle render worker

time_utils.py
    Time formatting/parsing helpers

requirements.txt
install_windows.bat
run_windows.bat
```

---

# Design philosophy

The editor is deliberately **non-destructive**.

The raw source video is never modified.

Instead, the application maintains an ordered list of source intervals:

```text
Chunk(start, end)
```

and only renders a new movie during export.

Subtitles are likewise stored in source-video time and projected onto the final timeline when needed.

This keeps chunk trimming, reordering, subtitle movement, project saving, and repeated exports straightforward.

---

# Current limitations

- Windows is the primary supported platform.
- Subtitle recognition is limited in the UI to English and Chinese.
- Whisper currently defaults to CPU/int8.
- Automatic machine translation is not built in.
- There is no undo/redo stack yet.
- There is no full nonlinear timeline UI.
- Preview seeking can be less exact than final FFmpeg rendering.
- Export currently re-encodes the entire result.
- Project files reference the source video rather than embedding it.

---

## Status

The current implementation is functional for:

- pause-based automatic editing,
- manual chunk correction,
- project save/reopen,
- English/Chinese transcription,
- bilingual subtitle management,
- burned-in subtitle export.

The project is still evolving, so bug reports and focused feature requests are welcome.
