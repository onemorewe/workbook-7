# ClosePaw custom build

This repository builds a customized ClosePaw APK with GPT-based voice transcription and an experimental hands-free Android agent.

## Canonical context for ChatGPT Work / future agents

Before changing this project, read [`docs/WORK_HANDOFF.md`](docs/WORK_HANDOFF.md). It contains the current voice pipeline, observability architecture, runtime constraints, test policy, product direction, known limitations, and immediate next steps.

## Current architecture in one line

`Hey Jarvis (local microWakeWord) -> OpenAI live transcription -> semantic intent gate -> spoken/visible acknowledgement -> ClosePaw agent/tools -> remote trace events`

Target private observability architecture:

`Android app -> authenticated HTTPS ingest service -> private trace DB -> owner-only dashboard / authenticated assistant access`

The phone should send traces to our ingest service; the service validates and stores them in the DB. Privileged DB credentials must never live in the APK. Prepared backend work is under [`trace-backend/`](trace-backend/).

## Stable Android signing

The workflow `.github/workflows/build-closepaw-voice.yml` always signs release APKs with the same private key supplied through GitHub Actions repository secrets. As long as the package name and signing key stay unchanged, future APKs install as in-place updates and Android preserves app data/settings.

Required repository secrets:

- `KEYSTORE_BASE64` — base64 of the private `.jks` signing keystore
- `KEYSTORE_PASSWORD` — keystore password
- `KEY_ALIAS` — `closepaw`
- `KEY_PASSWORD` — key password

Never commit the keystore or passwords to this repository.

The workflow gives each build an increasing custom `versionCode` (`100000 + github.run_number`) and builds `assembleRelease`. The resulting signed APK is uploaded as a GitHub Actions artifact.

Any push to `main` triggers a build. Experimental branch builds are also used during development; do not ship an APK unless the relevant CI run is fully green.

## One-time migration

The first custom-signed APK cannot update an APK signed by the upstream ClosePaw key or a previous debug key. Uninstall the old build once, install the first custom-signed build, configure it, and then keep installing future custom-signed APKs over it without uninstalling.

## Last verified hands-free release

At the time of the current handoff, GitHub Actions run **48** was fully green: unit tests, Android speech/UI sandbox, signed release build, signature verification, and artifact upload.