#!/bin/bash
set -e

git_root="$(git rev-parse --show-toplevel)"
cd "$git_root"
# activate the virtual env if not done yet
[ -z "$VIRTUAL_ENV" ] && . .venv/bin/activate
venv_root=$(python3 -c 'import sys; print(sys.prefix)')
venv_packages="$(ls -d "${venv_root}/lib/python"*"/site-packages")"
{
    git ls-files --others --exclude-standard
    git ls-files --modified
} | grep "\<[a-z][a-z]*/walt/" | \
    grep -v "\.swp$" | \
    grep -v ":w$" | \
    grep -v ":$" | \
while read f
do
	mod_path=$(echo "$f" | sed -e 's/^[a-z]*\///')
	venv_f="${venv_packages}/$mod_path"
    if diff -q "$f" "$venv_f" >/dev/null 2>&1
    then
        # already modified / added in venv
        continue
    fi
    if [ -e "$venv_f" ]
    then
        mode="updated"
    else
        mode="added"
    fi
    mkdir -p "$(dirname "$venv_f")"
    cp "$f" "$venv_f"
    echo $mode $mod_path in venv.
done
