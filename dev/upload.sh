#!/bin/bash
set -e
URL=https://github.com/drakkar-lig/walt-python-packages.git
SUBPACKAGES="$*"
. dev/tools/functions.sh

branch=$(git branch | grep '*' | awk '{print $2}')
case "$branch" in
    master) tag_prefix='upload_';;
    test)   tag_prefix='testupload_';;
    *)      >&2 echo "Only branches 'master' and 'test' are allowed. You are on branch '$branch'."
            exit;;
esac

remote=$(git remote -v | grep fetch | grep $URL | awk '{print $1}')

if [ "$remote" = "" ]; then
    >&2 echo "This operation is only allowed when the remote git repository is $URL (otherwise version numbering conflicts will occur)."
    exit
fi

stat_porcelain=$(git status --porcelain | grep -v '??' | wc -l)

if [ "$stat_porcelain" -gt 0 ]; then
    >&2 echo "Your git repository is not clean."
    >&2 echo "Commit your changes using 'git commit', or make sure uncommited changes are not needed and run:"
    >&2 echo "git stash; make upload; git stash pop"
    >&2 echo "Aborted."
    exit
fi
    
stat_ahead=$(git status --porcelain -b | grep ahead | wc -l)

if [ $stat_ahead = 1 ]; then
    >&2 echo "You need to push your changes using git push before publishing in Pypi."
    exit
fi

pypi_credentials="$(prompt_pypi_credentials)"
pypi_username="$(echo "$pypi_credentials" | head -n 1)"
pypi_password="$(echo "$pypi_credentials" | tail -n 1)"

# create .pypirc
backup_pypirc
create_pypirc "$branch" "$pypi_username" "$pypi_password"
trap restore_pypirc EXIT    # on exit, restore

# check that packages are fine
# check that credentials are fine
do_subpackages sdist register -r $repo

# everything seems fine, let's start the real work

# increment the last upload
git fetch $remote 'refs/tags/*:refs/tags/*'
last_upload_in_git=$(git tag | grep "^$tag_prefix" | tr '_' ' ' | awk '{print $2}' | sort -n | tail -n 1)
new_upload=$((last_upload_in_git+1))

# restore versions.py as it was on last upload
git checkout $tag_prefix$last_upload_in_git -- common/walt/common/versions.py
# update file walt/common/versions.py (increment UPLOAD and update API numbers if needed)
dev/version/versions-updater.py $new_upload
echo "versions.py updated"
dev/version/info-updater.py
echo "info.py files updated"

newTag="$tag_prefix$new_upload"
git add common/walt/common/versions.py
git commit -m "$newTag (automated by $0)"

git tag -m "$newTag (automated by $0)" -a $newTag
git push --tag $remote $branch

# sdist: rebuild source packages
# register: submit metadata to index server
# upload: upload packages
do_subpackages sdist register -r $repo upload -r $repo

