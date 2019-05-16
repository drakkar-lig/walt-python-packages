#!/bin/bash
set -e
URL=github.com/drakkar-lig/walt-python-packages
SUBPACKAGES="$*"
. dev/tools/functions.sh

which twine >/dev/null || {
    echo "twine command is missing! Aborted." >&2
    exit
}

branch=$(git branch | grep '*' | awk '{print $2}')
case "$branch" in
    master) tag_prefix='upload_'
            repo_option=''
            ;;
    test)   tag_prefix='testupload_'
            repo_option='--repository-url https://test.pypi.org/legacy/'
            ;;
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

# build and check that packages are fine
rm -rf */dist
do_subpackages python setup.py sdist bdist_wheel

# everything seems fine, let's start the real work

# increment the last upload
git fetch $remote 'refs/tags/*:refs/tags/*'
last_upload_in_git=$(git tag | grep "^$tag_prefix" | tr '_' ' ' | awk '{print $2}' | sort -n | tail -n 1)
new_upload=$((last_upload_in_git+1))

# update files containing version number
echo "__version__ = '$new_upload'" > common/walt/common/version.py
dev/info-updater.py
echo "info.py, version.py files updated"

newTag="$tag_prefix$new_upload"
git commit -a -m "$newTag (automated by $0)"

git tag -m "$newTag (automated by $0)" -a $newTag
git push --tag $remote $branch

# rebuild updated packages
rm -rf */dist
do_subpackages python setup.py sdist bdist_wheel

# upload: upload packages
do_subpackages twine upload $repo_option dist/*

