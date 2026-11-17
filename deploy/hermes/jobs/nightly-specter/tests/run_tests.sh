#!/bin/sh
# Run the nightly-job tests locally (no cluster, no network, no model). Exits 0 when all pass.
cd "$(dirname "$0")" && exec python3 -I -m unittest discover -s . -p 'test_*.py' -v
