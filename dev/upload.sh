#!/bin/bash
set -e
URL=https://github.com/drakkar-lig/walt-python-packages.git
SUBPACKAGES="$*"

prompt_pypi_credentials()
{
    password=''
    username=''
    while [ "$username" = "" ]
    do
        read -p "PyPI username: " username
    done
    while [ "$password" = "" ]
    do
        read -p "PyPI password: " -s password
    done
    echo "$username"
    echo "$password"
}

backup_pypirc()
{
    if [ -f '~/.pypirc' ]
    then
        cp ~/.pypirc ~/.pypirc.backup
        echo ~/.pypirc.backup
    else
        echo none
    fi
}

restore_pypirc()
{
    backup="$1"
    if [ "$1" != "none" ]
    then
        mv ~/.pypirc.backup ~/.pypirc
    fi
}

create_pypirc()
{
    pypi_username="$1"   
    pypi_password="$2"   

    cat > ~/.pypirc << EOF
[distutils]
index-servers=
    pypi

[pypi]
username:$pypi_username
password:$pypi_password
EOF
}

do_subpackages()
{
    for subpackage in $SUBPACKAGES
    do
        cd $subpackage
        python setup.py $* >/dev/null
        cd ..
    done
}

remote=$(git remote -v | grep fetch | grep $URL | awk '{print $1}')

if [ "$remote" = "" ]; then
    >&2 echo "This operation is only allowed when the remote git repository is $URL (otherwise version numbering conflicts will occur)."
    exit
fi

stat_porcelain=$(git status --porcelain -u no | wc -l)

if [ ! -n "$stat_porcelain" ]; then
    >&2 echo "Your repository is not clean, please commit your changes using git commit"
    exit
fi
    
stat_ahead=$(git status --porcelain -b | grep -c ahead)

if [ $stat_ahead = 1 ]; then
    >&2 echo "You need to push your changes using git push before publishing in Pypi"
    exit
fi

pypi_credentials="$(prompt_pypi_credentials)"
pypi_username="$(echo "$pypi_credentials" | head -n 1)"
pypi_password="$(echo "$pypi_credentials" | tail -n 1)"

# create .pypirc
pypirc_backup=$(backup_pypirc)
create_pypirc "$pypi_username" "$pypi_password"

# create archives
do_subpackages sdist

# get the right to modify each project on PyPI
do_subpackages register

git fetch $remote 'refs/tags/*:refs/tags/*'
last_upload_in_git=$(git tag | grep upload_ | tr '_' ' ' | awk '{print $2}' | sort -n | tail -n 1)
last_upload_in_versions=$(cat common/walt/common/versions.py | grep UPLOAD | grep -o '[0-9]*')
if [ "$last_upload_in_git" != "$last_upload_in_versions" ]; then
    echo "Please check your upload number in versions.py"
    exit
fi

# update file walt/common/versions.py (increment UPLOAD and update API numbers if needed)
dev/version/versions-updater.py
echo "versions.py updated"
dev/version/info-updater.py
echo "info.py files updated"

new_upload=$((last_upload_in_git+1))
git add common/walt/common/versions.py
git commit -m "Upload $new_upload"

# upload packages
do_subpackages sdist upload

# restore .pypirc
restore_pypirc $pypirc_backup

newTag="upload_$new_upload"
git tag -a $newTag
git push --tag
