import os, pathlib, re, subprocess, time, xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]
RESULTS = ROOT / 'ci-results'
RESULTS.mkdir(exist_ok=True)
PACKAGE = 'dev.noshorts.chrome'
COMPONENT = PACKAGE + '/dev.noshorts.chrome.ShortsService'

def adb(*args):
    return subprocess.check_output(['adb', *args], text=True).strip()

def hierarchy():
    adb('shell', 'uiautomator', 'dump', '/sdcard/noshorts-ui.xml')
    return ET.fromstring(adb('shell', 'cat', '/sdcard/noshorts-ui.xml'))

def find_id(name):
    for _ in range(12):
        tree = hierarchy()
        for node in tree.iter('node'):
            if node.get('resource-id') == PACKAGE + ':id/' + name:
                return node
        adb('shell', 'input', 'swipe', '500', '1500', '500', '500', '400')
        time.sleep(.3)
    raise AssertionError('UI node not found: ' + name)

def tap(node):
    x1, y1, x2, y2 = map(int, re.findall(r'\d+', node.get('bounds')))
    adb('shell', 'input', 'tap', str((x1+x2)//2), str((y1+y2)//2))

def wait_bound(phase):
    deadline = time.monotonic() + 45
    while True:
        state = adb('shell', 'dumpsys', 'accessibility')
        enabled = adb('shell', 'settings', 'get', 'secure', 'enabled_accessibility_services')
        (RESULTS/(phase+'-accessibility.txt')).write_text(state)
        (RESULTS/(phase+'-enabled.txt')).write_text(enabled+'\n')
        bound = re.search(r'(?:boundServices|Bound services):\s*\{(.*?)\}', state, re.S | re.I)
        if bound and PACKAGE in bound.group(1):
            assert COMPONENT in enabled, 'Bound service is absent from enabled settings: '+phase
            return
        assert time.monotonic() < deadline, 'Accessibility service did not bind: '+phase+'; enabled='+enabled
        time.sleep(1)

old = ROOT / 'ci-results' / 'NoShorts-previous.apk'
new = ROOT / 'app/build/outputs/apk/release/app-release.apk'
adb('shell', 'pm', 'list', 'packages', 'com.android.chrome')
assert 'com.android.chrome' in adb('shell', 'pm', 'list', 'packages', 'com.android.chrome'), 'Google Chrome absent from system image'
(RESULTS/'chrome-version.txt').write_text(adb('shell', 'dumpsys', 'package', 'com.android.chrome'))
adb('install', '-r', str(old))
adb('shell', 'am', 'start', '-n', PACKAGE+'/.MainActivity')
time.sleep(1)
tap(find_id('rules_input'))
adb('shell', 'input', 'text', 'example.test/blocked')
adb('shell', 'input', 'keyevent', '4')
tap(find_id('save_rules'))
# Enable only after package installation broadcasts and first-launch UI have settled.
# A comparison of two empty settings values must never count as permission retention.
adb('shell', 'settings', 'put', 'secure', 'enabled_accessibility_services', COMPONENT)
adb('shell', 'settings', 'put', 'secure', 'accessibility_enabled', '1')
wait_bound('before-update')
first = re.search(r'firstInstallTime=(.*)', adb('shell', 'dumpsys', 'package', PACKAGE)).group(1)
permissions = adb('shell', 'settings', 'get', 'secure', 'enabled_accessibility_services')
assert COMPONENT in permissions, 'Service was not enabled before update'
adb('install', '-r', str(new))
assert first == re.search(r'firstInstallTime=(.*)', adb('shell', 'dumpsys', 'package', PACKAGE)).group(1), 'Update reinstalled the app'
assert permissions == adb('shell', 'settings', 'get', 'secure', 'enabled_accessibility_services'), 'Accessibility permission changed during update'
adb('shell', 'am', 'start', '-n', PACKAGE+'/.MainActivity')
time.sleep(1)
assert find_id('rules_input').get('text') == 'example.test/blocked', 'Saved rules were lost during update'
wait_bound('after-update')
(RESULTS/'update-check.txt').write_text('PASS: adb install -r; firstInstallTime, saved custom rule and Accessibility permission retained\n')
adb('reboot')
subprocess.run(['adb', 'wait-for-device'], check=True, timeout=120)
deadline = time.monotonic() + 120
while adb('shell', 'getprop', 'sys.boot_completed') != '1':
    assert time.monotonic() < deadline, 'Emulator did not finish rebooting'
    time.sleep(1)
adb('shell', 'input', 'keyevent', '82')
assert permissions == adb('shell', 'settings', 'get', 'secure', 'enabled_accessibility_services'), 'Accessibility permission changed after reboot'
wait_bound('reboot')
adb('shell', 'am', 'start', '-n', PACKAGE+'/.MainActivity')
time.sleep(2)
assert find_id('rules_input').get('text') == 'example.test/blocked', 'Saved rules were lost after reboot'
(RESULTS/'reboot-check.txt').write_text('PASS: reboot retained custom rule and Accessibility permission; system dumpsys confirmed automatic service binding before UI automation or instrumentation\n')
adb('reverse', 'tcp:8765', 'tcp:8765')
