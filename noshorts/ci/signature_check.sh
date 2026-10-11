#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
signer="$ANDROID_HOME/build-tools/35.0.0/apksigner"
"$signer" verify --verbose --print-certs ci-results/NoShorts-previous.apk > ci-results/previous-signature.txt
"$signer" verify --verbose --print-certs app/build/outputs/apk/release/app-release.apk > ci-results/release-signature.txt
diff <(sed -n '/certificate SHA-256 digest:/p' ci-results/previous-signature.txt) <(sed -n '/certificate SHA-256 digest:/p' ci-results/release-signature.txt)
sha256sum app/build/outputs/apk/release/app-release.apk > ci-results/apk-sha256.txt
