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

Verified on 2026-09-05: GitHub Actions [run **53**](https://github.com/onemorewe/workbook-7/actions/runs/33979733065) was fully green: unit tests, Android speech/UI sandbox, signed release build, signature verification, and artifact upload. Check current CI before distributing a newer APK.

## Private trace backend continuation

[`trace-backend/README.md`](trace-backend/README.md) documents the authenticated ingest/read endpoints, per-device write credentials, private schema, deployment sequence and real round-trip check. Backend auth/redaction tests and a real Postgres RLS/deduplication gate now run before the Android build.

On 2026-10-21 the existing Supabase project was restored from inactivity. GitHub Actions [run **140**, attempt **2**](https://github.com/onemorewe/workbook-7/actions/runs/39658261495) passed private ingest, unit tests, release signing and artifact upload. Its synthetic `ci-preflight-140` event was independently found in private storage. This verifies the CI-to-ingest-to-database path; the full deployed read/auth round-trip and real Samsung round-trip remain **NOT_VERIFIED**. Keep ntfy until a known phone event is confirmed. Exact evidence and the existing owner-only dashboard identity are in [`docs/WORK_HANDOFF.md`](docs/WORK_HANDOFF.md).

## Optional Android UI and parser run

Use `workflow_dispatch`, or include `[android-ui]` in the HEAD commit message of a push to one of the workflow's configured branches. Both existing emulator steps then run; ordinary pushes still skip them. The private-ingest, backend, unit, release-signing and signature gates are unchanged.

The existing API 35 / x86_64 / Pixel 6 emulator runs only `HandsFreeSafetyInstrumentedTest` and `VoiceRuntimeUiInstrumentedTest`. Live AI allowance is **0**: do not provision API keys or OAuth accounts. Parser cases feed synthetic server events without opening a WebSocket; the UI case navigates the real app and attempts hands-free startup with no credentials. This is parser/navigation/crash evidence, not a live transcription or phone test. Run 140 skipped these emulator steps, so its green result does not establish UI success.

## Generated UI contract check

After the workflow applies the complete patch chain, run
`python3 tests/test_voice_runtime_ui_contract.py closepaw`. This checks the copied
instrumentation test's panel selectors against Compose render calls in the final
generated source, catching labels changed by a later patch. It runs before the
signed build on every workflow invocation. This source check does not establish
visibility, scrolling, click behavior or Android instrumentation success.
