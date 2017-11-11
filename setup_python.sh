#!/bin/bash
set -ex
sudo apt install -y python-virtualenv libmysqlclient-dev python-dev
/usr/bin/virtualenv python/venv
./python/venv/bin/pip install -r python/requirements.freeze
