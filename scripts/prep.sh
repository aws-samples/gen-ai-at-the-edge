#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

set -e

python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
