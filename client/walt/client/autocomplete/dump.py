from inspect import getfullargspec

from plumbum.lib import getdoc
from walt.doc.md import get_described_topics, get_topics


# Notes:
# * The code was designed for bash at first. In zsh, we finally used
#   low level completion features (i.e. the global variables passed
#   to the function, such as "words" and "CURRENT", and compadd()
#   to return the completions) because using high level functions
#   such as _arguments() would require much different code.
# * Zsh apparently maintains a cache of completion replies itself, so
#   the cache feature is only implemented for bash.


HEADER = {
"bash": """\
_WALT_COMP_CACHE_VALIDITY_SECS=3
_walt_comp_debug=0

_walt_comp_get_cols() {
    if [ "$COLUMNS" = "" ]
    then
        COLUMNS="$(tput cols 2>/dev/null)"
    fi
    if [ "$COLUMNS" != "" ]
    then
        echo "$COLUMNS"
    fi
}

_walt_comp_pad_reply_lines() {
    local cols="$1"
    for i in ${!COMPREPLY[@]}
    do
        COMPREPLY[i]="$(printf '%-*s\\n' $cols "${COMPREPLY[i]}")"
    done
}

_walt_comp_print_array() {
    echo "size ${#} -- "
    i=1
    for item in "$@"
    do
        echo "    $i: $(echo $item)"
        i=$((i+1))
    done
}

# filter lines starting with a prefix
# and save result in COMPREPLY
# (for some reason compgen -W sometimes does not work with lines
# and using grep is slower)
_walt_compgen_lines()
{
    prefix="$1"
    lines="$2"
    # prefix all lines with "__del"
    lines="__del${lines//$'\\n'/$'\\n'__del}"
    # replace __del${prefix} with ${prefix}
    lines="${lines//__del${prefix}/${prefix}}"
    # use newline as field separator
    OLDIFS="$IFS"; IFS=$'\\n'
    # turn lines text into an array
    array_lines=($lines)
    # remove lines still prefixed with __del
    # and save result into COMPREPLY
    COMPREPLY=(${array_lines[@]//__del*})
    # restore field separator
    IFS="$OLDIFS"
}

_walt_date() {
    printf '%(%s)T'  # bash builtin, faster than "date +%s"
}

__common_functions__

_walt_complete()
{
    local cur prev words cword split
    _init_completion -s -n : || return
    local partial_token="${cur}"

    if [ "$_walt_comp_debug" -eq 1 ]
    then
        echo "INPUT ** ${words[@]}" >> log.txt
    fi
    # if last request was the same and recent, return the same
    if [ "${words[*]}" = "$_walt_comp_cache_last_request" ]
    then
        # cache hit, check if not too old
        if [ $((_walt_comp_cache_timestamp+_WALT_COMP_CACHE_VALIDITY_SECS)) \\
                -ge "$(_walt_date)" ]
        then
            # ok
            COMPREPLY=("${_walt_comp_cache_last_reply[@]}")
            return 0
        fi
    fi
    local subapps=""
    local described_subapps=""
    local options="--help"
    local described_options="\\
--help -- Prints this help message and quits"
    local num_positional_args=0
    declare -A valued_option_types=() positional_arg_types=()
    local validated="${words[*]:0:$COMP_CWORD}"
    case "${validated}" in
""",

"zsh": """\
#compdef _walt walt

_walt_comp_debug=0

function _walt_comp_reply {
    if [ "$possible_described" != "" ]
    then
        # if completions are described:
        # 1- turn possible_described into array
        oldifs="$IFS";
        IFS=$'\\n' possible_described=($(echo "$possible_described"))
        IFS="$oldifs"
        # 2- log
        if [ "$_walt_comp_debug" -eq 1 ]
        then
            echo "OUTPUT ** $(typeset possible) $(typeset possible_described)" \
                    >> log.txt
        fi
        # 3- add completions
        compadd -Q -d possible_described -l -- $possible
    else
        # simple completions without description
        # 1- log
        if [ "$_walt_comp_debug" -eq 1 ]
        then
            echo "OUTPUT ** $(typeset possible)" >> log.txt
        fi
        # 2- add completions
        compadd -Q -- $possible
    fi
}

__common_functions__

function _walt
{
    words=("${words[@]:0:$CURRENT}")
    if [ "$_walt_comp_debug" -eq 1 ]
    then
        echo "INPUT ** $(typeset -p words) CURRENT=$CURRENT" >> log.txt
    fi
    local partial_token="${words[$CURRENT]}"
    local subapps=""
    local described_subapps=""
    local options="--help"
    local described_options="\\
--help:Prints this help message and quits"
    local num_positional_args=0
    declare -A valued_option_types=() positional_arg_types=()
    local validated="${words[*]}"
    case "${validated}" in
"""
}

APP_SECTION = """\
        "%(path)s"*)
            %(assign_vars)s;;
"""

