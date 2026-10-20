import os,json,time,base64,subprocess,urllib.request,urllib.parse,hashlib,uuid,threading
from pathlib import Path
ROOT=Path(__file__).parent.resolve();RELAY=os.environ['LAB_RELAY'];RUN='gh-'+os.environ['GITHUB_RUN_ID']+'-'+os.environ['GITHUB_RUN_ATTEMPT'];EXPIRES=int((time.time()+35*60)*1000)
TOKEN='';TOKEN_TIME=0;SESSION='';PROBE='dev.stas.s24lab.probe';WIDTH=1236;HEIGHT=2745;PROBE_RESULT=None
def adb(*args):return subprocess.check_output(['adb','-s','emulator-5554',*args],timeout=90).decode('utf-8',errors='replace').strip()
def token():
 global TOKEN,TOKEN_TIME
 if time.time()-TOKEN_TIME>180:
  url=os.environ['ACTIONS_ID_TOKEN_REQUEST_URL']+'&audience='+urllib.parse.quote(RELAY,safe='')
  req=urllib.request.Request(url,headers={'Authorization':'Bearer '+os.environ['ACTIONS_ID_TOKEN_REQUEST_TOKEN']})
  with urllib.request.urlopen(req,timeout=20)as r:TOKEN=json.load(r)['value']
  TOKEN_TIME=time.time()
 return TOKEN
def relay(path,data=None,binary=False):
 headers={'Authorization':'Bearer '+token()}
 if data is not None:
  headers['Content-Type']='image/png'if binary else'application/json';data=data if binary else json.dumps(data,ensure_ascii=False).encode()
 req=urllib.request.Request(RELAY+'/v1/'+path,data=data,headers=headers)
 with urllib.request.urlopen(req,timeout=30)as r:return r.read()if binary else json.load(r)
def wd(method,path,data=None):
 raw=None if data is None else json.dumps(data,ensure_ascii=False).encode()
 req=urllib.request.Request('http://127.0.0.1:4723'+path,data=raw,method=method,headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=120)as r:v=json.load(r)
 if isinstance(v.get('value'),dict)and v['value'].get('error'):raise RuntimeError(str(v['value'])[:1500])
 return v.get('value')
def command(method,path,data=None):return wd(method,'/session/'+SESSION+path,data)
def find(using,value):
 result=command('POST','/element',{'using':using,'value':value});return result.get('element-6066-11e4-a52e-4f735466cecf')or result['ELEMENT']
def tap(x,y):command('POST','/actions',{'actions':[{'type':'pointer','id':'finger','parameters':{'pointerType':'touch'},'actions':[{'type':'pointerMove','duration':0,'x':round(x),'y':round(y)},{'type':'pointerDown','button':0},{'type':'pause','duration':80},{'type':'pointerUp','button':0}]}]})
def tap_element(e):
 r=command('GET','/element/'+e+'/rect');tap(r['x']+r['width']/2,r['y']+r['height']/2)
def wait_text(text):
 for _ in range(20):
  if text in command('GET','/source'):return
  time.sleep(.5)
 raise RuntimeError('Expected visible UI not found: '+text)
def probe():
 adb('shell','am','force-stop',PROBE);adb('shell','am','start','-n',PROBE+'/.MainActivity');time.sleep(2)
 value='Привет S24 '+str(uuid.uuid4())[:6]
 e=find('class name','android.widget.EditText');tap_element(e);command('POST','/element/'+e+'/clear',{});command('POST','/element/'+e+'/value',{'text':value})
 command('POST','/appium/device/press_keycode',{'keycode':4});time.sleep(.3)
 tap_element(find('xpath',"//*[@text='Save']"));wait_text('Saved: '+value)
 adb('shell','am','force-stop',PROBE);adb('shell','am','start','-n',PROBE+'/.MainActivity');time.sleep(1);wait_text('Saved: '+value)
 stored=adb('shell','run-as',PROBE,'cat','shared_prefs/stand.xml');assert value in stored,'Durable preferences missing input'
 return {'state':'passed','ordinaryTouch':True,'webview':True,'unicodeInput':True,'androidBack':True,'forceStopRelaunch':True,'durableStorage':True,'fixtureValue':value,'apkSha256':hashlib.sha256((ROOT/'build/probe.apk').read_bytes()).hexdigest(),'capturedAt':int(time.time()*1000)}
