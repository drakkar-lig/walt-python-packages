#!/bin/bash
set -e
URL_REGEXP="github.com.drakkar-lig/walt-python-packages"
SUBPACKAGES="$*"

which twine >/dev/null || {
    echo "twine command is missing! Aborted." >&2
    exit
}

fix_binary_package_tag() {
    subpackage="$1"
    whl=$subpackage/dist/*.whl
    platform_tag=$(auditwheel show $whl | grep -o 'manylinux_[0-9]*_[0-9]*_x86_64')
    wheel tags --remove --platform-tag $platform_tag $whl
}

build_subpackages() {
    BUILD_KEEP_VERSION=1 PACKAGES="$SUBPACKAGES" make build-packages
    for d in $SUBPACKAGES
    do
        if [ "$d" = "server" ]
        then
            fix_binary_package_tag $d
        fi
    done
}

remote=$(git remote -v | grep fetch | grep "$URL_REGEXP" | awk '{print $1}')

if [ "$remote" = "" ]; then
    >&2 echo "This operation is only allowed when the remote git repository is the official one (otherwise version numbering conflicts will occur)."
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

branch=$(git branch | grep '*' | awk '{print $2}')
case "$branch" in
    master) repo_option=''
            if [ ! -z "$NEW_VERSION" ]
            then
                new_version="$NEW_VERSION"
                new_tag="upload_$NEW_VERSION"
            else
                echo "Env variable NEW_VERSION is missing. Aborting."
                exit 1
            fi
            ;;
    *)      repo_option='--repository-url https://test.pypi.org/legacy/'
            # increment the last upload
            git fetch $remote 'refs/tags/*:refs/tags/*'
            last_upload_in_git=$(git tag | grep "^$tag_prefix" | tr '_' ' ' | awk '{print $2}' | sort -n | tail -n 1)
            new_upload=$((last_upload_in_git+1))
            new_version="0.${new_upload}"
            new_tag="testupload_${new_upload}"
            ;;
esac

# build and check that packages are fine
build_subpackages

# everything seems fine, let's start the real work

# update files containing version number
cur_version="$(dev/get-version.sh)"
version_update_commit=0
if [ "${cur_version}" != "${new_version}" ]
then
    version_update_commit=1
    dev/set-version.sh "${new_version}"
    git commit -a -m "$new_tag (automated by 'make upload')"
fi

# add tag
git tag -m "$new_tag (automated by 'make upload')" -a $new_tag
git push --tag $remote $branch

if [ "$version_update_commit" -eq 1 ]
then
    # rebuild updated packages
    build_subpackages
fi

# upload: upload packages
if [ "$repo_option" = "" ]
then
    # Real PyPI: let the user test wheel packages and upload them if ok
    echo
    echo "Wheel packages were generated successfully:"
    ls -1 */dist/*.whl
    echo
    echo "You can test them and then perform the real upload to PyPI using:"
    echo "$ twine upload $repo_option */dist/*"
    echo
    if [ "$version_update_commit" -eq 1 ]
    then
        echo "In case of issue, revert the git commit and tag using:"
        echo "$ git tag -d $new_tag"
        echo "$ git push --delete origin $new_tag"
        echo "$ git reset --hard HEAD~1"
        echo "$ git push -f $remote $branch"
    else
        echo "In case of issue, revert the git tag using:"
        echo "$ git tag -d $new_tag"
        echo "$ git push --delete origin $new_tag"
    fi
else
    # TestPyPI: do the upload
    twine upload $repo_option */dist/*
    echo """\
Packages were uploaded to testpypi. At installation use:
$ pip install --index-url https://pypi.org/simple --extra-index-url https://test.pypi.org/simple \
walt-server==$new_version walt-client==$new_version
"""
fi
