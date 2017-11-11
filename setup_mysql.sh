#!/bin/bash
set -ex
mysql -uroot -ppassword < sql/00_create_database.sql
mysql -uroot -ppassword < sql/01_schema.sql
zcat sql/02_initial_data.sql.gz | mysql -uroot -ppassword
