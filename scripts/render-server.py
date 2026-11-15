#!/usr/bin/env python3
"""Serves the built site (dist/) and saves the images the page posts in its export modes.

The site falls back to pre-rendered image sequences when WebGL is missing or too slow. Those sequences are
rendered by the site itself, in a browser that has WebGL, when opened with `?export=<kind>`; each frame is
POSTed here and written to render-out/. See README, "Re-rendering the fallback images".

    python3 scripts/render-server.py [port]        (default 8765; run `npm run build` first)
"""
import http.server, os, re, socketserver, sys, threading, urllib.parse

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'dist')
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'render-out')
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
GIF = bytes.fromhex('47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b')
done = threading.Event()


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)

    def log_message(self, *a):
        pass

    def _ok(self, body=b'ok', ctype='text/plain'):
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == '/wait':  # held open until the page reports it has finished, so a headless browser waits
            done.clear()
            done.wait(timeout=float(urllib.parse.parse_qs(u.query).get('s', ['60'])[0]))
            return self._ok(GIF, 'image/gif')
        if u.path == '/done':
            done.set()
            return self._ok()
        return super().do_GET()

    def do_POST(self):
        name = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get('name', [''])[0]
        if not re.fullmatch(r'[a-z0-9_]{1,24}\.(jpg|json)', name):
            self.send_response(400)
            self.end_headers()
            return
        os.makedirs(OUT, exist_ok=True)
        with open(os.path.join(OUT, name), 'wb') as f:
            f.write(self.rfile.read(int(self.headers.get('Content-Length', '0'))))
        self._ok()


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


if not os.path.isdir(ROOT):
    sys.exit('dist/ not found: run `npm run build` first')
print(f'Serving dist/ on http://127.0.0.1:{PORT} — exported frames go to render-out/')
Server(('127.0.0.1', PORT), Handler).serve_forever()
