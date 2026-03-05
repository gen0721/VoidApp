#!/bin/bash
export PIP_BREAK_SYSTEM_PACKAGES=1
python -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install --no-cache-dir --ignore-installed -r requirements.txt
python main.py
