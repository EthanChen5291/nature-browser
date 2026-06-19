# Dad's Dashboard 🌿

A calm, nature-inspired personal dashboard built as a Father's Day CS project.
It's designed to feel **natural and refreshing** while quietly helping with a
busy workday: focus tasks, AI meeting summaries, one-click nature music, a 4K
nature video backdrop, and a rotating family photo gallery.

---

## What's inside

| File | What it is |
|------|------------|
| `dad-dashboard.html` | The whole dashboard. Works on its own — just open it. |
| `server.py` | Optional helper for YouTube→MP3, nature videos, and photos. |
| `README.md` | This file. |

---

## The fastest way to run it

**Just double-click `dad-dashboard.html`.** It opens in your browser and the
following work immediately:

- ✅ Today's Focus tasks (saved in the browser)
- ✅ Nature music player with built-in calm classics + adding your own files
- ✅ Rotating family photo gallery (with placeholders until you add photos)
- ✅ Animated nature ambient background
- ✅ Paste-and-summarize meeting notes (with an API key, see below)

---

## The full experience (recommended)

Running the small helper server unlocks **live microphone transcription**,
**YouTube→MP3 song search**, and **real 4K nature videos**.

### 1. Install the two tools it needs
```bash
pip install yt-dlp
```
You also need **ffmpeg** (for MP3 conversion):
- macOS: `brew install ffmpeg`
- Windows: `winget install Gyan.FFmpeg`
- Linux: `sudo apt install ffmpeg`

### 2. (Optional) Grab a few starter nature videos
```bash
python3 server.py --setup
```

### 3. Start the dashboard
```bash
python3 server.py
```
Then open **http://localhost:8000** in **Chrome** or **Edge**.

> Opening it from `http://localhost` (instead of double-clicking the file) is
> what lets the browser use the **microphone** for live meeting transcription.

---

## Setting up the AI meeting summaries

1. Click the ⚙ (gear) in the top-right.
2. Paste an **AI API key**. An OpenAI key works out of the box
   (https://platform.openai.com/api-keys).
3. Save.

Then during a meeting: press **● Start listening**, and when it's done press
**✨ Summarize**. You'll get a **HIGHLY concise** set of bullet points (to-dos
flagged with ☐). Each summary is auto-stamped with the date & time in **CST**
and filed into **🗂 Meetings** — a Stage-Manager-style deck where past meetings
stack newest-first with their dates peeking at the top. Tap any card to bring it
forward. No need to type the date — it knows.

> Want to use a different/cheaper or local model? In Settings you can change the
> **API Base URL** and **Model** to any OpenAI-compatible provider (Groq,
> OpenRouter, a local LLM, etc.). The key never leaves the browser except to
> talk to the provider you choose.

---

## Adding music

- **One-click calm:** the 🌿 button shuffles soothing instrumentals and presses play.
- **Search YouTube:** type a song, press Search, then **⬇ Add** — it's added to
  the playlist and starts playing.
  - *Running locally* (`server.py`): the helper downloads it as an MP3.
  - *On the deployed site:* full songs stream through a hidden YouTube player
    (no download — Vercel can't run ffmpeg). This needs a **YouTube Data API
    key**: in Google Cloud, enable **"YouTube Data API v3"**, create an API key,
    and add it as `YOUTUBE_API_KEY` in the Vercel project's Environment
    Variables. (Free quota is ~100 searches/day.)
- **Add your own files:** press the **＋** next to search to pick audio files,
  or drop `.mp3` files into the `music/` folder next to `server.py`.

## Adding family photos

Drop image files into the `photos/` folder next to `server.py`, or press the
**＋** on the Family panel to add them for the current session. They rotate
automatically every few seconds.

## Nature video background

Click the 🎞️ button (top-right) to turn the video backdrop on/off. Videos come
from the `videos/` folder (populated by `python3 server.py --setup`, or drop
your own `.mp4` files in there). Without videos, a gentle animated nature
gradient is shown instead.

---

## Privacy

Everything is local. Tasks, settings, and your API key live in your browser.
The helper server only runs on your own computer and never sends your data
anywhere — it just fetches the songs/videos you ask for.

---

Made with love for Dad. Happy Father's Day. 💚
"""
