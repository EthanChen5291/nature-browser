"""Vercel serverless function: YouTube song search.

Replaces the /api/search endpoint from server.py for the deployed site. Uses
the YouTube Data API v3 (key in YOUTUBE_API_KEY) instead of yt-dlp, which can't
run on Vercel. Returns video ids the browser plays through the YouTube IFrame
player — there is no MP3 download, because that needs ffmpeg plus a writable
disk and neither exists in the serverless sandbox.

The key falls back to GEMINI_API_KEY: both are Google API keys, so if the
YouTube Data API v3 is enabled on that key's project the same key works here.
"""

import json
import os
import re
import urllib.request
import urllib.error
import urllib.parse
from http.server import BaseHTTPRequestHandler

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY") or os.environ.get("GEMINI_API_KEY", "")
SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"

_ISO = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")


def _fmt_duration(iso):
    m = _ISO.fullmatch(iso or "")
    if not m:
        return ""
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    return f"{h}:{mi:02d}:{s:02d}" if h else f"{mi}:{s:02d}"


def _get(url, params):
    full = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full, headers={"User-Agent": "dad-dashboard/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def yt_search(query, count=6):
    """Return [{id,title,uploader,duration}] from the YouTube Data API."""
    data = _get(SEARCH_URL, {
        "part": "snippet", "type": "video", "maxResults": count,
        "q": query, "videoEmbeddable": "true", "videoSyndicated": "true",
        "key": YOUTUBE_API_KEY,
    })
    items = data.get("items", [])
    ids = [it["id"]["videoId"] for it in items if it.get("id", {}).get("videoId")]

    # One cheap (1-unit) videos.list call fills in durations for all hits at once.
    durations = {}
    if ids:
        det = _get(VIDEOS_URL, {"part": "contentDetails", "id": ",".join(ids),
                                "key": YOUTUBE_API_KEY})
        for d in det.get("items", []):
            durations[d["id"]] = _fmt_duration(d.get("contentDetails", {}).get("duration"))

    results = []
    for it in items:
        vid = it.get("id", {}).get("videoId")
        if not vid:
            continue
        sn = it.get("snippet", {})
        results.append({
            "id": vid,
            "title": sn.get("title", ""),
            "uploader": sn.get("channelTitle", ""),
            "duration": durations.get(vid, ""),
        })
    return results


class handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
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

    def do_GET(self):
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        q = (qs.get("q") or [""])[0].strip()
        if not q:
            return self._json({"results": []})
        if not YOUTUBE_API_KEY:
            return self._json({"error": "No YouTube key configured. Set YOUTUBE_API_KEY "
                                        "(or GEMINI_API_KEY) in the Vercel project's "
                                        "Environment Variables."}, 500)
        try:
            return self._json({"results": yt_search(q)})
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            try:
                detail = json.loads(detail).get("error", {}).get("message", detail)
            except Exception:
                pass
            return self._json({"error": f"YouTube API error {e.code}: {detail[:300]}"}, 502)
        except urllib.error.URLError as e:
            return self._json({"error": f"Could not reach YouTube: {e.reason}"}, 502)
