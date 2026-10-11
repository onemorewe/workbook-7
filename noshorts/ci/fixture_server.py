from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json, traceback, urllib.parse
from feed_fixtures import inject

HTML = b'''<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Chrome navigation test</title><style>body{min-height:300vh}a{position:fixed;bottom:40px;left:16px;font-size:24px;padding:24px;background:#ddd;color:#000}</style>
<h1>Allowed page</h1><p>The word Shorts alone must not block this page.</p>
<a href="/shorts/test" onclick="history.pushState({},'', '/shorts/test');document.querySelector('h1').textContent='Blocked route';return false;">Open Shorts route</a>'''

PREVIEWS = b'''<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Preview masking test</title>
<style>body{margin:12px;min-height:300vh;font-family:sans-serif}.card{display:block;width:160px;height:220px;margin:12px;color:black;background:#ff00ff}.safe{display:block;height:100px;background:#00ff00;color:black}.spacer{height:70vh}button{font-size:20px}</style>
<h1>Shorts is just a word</h1>
<a class="safe" href="https://www.youtube.com/watch?v=shorts">Ordinary video with Shorts in its title</a>
<section><h2>Shorts</h2><a class="card" href="https://www.youtube.com/shorts/fixture-one"><img width="160" height="190" alt="Shorts preview one" src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='190'%3E%3Crect width='160' height='190' fill='%23ff00ff'/%3E%3C/svg%3E">Shorts card one</a></section>
<a class="safe" href="https://youtube.com.evil.example/shorts/fixture">Lookalike destination stays visible</a>
<div class="spacer"></div>
<section><a class="card" href="https://m.youtube.com/shorts/fixture-two"><img width="160" height="190" alt="Shorts preview two" src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='190'%3E%3Crect width='160' height='190' fill='%23ff00ff'/%3E%3C/svg%3E">Shorts card two</a></section>
<a class="safe" href="https://www.youtube.com/watch?v=ordinary">Ordinary video after scrolling</a>
<button onclick="document.getElementById('dynamic').innerHTML='&lt;a class=card href=https://www.youtube.com/shorts/dynamic&gt;Dynamic Shorts preview&lt;/a&gt;';document.getElementById('dynamic').scrollIntoView()">Add dynamic card</button><section id="dynamic"></section>'''

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/inject-feed?'):
            try:
                query=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                site=query['site'][0]
                content=json.dumps(inject(site,query.get('login')==['1'])).encode();self.send_response(200)
            except Exception as ex:
                traceback.print_exc();content=json.dumps({'error':str(ex)}).encode();self.send_response(500)
            self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(content)))
            self.end_headers();self.wfile.write(content);return
        content = PREVIEWS if self.path.startswith('/previews') else HTML
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(content)))
        self.end_headers()
        self.wfile.write(content)

ThreadingHTTPServer(('127.0.0.1', 8765), Handler).serve_forever()
