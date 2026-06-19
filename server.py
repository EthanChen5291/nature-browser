#!/usr/bin/env python3
"""
Dad's Dashboard - local helper server
=====================================
Optional companion for dad-dashboard.html. It powers three things the
browser can't do on its own:

  1. Song search + YouTube -> MP3 download  (uses yt-dlp + ffmpeg)
  2. Serving downloaded 4K nature videos for the background
  3. Serving family photos you drop into the photos/ folder

Nothing here phones home. Everything is saved next to this file.

Quick start
-----------
    pip install yt-dlp        # ffmpeg must also be installed on your system
    python3 server.py

Then open  http://localhost:8000  in Chrome.
(Serving the page from here also lets the microphone + AI notes work,
 because browsers only allow the mic on http://localhost or https.)

Get some nature videos to start (downloads a few calming 4K clips):
    python3 server.py --setup
"""

import json
import os
import re
import sys
import subprocess
import threading
import urllib.parse
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))


def load_env():
    """Read KEY=VALUE lines from a .env file next to this script into os.environ.
    Keeps secrets (like the Gemini API key) out of the code and the browser."""
    path = os.path.join(ROOT, ".env")
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


load_env()

# AI summaries run server-side so the API key never touches the browser.
# The first provider with a key configured wins: Groq, then Gemini.
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")


def ai_provider():
    if GROQ_API_KEY:
        return "groq"
    if GEMINI_API_KEY:
        return "gemini"
    return None
MUSIC_DIR = os.path.join(ROOT, "music")
# Nature backdrop clips live in assets/ (nature*.mp4); family photos in assets/memories/.
VIDEO_DIR = os.path.join(ROOT, "assets")
PHOTO_DIR = os.path.join(ROOT, "assets", "memories")
ASSETS_DIR = os.path.join(ROOT, "assets")
for d in (MUSIC_DIR, VIDEO_DIR, PHOTO_DIR):
    os.makedirs(d, exist_ok=True)

PORT = 8000

# A few calming, public nature clips to seed the background (used by --setup).
DEFAULT_NATURE_VIDEOS = [
    "https://www.youtube.com/watch?v=BHACKCNDMW8",  # forest stream
    "https://www.youtube.com/watch?v=oR2Vk5Md9zw",  # calm ocean
    "https://www.youtube.com/watch?v=qRTVg8HHzUo",  # mountains
]

MUSIC_EXT = (".mp3", ".m4a", ".ogg", ".wav", ".flac")
VIDEO_EXT = (".mp4", ".webm", ".mov", ".mkv")
PHOTO_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic")


def which(cmd):
    for p in os.environ.get("PATH", "").split(os.pathsep):
        full = os.path.join(p, cmd)
        if os.path.isfile(full) and os.access(full, os.X_OK):
            return full
    return None


YTDLP = which("yt-dlp") or "yt-dlp"


def safe_name(s):
    s = re.sub(r"[^\w\- ]", "", s).strip()
    return (s[:80] or "track")


def run(cmd, timeout=300):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def yt_search(query, count=6):
    """Return a list of {id,title,duration,uploader} using yt-dlp."""
    cmd = [YTDLP, f"ytsearch{count}:{query}", "--dump-json", "--flat-playlist",
           "--no-warnings", "--quiet"]
    out = run(cmd, timeout=60)
    results = []
    for line in out.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            j = json.loads(line)
        except Exception:
            continue
        dur = j.get("duration")
        if isinstance(dur, (int, float)):
            m, s = divmod(int(dur), 60)
            dur = f"{m}:{s:02d}"
        results.append({
            "id": j.get("id"),
            "title": j.get("title", "Unknown"),
            "uploader": j.get("uploader", ""),
            "duration": dur or "",
        })
    return results


def yt_download_audio(video_id, title=""):
    base = safe_name(title) + "." + video_id
    out_tmpl = os.path.join(MUSIC_DIR, base + ".%(ext)s")
    url = "https://www.youtube.com/watch?v=" + video_id
    cmd = [YTDLP, url, "-x", "--audio-format", "mp3", "--audio-quality", "0",
           "-o", out_tmpl, "--no-playlist", "--no-warnings", "--quiet"]
    run(cmd, timeout=600)
    for f in os.listdir(MUSIC_DIR):
        if f.startswith(base) and f.lower().endswith(".mp3"):
            return f
    return None


def yt_download_video(url):
    out_tmpl = os.path.join(VIDEO_DIR, "%(title).70s.%(id)s.%(ext)s")
    cmd = [YTDLP, url, "-f", "bestvideo[height<=2160][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
           "--merge-output-format", "mp4", "-o", out_tmpl,
           "--no-playlist", "--no-warnings", "--quiet"]
    run(cmd, timeout=1800)


def list_media(folder, exts, urlprefix):
    files = []
    for f in sorted(os.listdir(folder)):
        if f.lower().endswith(exts):
            title = re.sub(r"\.[A-Za-z0-9_-]{11}$", "", os.path.splitext(f)[0])
            files.append({"title": title, "url": urlprefix + urllib.parse.quote(f)})
    return files


SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "bullets": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "bullets"],
}


def groq_generate(system, user_text):
    """Call Groq's OpenAI-compatible chat endpoint and return the model's text reply."""
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not set. Add it to the .env file next to server.py.")
    payload = {
        "model": GROQ_MODEL,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_text},
        ],
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=data, method="POST",
        headers={"Content-Type": "application/json",
                 "User-Agent": "dad-dashboard/1.0",
                 "Authorization": "Bearer " + GROQ_API_KEY})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            out = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        try:
            detail = json.loads(detail).get("error", {}).get("message", detail)
        except Exception:
            pass
        raise RuntimeError(f"Groq error {e.code}: {detail[:300]}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Could not reach Groq: {e.reason}")
    return out["choices"][0]["message"]["content"]


def ai_generate(system, user_text):
    """Route a summary request to whichever provider is configured in .env."""
    provider = ai_provider()
    if provider == "groq":
        return groq_generate(system, user_text)
    if provider == "gemini":
        return gemini_generate(system, user_text)
    raise RuntimeError("No AI key configured. Add GROQ_API_KEY or GEMINI_API_KEY to .env.")


# --- Conversational assistant ("Ask anything" box under the meeting notes) ---
CHAT_SYSTEM = (
    "You are a friendly, patient assistant for an older gentleman using a calm "
    "home dashboard. Answer his questions clearly and warmly. Keep replies short "
    "and easy to read — a few sentences or a short list, no jargon. If something "
    "is uncertain, say so plainly. Be encouraging and never condescending."
)


def groq_chat(messages):
    """Plain conversational completion via Groq (no JSON forcing)."""
    payload = {
        "model": GROQ_MODEL,
        "temperature": 0.5,
        "messages": [{"role": "system", "content": CHAT_SYSTEM}] + messages,
    }
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json",
                 "User-Agent": "dad-dashboard/1.0",
                 "Authorization": "Bearer " + GROQ_API_KEY})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            out = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        try:
            detail = json.loads(detail).get("error", {}).get("message", detail)
        except Exception:
            pass
        raise RuntimeError(f"Groq error {e.code}: {detail[:300]}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Could not reach Groq: {e.reason}")
    return out["choices"][0]["message"]["content"]


def gemini_chat(messages):
    """Plain conversational completion via Gemini (no response schema)."""
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_MODEL}:generateContent?key={urllib.parse.quote(GEMINI_API_KEY)}")
    contents = [
        {"role": "model" if m["role"] == "assistant" else "user",
         "parts": [{"text": m["content"]}]}
        for m in messages
    ]
    payload = {
        "system_instruction": {"parts": [{"text": CHAT_SYSTEM}]},
        "contents": contents,
        "generationConfig": {"temperature": 0.5},
    }
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            out = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        try:
            detail = json.loads(detail).get("error", {}).get("message", detail)
        except Exception:
            pass
        raise RuntimeError(f"Gemini error {e.code}: {detail[:300]}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Could not reach Gemini: {e.reason}")
    cands = out.get("candidates") or []
    if not cands:
        fb = out.get("promptFeedback") or out
        raise RuntimeError("Gemini returned no answer: " + json.dumps(fb)[:200])
    parts = cands[0].get("content", {}).get("parts", [])
    return "".join(p.get("text", "") for p in parts)


def ai_chat(messages):
    """Route a chat request to whichever provider is configured in .env."""
    provider = ai_provider()
    if provider == "groq":
        return groq_chat(messages)
    if provider == "gemini":
        return gemini_chat(messages)
    raise RuntimeError("No AI key configured. Add GROQ_API_KEY or GEMINI_API_KEY to .env.")


def clean_messages(raw):
    """Keep only well-formed user/assistant turns, cap length and count."""
    msgs = []
    for m in (raw or [])[-12:]:
        role = m.get("role")
        content = (m.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            msgs.append({"role": role, "content": content[:2000]})
    return msgs


def gemini_generate(system, user_text):
    """Call Gemini's generateContent endpoint and return the model's text reply.
    Raises RuntimeError with a readable message on any failure."""
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set. Add it to the .env file next to server.py.")
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_MODEL}:generateContent?key={urllib.parse.quote(GEMINI_API_KEY)}")
    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json",
            "responseSchema": SUMMARY_SCHEMA,
        },
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            out = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        try:
            detail = json.loads(detail).get("error", {}).get("message", detail)
        except Exception:
            pass
        raise RuntimeError(f"Gemini error {e.code}: {detail[:300]}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Could not reach Gemini: {e.reason}")
    cands = out.get("candidates") or []
    if not cands:
        fb = out.get("promptFeedback") or out
        raise RuntimeError("Gemini returned no answer: " + json.dumps(fb)[:200])
    parts = cands[0].get("content", {}).get("parts", [])
    return "".join(p.get("text", "") for p in parts)


