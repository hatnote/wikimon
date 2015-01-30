#!/bin/bash

DB=GeoLite2-City.mmdb
CUR_MD5=current_geodb.md5

GEODB_DIR=$(readlink -f ${GEODB_DIR-$PWD})
CUR=$GEODB_DIR
PREV=$GEODB_DIR/prev
GEODB_TMP=$GEODB_DIR/tmpdl

mkdir -p $GEODB_TMP
cd $GEODB_TMP

# current md5sum
HASH=$(wget -O - http://geolite.maxmind.com/download/geoip/database/GeoLite2-City.md5) || exit 1

MD5="$HASH  $DB"

# hashes match, so we already have this one
cmp <(echo "$MD5") $CUR/$CUR_MD5 && exit 2

# try to pick up where we left off
# overwrite if newer (or size changes)
wget -cN http://geolite.maxmind.com/download/geoip/database/GeoLite2-City.mmdb.gz || exit 3

gunzip GeoLite2-City.mmdb.gz || exit 4

# make sure it downloaded successfully
echo "$MD5" | md5sum -c || exit 5

# make sure we got
if [ -f "$CUR/$DB" -a -f "$CUR/$CUR_MD5" ]
then
    mkdir -p $PREV
    cp $CUR/$DB $CUR/$CUR_MD5 $PREV/ || exit 6
fi

echo "$MD5" > $CUR_MD5

mv $DB $CUR_MD5 $CUR/ || exit 7
