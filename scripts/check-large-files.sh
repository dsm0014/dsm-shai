#!/usr/bin/env bash
# Fails when any git-tracked file is larger than the byte limit set by CHECK_MAX_BYTES (default 1000000).
set -u
set -o pipefail

cd "$(git rev-parse --show-toplevel)" || exit 1

limit="${CHECK_MAX_BYTES:-1000000}"
if ! [[ "$limit" =~ ^[1-9][0-9]*$ ]]; then
  echo "check-large-files: CHECK_MAX_BYTES must be a positive integer" >&2
  exit 1
fi

failed=0
while IFS= read -r -d '' path; do
  [ -f "$path" ] || continue
  size=$(wc -c < "$path")
  if [ "$size" -gt "$limit" ]; then
    echo "$path: file is $size bytes, limit is $limit bytes"
    failed=1
  fi
done < <(git ls-files -z)

if [ "$failed" -ne 0 ]; then
  exit 1
fi

echo "OK large-files"
exit 0
