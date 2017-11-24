#!/bin/bash
set -ex
now=`date +%Y%m%d-%H%M%S`

# Python
if [ -e conf/isuketch.python.service ]; then
  cp conf/isuketch.python.service /etc/systemd/system/isuketch.python.service
fi

# Node
if [ -e conf/isuketch.react.service ]; then
  cp conf/isuketch.react.service /etc/systemd/system/isuketch.react.service
fi

# system
if [ -e conf/sysctl.conf ]; then
  cp conf/sysctl.conf /etc/sysctl.conf
  sysctl -p
fi

if [ -e conf/limits.conf ]; then
  cp conf/limits.conf /etc/security/limits.conf
fi

systemctl daemon-reload
systemctl restart isuketch.python isuketch.react
journalctl -f -u isuketch.python -u isuketch.react
