# ClosePaw custom agent — canonical handoff

This file is the canonical context handoff for ChatGPT Work / future agents. Read this before changing the project.

## Repository and active branch

- Repository: `onemorewe/workbook-7`
- Active development branch for the current hands-free/debug work: `handsfree-crash-runtime-panel`
- Upstream project being patched/built: ClosePaw (`imoonkey/closepaw`)
- Stable Android signing is preserved through GitHub Actions secrets. Do not regenerate the keystore or change the package/signing lineage unless explicitly requested.

## User goal

Build a reliable hands-free Android agent on a Samsung Galaxy S24 Ultra. It should wake locally, understand RU/EN speech, decide the semantic intent, announce what it understood, execute actions through ClosePaw, and expose enough remote observability that the development assistant can debug failures without asking the user to pull logs while driving.

The long-term product direction is broader than voice: successful expensive GUI-agent executions should be compiled into reusable deterministic capabilities/workflows, shared across devices/users through a server-side registry. Heavy LLM reasoning should be sparse and used for unknown tasks, semantic resolution, repair, and workflow compilation—not for every tap forever.

## Current hands-free pipeline

1. Always-on local wake detector.
   - Current control wake phrase: **Hey Jarvis**.
   - Runtime: microWakeWord / TFLite.
   - The eventual desired wake phrase is Russian **Алёша**, after a custom model is trained and validated.
2. After wake, OpenAI Realtime transcription is opened.
   - Model: `gpt-live-transcribe`.
   - Audio: 24 kHz mono PCM16.
   - Current turn detection is server VAD.
3. Final transcript is fed to the intent gate.
4. Intent gate returns either:
   - `NOT_READY`, or
   - the normalized executable intent itself.
   It must not return READY/NOT_READY booleans.
5. Intent gate uses the selected ChatGPT/Codex OAuth model when available (subscription allowance). Do not silently fall back to API-key text billing for the intent gate.
6. When an intent is accepted, the app visibly shows it and TTS announces what it understood before execution.
7. Hands-free sessions use auto-approve for action approvals during this prototype stage.
8. The accepted intent is submitted to the normal ClosePaw agent/session machinery for tool execution.

## Normal microphone path

The ordinary mic button is separate from hands-free. It currently records an utterance and submits it to OpenAI transcription; do not assume changes to hands-free automatically change the normal mic path.

## Important semantic rule for music/search-like tasks

Do not force the LLM to invent an exact canonical entity before searching.

Preferred flow:

1. Understand the action/capability first, e.g. `PLAY_MUSIC`, target app = Yandex Music.
2. Preserve the user's raw/fuzzy entity reference, e.g. a title fragment, lyric quote, or artist+song approximation.
3. Announce the interpreted action, e.g. "Ищу ... в Яндекс Музыке".
4. Search the provider with the heard reference.
5. If the returned candidate validates confidently, use it.
6. Only if confidence is low, invoke a semantic resolver / web / stronger model to canonicalize title+artist, then retry.
7. Verify semantic success (correct title/artist actually playing), not merely that a search screen opened or something started.

This hybrid avoids both extremes: blind raw-STT searching and LLM hallucination of exact names before provider search.

## Observability: current vs target

### Current build

The current debug build still publishes compact structured events to a pinned `ntfy.sh` topic so the assistant can inspect wake/STT/VAD/intent/agent/trace stages remotely. Credentials are redacted. This is development-only and not the desired final architecture.

### Target private trace architecture

The intended architecture is:

`Android app -> authenticated HTTPS ingest endpoint -> server-side validation/normalization -> private trace database -> private dashboard / assistant access`

Concretely, the prepared backend direction is Supabase:

- Android does **not** connect to the database with privileged credentials.
- Android sends trace events to a Supabase Edge Function (or equivalent server endpoint) over HTTPS.
- The ingest endpoint authenticates a device/app write token, validates payloads, and inserts them into the private `trace_events` table.
- Database/service-role credentials remain server-side only.
- Public/anonymous read access is disabled.
- The dashboard reads the database server-side and is owner-only.
- ChatGPT/agent access should use the connected Supabase integration or another authenticated server-side read path, never public table access.
- Dashboard should show sessions/runs, ordered timeline, stages, latency, errors, retries, transcript, normalized intent, tool calls/results, and filtering/search.

This means the app writes **to our ingest service**, and the service writes to the DB. The DB is storage behind the service, not a database credential embedded in the APK.

