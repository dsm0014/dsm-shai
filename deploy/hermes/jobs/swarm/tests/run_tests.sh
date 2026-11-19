#!/bin/bash
cd "$(dirname "$0")" && exec python3 -I -m unittest discover -s . -p 'test_*.py' -v
