"""Vercel serverless function: AI meeting summaries.

Mirrors the /api/summarize endpoint from server.py, but runs on Vercel.
The provider key lives in a Vercel environment variable, never in the browser.
Groq is preferred (free, no card); Gemini is used if only that key is set.
"""

import json
import os
import urllib.request
import urllib.error
import urllib.parse
from http.server import BaseHTTPRequestHandler

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "bullets": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "bullets"],
}


def groq_generate(system, user_text):
    payload = {
        "model": GROQ_MODEL,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_text},
        ],
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


def gemini_generate(system, user_text):
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


def ai_generate(system, user_text):
    if GROQ_API_KEY:
        return groq_generate(system, user_text)
    if GEMINI_API_KEY:
        return gemini_generate(system, user_text)
    raise RuntimeError("No AI key configured. Set GROQ_API_KEY or GEMINI_API_KEY "
                       "in the Vercel project's Environment Variables.")


class handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
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

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except Exception:
            body = {}
        text = (body.get("transcript") or "").strip()
        if not text:
            return self._json({"error": "missing transcript"}, 400)
        system = body.get("system") or "Summarize this meeting transcript concisely."
        try:
            content = ai_generate(system, "Transcript:\n\n" + text)
            return self._json({"content": content})
        except Exception as e:
            return self._json({"error": str(e)}, 502)
