from pathlib import Path
import os,subprocess,shutil,zipfile
root=Path(__file__).parent.resolve();sdk=Path(os.environ['ANDROID_HOME']);build=root/'build';build.mkdir(exist_ok=True)
tools=sdk/'build-tools/36.0.0';jar=sdk/'platforms/android-36/android.jar';classes=build/'classes';classes.mkdir(exist_ok=True)
assets=build/'assets';assets.mkdir(exist_ok=True);shutil.copyfile(root/'probe/index.html',assets/'index.html')
def run(*args):subprocess.run([str(a)for a in args],check=True,timeout=120)
run('javac','--release','11','-classpath',jar,'-d',classes,root/'probe/MainActivity.java')
classjar=build/'classes.jar'
with zipfile.ZipFile(classjar,'w')as out:
 for file in classes.rglob('*.class'):out.write(file,file.relative_to(classes))
run(tools/'d8','--lib',jar,'--min-api','26','--output',build,classjar)
run(tools/'aapt2','link','-I',jar,'--manifest',root/'probe/AndroidManifest.xml','--min-sdk-version','26','--target-sdk-version','36','-A',assets,'-o',build/'unsigned.apk')
with zipfile.ZipFile(build/'unsigned.apk','a')as out:out.write(build/'classes.dex','classes.dex')
run(tools/'zipalign','-f','4',build/'unsigned.apk',build/'aligned.apk')
key=build/'probe.jks'
if not key.exists():run('keytool','-genkeypair','-keystore',key,'-storepass','android','-keypass','android','-alias','probe','-keyalg','RSA','-keysize','2048','-validity','10','-dname','CN=Synthetic Lab Probe')
run(tools/'apksigner','sign','--ks',key,'--ks-pass','pass:android','--key-pass','pass:android','--out',build/'probe.apk',build/'aligned.apk')
run(tools/'apksigner','verify',build/'probe.apk')
print('Synthetic probe APK built; no Alpha app code or credentials included.')

