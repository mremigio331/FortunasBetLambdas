#!/bin/bash

set -euo pipefail

LAYER_NAME=${1:-lambda_layer}

rm -rf layer
mkdir -p layer/python

docker run --rm --platform linux/amd64 --entrypoint bash -v "$PWD":/var/task -w /var/task public.ecr.aws/lambda/python:3.11 -c "
  yum install -y zip &&
  pip install --upgrade pip &&
  pip install -r requirements.txt -t layer/python &&
  cd layer && zip -r9 ../${LAYER_NAME}.zip python
"

rm -rf layer
echo 'Build complete.'
