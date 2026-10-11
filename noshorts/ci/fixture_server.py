from http.server import BaseHTTPRequestHandler, HTTPServer

HTML = b'''<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Chrome navigation test</title><h1>Allowed page</h1><p>The word Shorts alone must not block this page.</p>
<button style="font-size:24px;padding:24px" onclick="history.pushState({},'', '/shorts/test');document.querySelector('h1').textContent='Blocked route';">Open Shorts route</button>'''

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(HTML)))
        self.end_headers()
        self.wfile.write(HTML)

HTTPServer(('127.0.0.1', 8765), Handler).serve_forever()