COMMON_FUNCTIONS = """\
_walt_comp_get_possible() {
    local positional_idx=-1
    local positional_started=0
    local prev_token_type='tool'
    local token
    for token in "${words[@]:1}"
    do
        token_start_c="${token:0:1}"
        case "$prev_token_type" in
            'tool')
                if [ "$token_start_c" = "-" ]
                then
                    token_type='option-without-value'
                else
                    token_type='category'
                fi
                ;;
            'category')
                if [ "$token_start_c" = "-" ]
                then
                    token_type='option-without-value'
                else
                    token_type='command'
                fi
                ;;
            'option-with-value')
                token_type='value-of-option'
                ;;
            'command'|'option-without-value'|'value-of-option'| \\
                    'positional'|'start-of-positional')
                if [ $positional_started -eq 1 ]
                then
                    let positional_idx+=1
                    token_type='positional'
                elif [ "$token" = "--" ]
                then
                    token_type='start-of-positional'
                    positional_started=1
                elif [ "$token_start_c" = "-" ]
                then
                    valued_option_type="${valued_option_types[$token]}"
                    if [ "$valued_option_type" != "" ]
                    then
                        token_type='option-with-value'
                    else
                        token_type='option-without-value'
                    fi
                else
                    let positional_idx+=1
                    positional_started=1
                    token_type='positional'
                fi
                ;;
        esac
        prev_token_type="${token_type}"  # for next loop
    done

    # after previous loop, $token_type gives us the type of the expected token
    case "$token_type" in
        'value-of-option')
            if [ "$valued_option_type" = "DIRECTORY" ]
            then
                possible="$(compgen -d -- "$partial_token")"
            else
                possible="$(walt-autocomplete-helper \
                    "$valued_option_type" "${words[@]}")"
                if [ "$?" -ne 0 ]
                then    # issue (it is important not to store this result in cache)
                    return 1
                fi
            fi
            ;;
        'positional')
            if [ "$positional_idx" -ge "$num_positional_args" ]
            then
                # part of varargs, type given as last value of positional_arg_types
                positional_idx=$num_positional_args
            fi
            local positional_arg_type=${positional_arg_types[$positional_idx]}
            # we must be able to handle help correctly,
            # even if the server is down.
            if [ "$positional_arg_type" = "HELP_TOPIC" ]
            then
                # auto-generated data
                possible="__help_topics__"
                possible_described="\\
__described_help_topics__"
            elif [ "$positional_arg_type" != "" ]
            then
                possible="$(walt-autocomplete-helper \
                    "$positional_arg_type" "${words[@]}")"
                if [ "$?" -ne 0 ]
                then    # issue (it is important not to store this result in cache)
                    return 1
                fi
            fi
            ;;
        'start-of-positional'|'option-with-value'|'option-without-value')
            # since last token typed is incomplete, here we just know that
            # this token being typed is of the form --<something>: this is an option
            possible="$options"
            possible_described="$described_options"
            ;;
        'category'|'command')
            possible="$subapps"
            possible_described="$described_subapps"
            ;;
        'invalid')
            ;;
    esac
}
"""

FOOTER = {
"bash": """\
    esac
    local possible=""
    local possible_described=""
    _walt_comp_get_possible
    COMPREPLY=( $(compgen -W "$possible" -- "$partial_token") )
    if [ ${#COMPREPLY[@]} -gt 1 -a "$possible_described" != "" ]
    then
        # we have more than one possible completion values, we will try to
        # display them with their description.
        # by padding with space on the right, we can force bash to display
        # these strings on one single column (because multi-column display
        # is not very readable in our case).
        local cols=$(_walt_comp_get_cols)
        if [ "$cols" = "" ]
        then
            # we cannot pad, so keep the basic completions display
            return 0
        fi
        _walt_compgen_lines "$partial_token" "$possible_described"
        _walt_comp_pad_reply_lines "$cols"
    fi
    if [ "$_walt_comp_debug" -eq 1 ]
    then
        echo "OUTPUT ** $(_walt_comp_print_array "${COMPREPLY[@]}")" >> log.txt
    fi
    # save in cache for possible reuse
    _walt_comp_cache_timestamp="$(_walt_date)"
    _walt_comp_cache_last_request="${words[*]}"
    _walt_comp_cache_last_reply=("${COMPREPLY[@]}")
    # fix possible issues with ":" in arguments
    __ltrim_colon_completions "$cur"
    return 0
} &&
complete -F _walt_complete walt
""",

"zsh": """\
    esac
    local possible=""
    local -a possible_described=()
    _walt_comp_get_possible
    possible=($(echo $possible))
    _walt_comp_reply
}
"""
}

