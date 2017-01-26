#!/bin/bash
tty=$(tty)

menu()
{
    echo "****************** MENU ****************************"
    echo
    select choice in "$@"
    do
        if [ ! -z "$choice" ]
        then
            echo "Selected: $choice"
            return $REPLY
        fi
    done
    return 0
}

git_diff()
{
    title="$1"
    shift
    {
        echo "****************** $title ****************************"
        echo
        git -c color.diff=always diff "$@"
    } | less -R
}

handle_deleted()
{
    path="$1"
    menu "Confirm deletion" "Restore file" "Pass file for now (^D)" "Stop (^C)"
    case "$?" in
        1)
            git rm "$path"
            ;;
        2)
            git checkout -- "$path"
            ;;
        3)
            ;;
        4)
            SHOULD_STOP=1
            ;;
    esac
}

handle_modified()
{
    path="$1"
    git_diff 'DIFF' "$path"
    echo
    menu "Confirm all changes" "Select changes" "Bypass all changes for now (^D)" "Stop (^C)"
    case "$?" in
        1)
            git add "$path"
            ;;
        2)
            git add -p "$path"
            ;;
        3)
            ;;
        4)
            SHOULD_STOP=1
            ;;
    esac
}

edit_file()
{
    if [ "$EDITOR" = "" ]
    then
        EDITOR="editor"
    fi
    "$EDITOR" "$1"
}

handle_untracked()
{
    path="$1"
    if [ -d "$path" ]
    then    # untracked directory
        for file in $(find "$path" -type f)
        do
            echo "----> $file"
            handle_untracked "$file"
            if [ "$?" = "1" ]
            then
                break
            fi
        done
    elif [ -f "$path" ]
    then    # untracked file
        loop=1
        while [ $loop = 1 ]
        do
            if [ "$(grep -Il . "$path")" = "" ]
            then
                echo "Not displaying this file, since it seems to be binary."
            else
                git_diff 'NEW FILE CONTENT' /dev/null "$path"
            fi
            echo
            menu "Confirm new file" "Edit file" "Bypass file for now (^D)" "Stop (^C)"
            case "$?" in
                1)
                    git add "$path"
                    loop=0
                    ;;
                2)
                    edit_file "$path"
                    ;;
                3)
                    loop=0
                    ;;
                4)
                    loop=0
                    SHOULD_STOP=1
                    return 1
                    ;;
            esac
        done
    fi
}

SHOULD_STOP=0

git status --porcelain | sed -e "s/^.//g" | grep -v '^ ' | \
    while read state path
    do
        exec 6<&0   # save stdin (the pipe)
        exec 0<$tty # direct stdin to the tty for interaction
        status="$(git -c color.status=always status)"
        staged="$(echo "$status" | sed -n '/Changes not staged.*/q;p')"
        staged_numlines="$(echo "$staged" | wc -l)"
        unstaged="$(echo "$status" | sed -n -e '/Changes not staged/,$ p')"
        unstaged_line="$(echo "$unstaged" | sed -n "/^$path$/=")"
        {
            echo "****************** STATUS **************************"
            echo
            {
                # git status: print staged changes
                echo "$staged"
                echo
                # git status: print unstaged changes, with current file highlighted
                echo "$unstaged" | grep -E --color=always "(.*$path)?"
                echo
            } | tail -n +$((staged_numlines + unstaged_line - 8))
        } | less -R
        case "$state" in
            "M")
                handle_modified $path
                ;;
            "D")
                handle_deleted $path
                ;;
            "?")
                handle_untracked $path
                ;;
            *)
                echo 'Unknown state!'
                exit
                ;;
        esac
        exec 0<&6   # restore stdin (to the pipe)
        if [ $SHOULD_STOP -gt 0 ]
        then
            break
        fi
    done
