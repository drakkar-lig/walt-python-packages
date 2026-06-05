#!/bin/bash
set -e

git_root="$(git rev-parse --show-toplevel)"
cd "$git_root"
# activate the virtual env if not done yet
[ -z "$VIRTUAL_ENV" ] && . .venv/bin/activate
venv_root=$(python3 -c 'import sys; print(sys.prefix)')
venv_packages="$(ls -d "${venv_root}/lib/python"*"/site-packages")"

file_changes="$({
    git diff-index --name-status HEAD~10
    git ls-files --others --exclude-standard | awk '{print "A " $1}'
} | \
    grep -v "\.swp$" | \
    grep -v ":w$" | \
    grep -v ":$"
)"

{
    # handle files in <python-package>/walt/
    echo "$file_changes" | grep "[[:space:]][a-z][a-z0-9-]*/walt/" | \
    while read op f
    do
        mod_path=$(echo "$f" | sed -e 's/^[a-z0-9-]*\///')
        venv_f="${venv_packages}/$mod_path"
        echo "$op" "$f" "$venv_f"
    done

    # handle files in <python-package>/sh/
    echo "$file_changes" | grep "[[:space:]][a-z][a-z0-9-]*/sh/" | \
    while read op f
    do
        venv_f="${venv_root}/bin/$(basename "$f")"
        echo "$op" "$f" "$venv_f"
    done
} | while read op f venv_f
do
    if [ "$op" = "D" ]
    then
        if [ ! -e "$venv_f" ]
        then
            # already deleted
            continue
        fi
        mode="deleted"
        rm "$venv_f"
    else
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
    fi
    echo $mode $venv_f
done
