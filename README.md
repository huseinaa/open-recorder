# Open Recorder

A free screen + webcam recorder for Windows. I built it to film the lectures for my coding program,
because I wanted something free and stable that does exactly this. It records your screen and your
face at the same time, shows your face in a round bubble while you talk, and the controls never
show up in the video.

It's the recorder I use every day. Here's how to use it too.

---

## What it does

- **Records your screen and your webcam as two separate files**, so in the edit you can move your
  face, resize it, or cut the screen without touching the voice.
- **Shows your face in a round bubble** in the bottom-left corner while you record, so you see what
  your viewers will see. Drag it anywhere.
- **The bar and the bubble are invisible to the recording.** You see them on your monitor, the
  video doesn't.
- **Pause and resume as many times as you want.** When you stop, you get one video, not a folder of
  pieces.
- **Crash safe.** If the PC, the recorder or ffmpeg dies mid-recording, everything up to the last
  second is kept and joined into a normal video the next time you open it.
- **Keeps the camera and the screen in sync.** The camera always starts a fraction of a second
  before the screen. Open Recorder measures that gap on every recording and writes it into the file
  (see [What you get](#what-you-get)).
- **Warns you when the mic goes silent**: a live level meter in the bar, and three beeps if the mic
  stops picking anything up while you record.
- **Keeps your screen awake while recording**, so Windows doesn't turn the display off in the middle
  of a long explanation.
- **Uses your graphics card to encode** (Nvidia, Intel or AMD), and your CPU if there isn't one.
- **Global hotkeys** that work while any other app is in front.

---

## What you need

- **Windows 10 (version 2004 or newer) or Windows 11.** It's Windows only.
- **Python 3.10 or newer:** [python.org/downloads](https://www.python.org/downloads/). Tick
  "Add python.exe to PATH" in the installer.
- **ffmpeg**, the video engine. Open a terminal and run:
  ```
  winget install Gyan.FFmpeg
  ```
  Close the terminal and open a new one afterwards, so it can find ffmpeg.
- A webcam and a mic. Both are optional: it can record just the screen, or just the camera.

---

## Install (about 5 minutes)

**1. Install it**

```
pip install git+https://github.com/huseinaa/open-recorder.git
```

No git? Download the ZIP from the GitHub page (**Code > Download ZIP**), unzip it, open a terminal
in that folder and run `pip install .`

**2. Check everything**

```
open-recorder --check
```

Every line should say `OK`. A `MISS` line tells you exactly what to install. A `NOTE` is fine, it's
just worth knowing (for example, which screens get the fast capture).

**3. Put it on your Desktop**

```
open-recorder --shortcut
```

This makes an **Open Recorder** shortcut on your Desktop that opens it with no terminal window.

---

## Use it

Double-click the shortcut (or run `open-recorder` in a terminal). The first time, it asks which
folder to save your recordings in.

A bar appears at the top of the screen with three cards:

| Card | Toggle | Menu (the arrow) |
|---|---|---|
| **Screen** | record the screen or not | which monitor |
| **Camera** | record the webcam or not | which camera |
| **Mic** | record your voice or not | which microphone |

Then:

| Action | Button | Hotkey |
|---|---|---|
| Start recording | the big **rec** button | `Ctrl+Alt+R` |
| Pause / resume | pause | `Ctrl+Alt+P` |
| Stop and save | stop | `Ctrl+Alt+R` |
| Throw this recording away and start again | restart | |
| Open or change the save folder | the folder icon | |
| Shrink the bar to a small timer | the minimize icon | |

One beep = recording started (start talking after it). Two beeps = stopped and saved. Three fast
high beeps = something's wrong (the mic went silent, or the recording broke), and the bar says
which.

---

## What you get

Every recording is a pair of files with the same id (the date and time you pressed record):

```
screen_20261105_194954.mp4   the screen, no sound
camera_20261105_194954.mp4   your webcam + your voice
```

With the camera switched off, your voice goes into the screen file instead.

**Syncing them in your editor.** The screen file carries a `screen_offset` tag: the seconds to add
to a time in the camera file to get the same moment in the screen file. It's usually around -0.5.
Read it with:

```
ffprobe -v error -show_entries format_tags=screen_offset -of csv=p=0 screen_20261105_194954.mp4
```

In practice: put the camera file on your timeline at 0, and the screen file at `-screen_offset`
seconds (so with -0.5, the screen starts 0.5 s later than the camera).

---

## Settings

Every toggle and device you pick in the bar is remembered. The settings file is at:

```
C:\Users\<you>\AppData\Local\Open Recorder\config.json
```

Close Open Recorder before editing it. The ones worth knowing:

| Setting | What it changes | Default |
|---|---|---|
| `output_dir` | where recordings are saved (also changeable from the folder icon) | asked on first open |
| `fps` | frames per second of both files | `30` |
| `width`, `height` | the camera resolution it asks for first | `1920`, `1080` |
| `encoder` | `auto`, `h264_nvenc` (Nvidia), `h264_qsv` (Intel), `h264_amf` (AMD) or `libx264` (CPU) | `auto` |
| `quality` | lower = sharper and bigger files | `19` |
| `bubble_size` | the face bubble on screen, in pixels | `300` |
| `bubble_margin` | its distance from the corner, in pixels | `25` |
| `bar_scale` | the size of the bar (`1.0` = large) | `0.75` |
| `hotkey_record_stop`, `hotkey_pause` | for example `ctrl+alt+r`, `ctrl+shift+f9` | |
| `silent_mic_db`, `silent_mic_seconds` | how quiet, for how long, before the silent-mic beeps | `-75`, `4` |
| `theme` | colours, for example `{"accent": "#E5484D"}` for a red record button | |

The colour names for `theme` are in [`src/open_recorder/ui/theme.py`](src/open_recorder/ui/theme.py).

---

## If something goes wrong

- **Everything is logged** to `C:\Users\<you>\AppData\Local\Open Recorder\Logs\recorder.log`,
  ffmpeg's own messages included. That's the first place to look, and the file to attach if you
  open an issue.
- **"Recovered 1 recording from last time"** means the last session didn't close properly. Nothing
  was lost: it's saved in your folder like any other recording.
- **One screen says "slower capture" in `--check`.** Laptops with two graphics chips (the laptop
  screen on one, an external monitor on the other) are handled automatically. If a screen still
  can't use the fast capture, it records at about 18 fps instead of 30. Make sure the screen is
  awake when you run the check.
- **The camera shows "No picture".** Another app (Zoom, Teams, the Camera app) may be using it.
  Close that app, then pick the camera again from the camera menu.
- **A hotkey does nothing.** Another app has taken it. Change it in the settings file.

---

## For developers

```
git clone https://github.com/huseinaa/open-recorder.git
cd open-recorder
pip install -e ".[dev]"
pytest
```

`open-recorder --selftest` records, pauses and resumes twice, stops and quits on its own (about 25
seconds), which is the quickest way to check a change end to end.
`open-recorder --visible` leaves the bar and bubble visible to capture, for taking screenshots of
the recorder itself.

| Module | What's in it |
|---|---|
| `app.py` | the state machine, the button and hotkey actions, the UI loop |
| `capture.py` | the ffmpeg command line and the running ffmpeg process |
| `recording.py` | segments, joining them into one pair, crash recovery |
| `screens.py` | monitors and the fast screen capture probe |
| `ffmpeg.py` | finding ffmpeg, devices, picking the encoder |
| `config.py` | the settings file |
| `win32.py` | the Windows calls (hide from capture, hotkeys, keep awake) |
| `ui/` | the bar, the bubble, the theme |
| `check.py` | `--check` |

---

Built by Husein, [unemployedhusein.com](https://unemployedhusein.com). If you record something with
it, send it to me. MIT licensed.
