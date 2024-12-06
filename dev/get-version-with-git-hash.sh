#!/bin/sh

version="$(dev/get-version.sh)"
if git rev-parse --is-inside-work-tree >/dev/null 2>&1
then
    git_hash=$(git rev-parse --short HEAD)
    echo "$version+$git_hash"
else
    # Not in a git repo
    echo "$version"
fi
