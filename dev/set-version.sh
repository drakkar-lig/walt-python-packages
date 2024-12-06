#!/bin/sh

new_version="$1"
if [ "$new_version" = "" ]
then
    echo "Usage: $0 <new-version>"
    exit 1
fi

curr_version=$(dev/get-version.sh)
if [ "$new_version" = "$curr_version" ]
then
    echo "Skipping update of setup.py and version.py files, version is up-to-date."
    exit 0
fi

# update files containing version number
echo "__version__ = '${new_version}'" > common/walt/common/version.py
if [ -f server/requirements.txt ]
then
    sed -i -e 's/^\(walt-.*\)==.*$/\1=='"$new_version"'/g' server/requirements.txt
fi
dev/setup-updater.py
echo "setup.py, version.py files updated"
