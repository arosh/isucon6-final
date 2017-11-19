#!/bin/bash
set -ex
now=`date +%Y%m%d-%H%M%S`

# Nginx
if [ -e /var/log/nginx/access.log ]; then
  mv /var/log/nginx/access.log /var/log/nginx/access.log.$now
fi

if [ -e conf/nginx.conf ]; then
  cp conf/nginx.conf /etc/nginx/nginx.conf
fi

# MySQL
if [ -e /var/log/mysql/mysql-slow.log ]; then
  mv /var/log/mysql/mysql-slow.log /var/log/mysql/mysql-slow.log.$now
fi

if [ "$(pgrep mysql | wc -l)" ]; then
  mysqladmin -uroot -ppassword flush-logs
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
systemctl reload nginx
systemctl restart mysql isuketch.python isuketch.react
journalctl -f -u nginx -u mysql -u isuketch.python -u isuketch.react
