"""Update the disposable emulator's Chrome, requiring its existing Google certificate."""
import argparse
import hashlib
import http.cookiejar
import os
import pathlib
import re
import subprocess
import urllib.parse
import urllib.request
import zipfile
from html.parser import HTMLParser

ROOT = pathlib.Path(__file__).resolve().parents[1]
CACHE = ROOT / '.ci-cache'
CACHE.mkdir(exist_ok=True)
APK = CACHE / 'chrome154.apk'
PAGE = 'https://www.apkmirror.com/apk/google-inc/chrome/google-chrome-154-0-8037-126-release/google-chrome-154-0-8037-126-10-android-apk-download/'
VERSION = '154.0.8037.126'

class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.links.append(dict(attrs))

def download():
    if APK.exists() and hashlib.sha256(APK.read_bytes()).hexdigest() == '47ab1990446ec45fdb2078b0c443a1e66aaea011f72705bdbf854ed0ffecde3f':
        print('Using exact verified Chrome 154 package from CI cache', flush=True)
        return
    client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def fetch(url, referer=PAGE):
        return client.open(urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': referer}), timeout=30)
    override = os.environ.get('CHROME_APK_URL', '').strip()
    if override:
        assert override.startswith('https://'), 'Chrome transfer URL must use HTTPS'
        entry, landing = override, PAGE
    else:
        with fetch(PAGE) as response:
            links = Links(); links.feed(response.read().decode())
        entry = next(a['href'] for a in links.links if 'downloadButton' in a.get('class', '') and '/download/' in a.get('href', ''))
        landing = urllib.parse.urljoin(PAGE, entry)
        with fetch(landing) as response:
            links = Links(); links.feed(response.read().decode())
        entry = next(a['href'] for a in links.links if '/wp-content/themes/APKMirror/download.php' in a.get('href', ''))
    entries = [urllib.parse.urljoin(PAGE, entry)]
    if override and 'www.apkmirror.com/wp-content/themes/APKMirror/download.php' in override:
        entries.append("https://downloadr2.apkmirror.com/wp-content/uploads/2026/10/78/6ac3f87e1ddd1/com.android.chrome_154.0.8037.126-803712608_minAPI29%28x86_64%29%28nodpi%29_apkmirror.com.apk")
    last_error = None
    for entry in entries:
        try:
            with fetch(entry, landing) as response, APK.open('wb') as output:
                size = 0
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    assert size < 500 * 1024 * 1024, 'Unexpected Chrome package size'
                    output.write(chunk)
            with zipfile.ZipFile(APK) as archive:
                assert 'AndroidManifest.xml' in archive.namelist(), 'Download is not an APK'
                assert any(n.startswith('lib/x86_64/') for n in archive.namelist()), 'Chrome APK lacks x86_64 native code'
            print('Downloaded Chrome', VERSION, 'bytes', APK.stat().st_size, flush=True)
            return
        except Exception as error:
            last_error = type(error).__name__
            print('Public Chrome transfer failed:', last_error, getattr(error, 'code', ''), flush=True)
    raise RuntimeError('No Chrome package obtained: ' + str(last_error))

def command(*args):
    return subprocess.check_output(args, text=True, timeout=60)

def update():
    signer = pathlib.Path(os.environ['ANDROID_HOME']) / 'build-tools/35.0.0/apksigner'
    paths = command('adb', 'shell', 'pm', 'path', 'com.android.chrome').splitlines()
    original = CACHE / 'chrome-system.apk'
    command('adb', 'pull', paths[0].removeprefix('package:').strip(), str(original))
    def certificates(path):
        output = command(str(signer), 'verify', '--print-certs', str(path))
        return re.findall(r'Signer #\d+ certificate SHA-256 digest: ([0-9a-f]+)', output)
    existing = certificates(original)
    candidate = certificates(APK)
    assert existing and existing == candidate, 'Downloaded Chrome certificate does not match the emulator\'s trusted Google Chrome'
    badging = command(str(signer.parent/'aapt'), 'dump', 'badging', str(APK))
    assert "package: name='com.android.chrome'" in badging and "versionName='"+VERSION+"'" in badging, 'Wrong Chrome package/version'
    command('adb', 'install', '-r', str(APK))
    results = ROOT / 'ci-results'
    results.mkdir(exist_ok=True)
    (results/'chrome-update-check.txt').write_text('PASS: Chrome '+VERSION+' installed over system Chrome with identical verified Google certificate\nSHA256: '+hashlib.sha256(APK.read_bytes()).hexdigest()+'\nCertificate SHA256: '+candidate[0]+'\n')
    original.unlink()
    print('Updated emulator Chrome with identical Google certificate', flush=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--download-only', action='store_true')
    args = parser.parse_args()
    download()
    if not args.download_only:
        update()