Prepared backend files live under `trace-backend/` on the active branch. Do not wire the APK away from ntfy until a real private endpoint and auth token exist and have been tested.

## Privacy/security stance for prototype

The user is comfortable sending detailed traces for debugging, but still keep sane defaults:

- Never commit OpenAI API keys, OAuth tokens, Supabase service-role keys, keystore files, or signing passwords.
- Keep privileged DB credentials server-side.
- Prefer write-only/ingest credentials in the APK.
- Banking/authenticator/crypto apps remain blocked by ClosePaw; do not weaken those protections just for trace coverage.
- Trace payload contents are determined by the app; backend storage does not automatically add screenshots/prompts unless the app sends them.

## Voice & Runtime UI

There is a dedicated `Voice & Runtime` screen. It should report effective runtime state, not hard-coded marketing labels:

- selected/effective reasoning model;
- whether agent reasoning is using ChatGPT/Codex OAuth subscription allowance or API-key provider mode;
- effective speech/transcription model;
- wake detector/model;
- hands-free state;
- TTS engine;
- errors/fallbacks when relevant.

Do not move this back into a generic settings dump.

## Remote-debug requirement

The user should not have to manually extract logcat or traces during normal iteration. If a hands-free command fails, the target workflow is:

1. User tells the assistant approximately what was said and when.
2. Assistant reads the remote private trace stream/database.
3. Assistant identifies the failed stage and patches/tests the app.
4. User only performs final real-device smoke testing when Samsung-specific hardware/firmware behavior cannot be reproduced in emulator.

## Test policy

Do not ship a new APK merely because it compiles.

The GitHub Actions workflow should run:

- unit tests;
- Android emulator instrumentation/smoke tests;
- synthetic/neural `Hey Jarvis` audio fixture through the wake-word path where practical;
- hands-free pipeline tests around Realtime transcript completion -> intent gate handoff;
- UI navigation to `Voice & Runtime` and hands-free enable flow without crashing;
- release build;
- stable signing restoration;
- APK signature verification;
- artifact upload.

The last fully green release before this handoff was **run 48**, after fixing the emulator onboarding issue. It passed unit tests, Android speech/UI sandbox, signed release build, signature verification, and artifact upload.

## Known limitations / open work

- Emulator cannot faithfully reproduce Samsung's exact Android 16 audio stack/OEM behavior.
- Wake phrase is still `Hey Jarvis`; custom Russian `Алёша` weights are not yet trained/validated.
- Post-wake cloud transcription can accrue cost while a command session remains open.
- Current VAD is server VAD, not semantic VAD.
- Follow-up turns currently may require another wake phrase depending on current service state.
- Audio focus / beep leakage / AEC / speaker discrimination remain areas for real-device tuning.
- Private Supabase trace backend is prepared conceptually/in repo but not yet connected/deployed from the user's account at the time of this handoff.
- Do not remove the ntfy fallback until private ingest has been proven from the real phone.

## Product architecture direction beyond the prototype

Semantic capability layer should be distinct from UI workflows.

Example capability: `PLAY_MUSIC(entity_reference, provider)`.

Server-side shared registry eventually stores reusable capability/workflow variants keyed by environment such as app package/version, OS/OEM, locale, permission state, and UI variant. Flow:

1. cheap intent router identifies capability;
2. phone/server finds deterministic workflow variant for the environment;
3. phone executes deterministic actions;
4. semantic resolver is invoked only for ambiguity;
5. heavy GUI agent is invoked only for unknown/broken flows;
6. successful trace + user confirmation is compiled into a candidate reusable workflow;
7. candidates are validated/promoted before network-wide reuse;
8. UI drift triggers repair/new variant rather than deleting the semantic capability.

Key risks: semantic success verification, generalization, state explosion, privacy, prompt injection/poisoning, and safe promotion of shared workflows.

## How a new Work/agent should resume

1. Read this file and `README.md`.
2. Inspect the active branch `handsfree-crash-runtime-panel` before modifying code.
3. Inspect `trace-backend/` before inventing a new observability backend.
4. Preserve stable signing and current package identity.
5. Prefer short conceptual explanations to the user; they often interact while driving/listening.
6. Do not ask the user to manually debug things the emulator/remote traces can reveal.
7. Before shipping, require the full CI path to go green.

## Immediate next step

Connect/deploy the private trace backend, obtain a real HTTPS ingest endpoint plus safe write credential, patch `HandsFreeDebugRelay` to send there (optionally dual-write to ntfy during migration), validate events from emulator and then real device, and build the private owner-only trace dashboard.