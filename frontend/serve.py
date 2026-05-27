#!/usr/bin/env python3
"""Simple HTTP server with no-cache headers so browsers always load fresh files."""
from http.server import HTTPServer, SimpleHTTPRequestHandler

class NoCacheHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def log_message(self, fmt, *args):
        pass  # Suppress noisy logs

if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", 3000), NoCacheHandler)
    print("ROADSoS frontend → http://localhost:3000/index.html  (no-cache mode)")
    server.serve_forever()