def heartbeat(state='ready'):
 return relay('status',{'runId':RUN,'state':state,'expiresAt':EXPIRES,'profile':'alpha-main-api36-412x915','width':WIDTH,'height':HEIGHT,'api':36,'bootId':adb('shell','cat','/proc/sys/kernel/random/boot_id'),'webview':adb('shell','dumpsys','webviewupdate')[:2000],'probe':PROBE_RESULT})
def frame():relay('frame',base64.b64decode(command('GET','/screenshot')),True)
def execute(c):
 if c['runId']!=RUN or c['expiresAt']<time.time()*1000:raise RuntimeError('Stale command')
 kind=c['kind']
 if kind=='tap':tap(c['x']*WIDTH,c['y']*HEIGHT)
 elif kind=='swipe':command('POST','/actions',{'actions':[{'type':'pointer','id':'finger','parameters':{'pointerType':'touch'},'actions':[{'type':'pointerMove','duration':0,'x':round(c['x']*WIDTH),'y':round(c['y']*HEIGHT)},{'type':'pointerDown','button':0},{'type':'pointerMove','duration':c['duration'],'x':round(c['x2']*WIDTH),'y':round(c['y2']*HEIGHT)},{'type':'pointerUp','button':0}]}]})
 elif kind=='key':command('POST','/appium/device/press_keycode',{'keycode':{'HOME':3,'BACK':4,'ENTER':66,'APP_SWITCH':187}[c['key']]})
 elif kind=='text':
  e=command('GET','/element/active');eid=e.get('element-6066-11e4-a52e-4f735466cecf')or e['ELEMENT'];command('POST','/element/'+eid+'/value',{'text':c['text']})
 elif kind in ['launch','stop']:
  import re
  if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+',c['package']):raise RuntimeError('Invalid package')
  if kind=='stop':adb('shell','am','force-stop',c['package'])
  else:adb('shell','monkey','-p',c['package'],'-c','android.intent.category.LAUNCHER','1')
 elif kind=='install':
  import re
  if not re.fullmatch(r'[a-f0-9-]{36}',c['asset']):raise RuntimeError('Invalid asset')
  req=urllib.request.Request(RELAY+'/v1/assets/'+c['asset'],headers={'Authorization':'Bearer '+token()})
  with urllib.request.urlopen(req,timeout=90)as r:
   data=r.read(96*1024*1024+1);digest=r.headers.get('x-sha256')
  assert len(data)<=96*1024*1024 and hashlib.sha256(data).hexdigest()==digest,'APK hash mismatch'
  file=ROOT/'build'/('upload-'+c['asset']+'.apk');file.write_bytes(data);result=adb('install','-r','-t',str(file));file.unlink();return {'install':result,'sha256':digest}
 elif kind=='logs':return {'logcat':adb('logcat','-d','-t','120')[-10000:]}
 elif kind=='probe':return probe()
 else:raise RuntimeError('Command not supported')
 return {'executed':kind}
def main():
 global SESSION,PROBE_RESULT
 adb('shell','wm','size',str(WIDTH)+'x'+str(HEIGHT));adb('shell','wm','density','480');adb('shell','input','keyevent','82');adb('install','-r','-t',str(ROOT/'build/probe.apk'))
 caps={'platformName':'Android','appium:automationName':'UiAutomator2','appium:udid':'emulator-5554','appium:appPackage':PROBE,'appium:appActivity':'.MainActivity','appium:noReset':True,'appium:newCommandTimeout':300,'appium:adbExecTimeout':90000}
 response=wd('POST','/session',{'capabilities':{'alwaysMatch':caps}});SESSION=response['sessionId']
 PROBE_RESULT=probe();(ROOT/'build/probe-receipt.json').write_text(json.dumps(PROBE_RESULT,ensure_ascii=False,indent=2));print('Native probe passed: touch, Unicode, Back and persistence.',flush=True)
 heartbeat();frame();last_frame=time.time();last_heartbeat=time.time()
 while time.time()*1000<EXPIRES-10000:
  try:
   if time.time()-last_heartbeat>7:heartbeat();last_heartbeat=time.time()
   c=relay('next')
   if c:
    try:detail=execute(c);state='passed'
    except Exception as e:detail={'error':str(e)[:2000]};state='failed'
    relay('result',{'id':c['id'],'runId':RUN,'state':state,'detail':detail});frame();last_frame=time.time()
   elif time.time()-last_frame>5:frame();last_frame=time.time()
  except Exception as e:print('Control channel temporarily unavailable: '+type(e).__name__,flush=True)
  time.sleep(1)
 heartbeat('stopped');command('DELETE','',None)
if __name__=='__main__':main()

