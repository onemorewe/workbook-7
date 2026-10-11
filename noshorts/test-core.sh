#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
out_dir=$(mktemp -d)
trap 'rm -rf -- "$out_dir"' EXIT
mapfile -t source_files < <(find core/src -name '*.java' -print)
java -m jdk.compiler/com.sun.tools.javac.Main -d "$out_dir" "${source_files[@]}"
java -cp "$out_dir" dev.noshorts.core.CoreTest
