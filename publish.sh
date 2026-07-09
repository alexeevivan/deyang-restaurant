#!/bin/bash

set -e

source .venv/bin/activate

python3 canvas2graphsite.py Main.canvas --out .

mkdocs build
mkdocs gh-deploy

deactivate

git add .
git commit -m "Update project website" || true
git push