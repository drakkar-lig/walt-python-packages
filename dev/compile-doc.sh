#!/bin/sh
set -e

root_dir="$1"
python="$root_dir/dev/python.sh"

# go to the root of the sources
cd "$root_dir"

# activate the virtual env if not done yet
[ -z "$VIRTUAL_ENV" ] && . .venv/bin/activate

# install sphinx requirements
cd doc/walt/doc/sphinx
$python -m pip install -r requirements.txt

# compile the doc to html
make SPHINXOPTS="-W" html

# move the compilation results
rm -rf ../html && cp -r _build/html ../html
cd ../html
rm -rf _sources
find . -type d | while read d
do
    touch $d/__init__.py
done
cd ../../..
