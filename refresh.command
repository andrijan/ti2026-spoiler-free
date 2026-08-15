#!/bin/sh
# Double-click to pull in the latest games and open the site.
cd "$(dirname "$0")" || exit 1
python3 update.py
open index.html
