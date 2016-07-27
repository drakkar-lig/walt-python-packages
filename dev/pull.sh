#!/bin/bash
set -e
SUBPACKAGES="$*"
. dev/tools/functions.sh

branch=$(git branch | grep '*' | awk '{print $2}')
case "$branch" in
    master) repo_option='';;
    test)   repo_option='-i https://testpypi.python.org/simple';;
    *)      >&2 echo "Only branches 'master' and 'test' are allowed. You are on branch '$branch'."
            exit;;
esac

for subpackage in $SUBPACKAGES
do
    sudo pip install $repo_option --upgrade walt-$subpackage
done

