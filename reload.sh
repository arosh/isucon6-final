#!/bin/bash
set -ex
now=`date +%Y%m%d-%H%M%S`

# MySQL
if [ "$(pgrep mysql | wc -l)" ]; then
  mysqladmin -uroot -ppassword flush-logs
fi

if [ -e /var/log/mysql/mysql-slow.log ]; then
  mv /var/log/mysql/mysql-slow.log /var/log/mysql/mysql-slow.log.$now
fi

if [ -e conf/my.cnf ]; then
  cp conf/my.cnf /etc/mysql/my.cnf
fi

# Python
if [ -e conf/isuketch.python.service ]; then
  cp conf/isuketch.python.service /etc/systemd/system/isuketch.python.service
fi

# Node
if [ -e conf/isuketch.react.service ]; then
  cp conf/isuketch.react.service /etc/systemd/system/isuketch.react.service
fi

systemctl daemon-reload
systemctl restart mysql isuketch.python isuketch.react
journalctl -f -u mysql -u isuketch.python -u isuketch.react
