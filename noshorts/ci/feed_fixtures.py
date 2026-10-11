"""Deterministic feed HTML in disposable Chrome tabs, served by CDP, never in the APK."""
import base64, hashlib, json, os, socket, struct, subprocess, time, urllib.parse, urllib.request

SITES = {
    'YouTube': ('https://m.youtube.com/', '/results?search_query=fixture'),
    'Instagram': ('https://www.instagram.com/', '/direct/inbox/'),
    'LinkedIn': ('https://www.linkedin.com/feed/', '/messaging/'),
}

def html(site, login=False):
    if login:
        return '''<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Login feed fixture</title><h1 style="height:160px;background:#00ff00">Fixture sign-in</h1>
<label>Email<input aria-label="Fixture email"></label><label>Password<input type="password" aria-label="Fixture password"></label><button>Sign in</button>'''
    destination = SITES[site][1]
    # YouTube deliberately has no main/feed landmark or semantic bottom nav: fallback layout.
    start, end = ('<div id="feed">', '</div>') if site == 'YouTube' else ('<main id="feed" role="feed">', '</main>')
    return f'''<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{site} feed fixture</title><style>
body{{margin:0;font:16px sans-serif;background:white;min-height:300vh}}
header,footer{{position:fixed;left:0;right:0;height:64px;background:#00ff00;display:flex;align-items:center;justify-content:space-around;z-index:5}}
header{{top:0}}footer{{bottom:0}}button,input{{font-size:14px;max-width:30%;background:#00ff00;border:0;border-radius:0}}
#feed{{padding-top:76px;padding-bottom:80px;min-height:300vh}}
article{{height:240px;background:#ff00ff;margin:12px;display:flex;align-items:center;justify-content:center}}
.spacer{{height:75vh}}[role=dialog]{{position:fixed;top:110px;left:20px;right:20px;height:160px;background:#00ffff;z-index:10}}
</style><header><input type="search" aria-label="Fixture search"><button onclick="menu()">Fixture menu</button>
<button onclick="add()">Add feed card</button></header>
{start}<article>Fixture feed post one</article><div class="spacer"></div><article>Fixture feed post two</article>{end}
<footer><button onclick="window.scrollTo(0,0)">Home</button><button onclick="safe()">Messages</button><button>Profile</button></footer>
<script>
function menu(){{let d=document.createElement('div');d.setAttribute('role','dialog');d.setAttribute('aria-label','Fixture options');
d.innerHTML='<p>Fixture menu panel</p><button onclick="this.parentNode.remove()">Close menu</button>';document.body.append(d);}}
function add(){{let p=document.createElement('article');p.textContent='Dynamic feed post';document.getElementById('feed').prepend(p);window.scrollTo(0,0);}}
function safe(){{history.pushState({{}},'',{json.dumps(destination)});document.body.innerHTML='<h1 style="background:#00ff00;height:220px">Fixture safe destination</h1>';window.scrollTo(0,0);}}
</script>'''

class CDP:
    """Small standard-library WebSocket client; CDP commands are confined to the CI tab."""
    def __init__(self, url, body):
        u=urllib.parse.urlsplit(url)
        self.sock=socket.create_connection((u.hostname,u.port or 80),timeout=15)
        self.sock.settimeout(20); self.reader=self.sock.makefile('rb'); self.next_id=0; self.body=body
        key=base64.b64encode(os.urandom(16)).decode()
        path=u.path+('?' + u.query if u.query else '')
        self.sock.sendall((f'GET {path} HTTP/1.1\r\nHost: {u.netloc}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n').encode())
        status=self.reader.readline(); assert b'101' in status,status
        headers={}
        while True:
            line=self.reader.readline()
            if line in (b'\r\n',b''): break
            k,v=line.decode().split(':',1);headers[k.lower()]=v.strip()
        expected=base64.b64encode(hashlib.sha1((key+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
        assert headers.get('sec-websocket-accept')==expected,'Invalid WebSocket handshake'
    def frame(self, data, opcode=1):
        mask=os.urandom(4); n=len(data)
        size=bytes([0x80|n]) if n<126 else bytes([0x80|126])+struct.pack('!H',n) if n<65536 else bytes([0x80|127])+struct.pack('!Q',n)
        self.sock.sendall(bytes([0x80|opcode])+size+mask+bytes(b^mask[i%4] for i,b in enumerate(data)))
    def send(self, method, params=None):
        self.next_id+=1;self.frame(json.dumps({'id':self.next_id,'method':method,'params':params or {}}).encode());return self.next_id
    def exact(self,n):
        data=self.reader.read(n)
        if len(data)!=n: raise RuntimeError('CDP WebSocket ended')
        return data
    def receive(self):
        chunks=[]
        while True:
            first,second=self.exact(2);n=second&127
            if n==126:n=struct.unpack('!H',self.exact(2))[0]
            if n==127:n=struct.unpack('!Q',self.exact(8))[0]
            assert n<8_000_000,'Unexpected CDP frame size'
            mask=self.exact(4) if second&128 else None
            data=self.exact(n)
            if mask:data=bytes(b^mask[i%4] for i,b in enumerate(data))
            opcode=first&15
            if opcode==8:raise RuntimeError('Chrome closed CDP connection')
            if opcode==9:self.frame(data,10);continue
            if opcode==10:continue
            chunks.append(data)
            if first&128:return json.loads(b''.join(chunks))
    def call(self, method, params=None):
        wanted=self.send(method,params)
        while True:
            message=self.receive()
            if message.get('method')=='Fetch.requestPaused':
                p=message['params'];document=p.get('resourceType')=='Document'
                self.send('Fetch.fulfillRequest',{'requestId':p['requestId'],'responseCode':200 if document else 204,
                    'responseHeaders':[{'name':'Content-Type','value':'text/html; charset=utf-8'}],
                    'body':base64.b64encode(self.body.encode()).decode() if document else ''})
            if message.get('id')==wanted:
                if 'error' in message:raise RuntimeError(message['error'])
                return message.get('result',{})
    def close(self):
        self.reader.close();self.sock.close()

def inject(site, login=False):
    assert site in SITES,'Unknown fixture site'
    subprocess.run(['adb','forward','tcp:9222','localabstract:chrome_devtools_remote'],check=True,timeout=10)
    pages=json.load(urllib.request.urlopen('http://127.0.0.1:9222/json',timeout=10))
    page=next(p for p in pages if p.get('type')=='page' and '/feed-fixture-start' in p.get('url',''))
    cdp=CDP(page['webSocketDebuggerUrl'],html(site,login))
    try:
        cdp.call('Page.enable');cdp.call('Fetch.enable',{'patterns':[{'urlPattern':'*','requestStage':'Request'}]})
        result=cdp.call('Page.navigate',{'url':SITES[site][0]})
        assert not result.get('errorText'),result
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            result=cdp.call('Runtime.evaluate',{'expression':"document.readyState==='complete' && document.title.includes('feed fixture')",'returnByValue':True})
            if result.get('result',{}).get('value') is True:break
            time.sleep(.1)
        else:raise RuntimeError('Feed fixture did not render')
        cdp.call('Fetch.disable')
        return {'ok':True,'site':site,'url':SITES[site][0]}
    finally:cdp.close()