CTYPES = {
    ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".ogg": "audio/ogg",
    ".wav": "audio/wav", ".flac": "audio/flac",
    ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime",
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".gif": "image/gif", ".webp": "image/webp",
    ".html": "text/html; charset=utf-8",
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def _serve_file(self, folder, fname):
        path = os.path.abspath(os.path.join(folder, urllib.parse.unquote(fname)))
        if not path.startswith(os.path.abspath(folder)) or not os.path.isfile(path):
            self.send_error(404)
            return
        ext = os.path.splitext(path)[1].lower()
        ctype = CTYPES.get(ext, "application/octet-stream")
        size = os.path.getsize(path)
        rng = self.headers.get("Range")
        f = open(path, "rb")
        if rng:
            m = re.match(r"bytes=(\d+)-(\d*)", rng)
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else size - 1
            end = min(end, size - 1)
            length = end - start + 1
            self.send_response(206)
            self.send_header("Content-Type", ctype)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Content-Length", str(length))
            self._cors()
            self.end_headers()
            f.seek(start)
            self.wfile.write(f.read(length))
        else:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(size))
            self._cors()
            self.end_headers()
            self.wfile.write(f.read())
        f.close()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        if path == "/" or path == "/index.html":
            return self._serve_file(ROOT, "dad-dashboard.html")

        if path == "/api/search":
            q = (qs.get("q") or [""])[0]
            if not q:
                return self._json({"results": []})
            try:
                return self._json({"results": yt_search(q)})
            except Exception as e:
                return self._json({"error": str(e), "results": []}, 500)

        if path == "/api/library":
            t = (qs.get("type") or ["music"])[0]
            if t == "music":
                return self._json({"files": list_media(MUSIC_DIR, MUSIC_EXT, "/music/")})
            if t == "video":
                return self._json({"files": list_media(VIDEO_DIR, VIDEO_EXT, "/videos/")})
            if t == "photo":
                return self._json({"files": list_media(PHOTO_DIR, PHOTO_EXT, "/photos/")})
            return self._json({"files": []})

        if path.startswith("/music/"):
            return self._serve_file(MUSIC_DIR, path[len("/music/"):])
        if path.startswith("/videos/"):
            return self._serve_file(VIDEO_DIR, path[len("/videos/"):])
        if path.startswith("/photos/"):
            return self._serve_file(PHOTO_DIR, path[len("/photos/"):])
        if path.startswith("/assets/"):
            return self._serve_file(ASSETS_DIR, path[len("/assets/"):])

        self.send_error(404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except Exception:
            body = {}

        if parsed.path == "/api/summarize":
            text = (body.get("transcript") or "").strip()
            if not text:
                return self._json({"error": "missing transcript"}, 400)
            system = body.get("system") or "Summarize this meeting transcript concisely."
            try:
                content = ai_generate(system, "Transcript:\n\n" + text)
                return self._json({"content": content})
            except Exception as e:
                return self._json({"error": str(e)}, 502)

        if parsed.path == "/api/chat":
            messages = clean_messages(body.get("messages"))
            if not messages:
                return self._json({"error": "missing messages"}, 400)
            try:
                return self._json({"content": ai_chat(messages)})
            except Exception as e:
                return self._json({"error": str(e)}, 502)

        if parsed.path == "/api/download":
            kind = body.get("type", "music")
            if kind == "music":
                vid = body.get("id")
                if not vid:
                    return self._json({"error": "missing id"}, 400)
                try:
                    fname = yt_download_audio(vid, body.get("title", ""))
                    if not fname:
                        return self._json({"error": "download failed"}, 500)
                    return self._json({"url": "/music/" + urllib.parse.quote(fname)})
                except Exception as e:
                    return self._json({"error": str(e)}, 500)
            if kind == "video":
                url = body.get("url")
                if not url:
                    return self._json({"error": "missing url"}, 400)
                try:
                    yt_download_video(url)
                    return self._json({"ok": True})
                except Exception as e:
                    return self._json({"error": str(e)}, 500)

        self.send_error(404)


def setup_nature():
    if not which("yt-dlp") and YTDLP == "yt-dlp":
        print("yt-dlp not found. Install it with: pip install yt-dlp")
    print("Downloading a few calming nature videos (this can take a while)...")
    for url in DEFAULT_NATURE_VIDEOS:
        print("  -", url)
        try:
            yt_download_video(url)
        except Exception as e:
            print("    skipped:", e)
    print("Done. Videos saved in", VIDEO_DIR)


def main():
    if "--setup" in sys.argv:
        setup_nature()
        return
    if not which("ffmpeg"):
        print("[!] ffmpeg not found on PATH. MP3 conversion needs ffmpeg installed.")
    if not (which("yt-dlp") or YTDLP != "yt-dlp"):
        print("[!] yt-dlp not found. Install with: pip install yt-dlp")
    prov = ai_provider()
    if prov == "groq":
        print(f"[ok] AI summaries enabled via Groq (model: {GROQ_MODEL}).")
    elif prov == "gemini":
        print(f"[ok] AI summaries enabled via Gemini (model: {GEMINI_MODEL}).")
    else:
        print("[!] No AI key in .env (GROQ_API_KEY or GEMINI_API_KEY) — summaries disabled.")
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"\n  Dad's Dashboard helper running at  http://localhost:{PORT}\n")
    print("  Open that URL in Chrome. Press Ctrl+C to stop.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
