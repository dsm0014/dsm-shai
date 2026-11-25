#!/usr/bin/env bash
# This check enforces that YAML files (.yaml or .yml) contain no tab characters, because tabs are not allowed in YAML indentation.

set -u

while IFS= read -r -d '' file; do
    if [[ "$file" =~ \.(yaml|yml)$ ]]; then
        if grep -q $'\t' "$file"; then
            while IFS= read -r line; do
                echo "${file}: tab character on line ${line%:*}"
            done < <(grep -n $'\t' "$file")
            exit 1
        fi
    fi
done < <(git ls-files -z)

echo "OK yaml-tabs"
exit 0
