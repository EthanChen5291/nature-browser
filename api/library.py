"""Vercel serverless function: media library listing.

Replaces the /api/library endpoint from server.py for the deployed site.
The browser already hardcodes the bundled music and nature clips, so the only
thing it truly needs from here is the family photo list. Videos are provided
too as a fallback for the dashboard's onerror path. Music returns empty (the
bundled tracks are listed client-side); there are no server-downloaded songs.

URLs point straight at the static /assets/ paths Vercel serves the files from,
so the browser resolves them as origin + url with no extra rewrites.
"""

import json
import urllib.parse
from http.server import BaseHTTPRequestHandler

# Family photos bundled in assets/memories/. Kept here because the original
# endpoint listed a directory the serverless sandbox can't see at runtime.
PHOTO_FILES = [
    "20cb621dc5ebff1fbafd9088598e02e0.JPG",
    "697139b8ef7d55363ff04040dcd93c1b.JPG",
    "80a6a56507b5ff1d9185e7f024817c79.jpg",
    "IMG_0111.jpg",
    "IMG_0250.jpg",
    "IMG_0252.jpg",
    "IMG_0899.jpg",
    "IMG_1347.jpg",
    "IMG_2753 2.jpg",
    "IMG_3575.jpg",
    "IMG_4067.JPG",
    "IMG_4946.jpg",
    "IMG_5351.jpg",
    "IMG_5869.JPG",
    "IMG_6170.jpg",
    "IMG_8298.JPG",
    "IMG_8304.jpg",
    "IMG_8421.jpg",
]

# Small nature clips bundled in assets/ (the big multi-GB videos aren't deployed).
VIDEO_FILES = [f"nature{i}.mp4" for i in range(1, 8)]


def _entries(files, prefix):
    out = []
    for f in files:
        title = f.rsplit(".", 1)[0]
        out.append({"title": title, "url": prefix + urllib.parse.quote(f)})
    return out


class handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        t = (qs.get("type") or ["music"])[0]
        if t == "photo":
            files = _entries(PHOTO_FILES, "/assets/memories/")
        elif t == "video":
            files = _entries(VIDEO_FILES, "/assets/")
        else:  # music — bundled tracks are listed client-side; nothing extra here
            files = []
        body = json.dumps({"files": files}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
