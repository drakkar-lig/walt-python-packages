#!/bin/bash

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
    fi
}

restore_pypirc()
{
    if [ -f ~/.pypirc.backup ]
    then
        mv ~/.pypirc.backup ~/.pypirc
    else
        # if we have no backup, this means
        # we had no file at startup
        rm ~/.pypirc
    fi
}

create_pypirc()
{
    branch="$1"
    pypi_username="$2"
    pypi_password="$3"

    case "$branch" in
        master)
            repo=pypi
            repo_url=https://pypi.python.org/pypi;;
        test)
            repo=pypitest
            repo_url=https://testpypi.python.org/pypi;;
    esac

    cat > ~/.pypirc << EOF
[distutils]
index-servers=
    $repo

[$repo]
repository: $repo_url
username: $pypi_username
password: $pypi_password
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

