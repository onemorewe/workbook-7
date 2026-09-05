# ClosePaw custom build

This repository builds a customized ClosePaw APK with GPT-based voice transcription.

## Stable Android signing

The workflow `.github/workflows/build-closepaw-voice.yml` always signs release APKs with the same private key supplied through GitHub Actions repository secrets. As long as the package name and signing key stay unchanged, future APKs install as in-place updates and Android preserves app data/settings.

Required repository secrets:

- `KEYSTORE_BASE64` — base64 of the private `.jks` signing keystore
- `KEYSTORE_PASSWORD` — keystore password
- `KEY_ALIAS` — `closepaw`
- `KEY_PASSWORD` — key password

Never commit the keystore or passwords to this repository.

The workflow gives each build an increasing custom `versionCode` (`100000 + github.run_number`) and builds `assembleRelease`. The resulting signed APK is uploaded as a GitHub Actions artifact.

Any push to `main` triggers a build, so ChatGPT can start a new build by committing a harmless repository change when needed.

## One-time migration

The first custom-signed APK cannot update an APK signed by the upstream ClosePaw key or a previous debug key. Uninstall the old build once, install the first custom-signed build, configure it, and then keep installing future custom-signed APKs over it without uninstalling.
