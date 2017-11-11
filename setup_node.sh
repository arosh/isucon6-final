#!/bin/bash
set -ex
curl -sL https://deb.nodesource.com/setup_6.x | sudo -E bash -
sudo apt install -y nodejs
(
  cd react
  if [ -d node_modules ]; then
    rm -rf node_modules
  fi
  if [ -d build ]; then
    rm -rf build
  fi
  npm install
  NODE_ENV=production npm run build
)