# when the command has variable arguments
# (e.g. walt node config <node_set> <config_item>...)
# we store the type of the variable arguments at the
# end of "positional_arg_types" array.
# for instance for "walt node config" we get:
# * num_positional_args = 1
# * positional_arg_types = [ "NODE_SET", "NODE_CONFIG_PARAM" ]
def get_arg_types(app):
    positional = getattr(app.main, "positional", None)
    if positional is None:
        m = getfullargspec(app.main)
        positional = [None] * len(m.args[1:])
        arg_positions = {argname: idx for idx, argname in enumerate(m.args[1:])}
        num_args = len(positional)
        if m.varargs is not None:
            positional += [None]
            arg_positions[m.varargs] = len(positional) - 1
        for argname, argclass in m.annotations.items():
            argpos = arg_positions[argname]
            positional[argpos] = argclass
    else:
        num_args = len(positional)
    return num_args, [getattr(argclass, "__name__", None) for argclass in positional]


def dump_as_array(d):
    return "(" + " ".join(f'["{k}"]="{v}"' for (k, v) in d.items()) + ")"


def get_app_info(app):
    doc = app.DESCRIPTION if app.DESCRIPTION else getdoc(app)
    app_info = {"description": doc, "children": {}, "options": {}}
    for name, child in app._subcommands.items():
        subapp = child.subapplication("walt")
        app_info["children"][name] = get_app_info(subapp)
    app_info["num_args"], app_info["args"] = get_arg_types(app)
    for name, optinfo in app._switches_by_name.items():
        if len(name) == 1:  # single letter option, ignore
            continue
        name = "--" + name
        app_info["options"][name] = {"description": optinfo.help}
        if optinfo.argtype is None:
            app_info["options"][name]["opttype"] = "standalone"
        else:
            app_info["options"][name]["opttype"] = "valued"
            app_info["options"][name]["argname"] = optinfo.argname
    return app_info


def get_described_items(items, get_item_fullname):
    if len(items) == 0:
        return ""
    fullname_and_desc = tuple(
        (get_item_fullname(name, item_info), item_info["description"])
        for (name, item_info) in items.items()
    )
    name_max = max(len(fullname) for fullname, desc in fullname_and_desc)
    return "\n".join(
        f"""{fullname:<{name_max}} -- {desc}""" \
                for fullname, desc in fullname_and_desc
        )


def dump_assign_vars(assign_vars):
    indented_cr = "\n" + (" " * 12)
    assignments = tuple(f"{name}={value}" for name, value in assign_vars)
    assignments += ("",)  # will add one more indented carriage return below
    return indented_cr.join(assignments)


def get_option_fullname(optname, optinfo):
    if optinfo["opttype"] == "standalone":
        return optname
    else:
        return optname + " " + optinfo["argname"]


def quoted(name):
    return f'"{name}"'


def dump_app_section(path, app_tree):
    assign_vars = []
    subapps = app_tree["children"]
    options = app_tree["options"]
    args = app_tree["args"]
    num_args = app_tree["num_args"]
    if len(subapps) > 0:
        described_subapps = get_described_items(subapps,
                                                (lambda name, app_info: name))
        assign_vars += [
            ("subapps", quoted(" ".join(subapps))),
            ("described_subapps", '"\\\n' + described_subapps + '"'),
        ]
    # various apps only have the '--help' option: this is our default case.
    # we only override variables 'options' and 'described_options' if this app
    # has more options (thus the "> 1" condition here).
    if len(options) > 1:
        described_options = get_described_items(options, get_option_fullname)
        assign_vars += [
            ("options", quoted(" ".join(options))),
            ("described_options", '"\\\n' + described_options + '"'),
        ]
        optargnames = {
            optname: optinfo["argname"]
            for optname, optinfo in options.items()
            if optinfo["opttype"] == "valued"
        }
        if len(optargnames) > 0:
            assign_vars += [("valued_option_types", dump_as_array(optargnames))]
    if num_args != 0:
        assign_vars += [("num_positional_args", num_args)]
    enumerated_args = {idx: v for idx, v in enumerate(args) if v is not None}
    if len(enumerated_args) > 0:
        assign_vars += [("positional_arg_types", dump_as_array(enumerated_args))]
    print(
        APP_SECTION
        % dict(path=" ".join(path), assign_vars=dump_assign_vars(assign_vars)),
        end="",
    )


def dump_app(app_tree, path):
    # print sub apps sections
    for subapp_name, subapp in app_tree["children"].items():
        dump_app(subapp, path + (subapp_name,))
    # print app section
    dump_app_section(path, app_tree)


def dump_shell_autocomplete(app, shell):
    app_tree = get_app_info(app.root_app)
    # print header
    h_topics = " ".join(get_topics())
    described_h_topics = "\n".join(get_described_topics()).replace("`", "")
    header = HEADER[shell]
    header = header.replace("__common_functions__", COMMON_FUNCTIONS.strip())
    header = header.replace("__help_topics__", h_topics)
    header = header.replace("__described_help_topics__", described_h_topics)
    print(header, end="")
    # print apps and sub-apps sections
    dump_app(app_tree, path=("walt",))
    # print footer
    print(FOOTER[shell], end="")


def dump_bash_autocomplete(app):
    dump_shell_autocomplete(app, shell="bash")


def dump_zsh_autocomplete(app):
    dump_shell_autocomplete(app, shell="zsh")
