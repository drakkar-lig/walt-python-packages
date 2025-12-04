
# note: to generate a file syntax/<cmd>.out use
# LC_ALL=C <cmd> --help > syntax/<cmd>.out
# for instance:
# LC_ALL=C walt advanced --help > syntax/walt-advanced.out

# The grep commands allow to ignore volatile values of the "status box"
# printed when typing `walt` with no arguments.
# The sed expression is used to discard the list of values of a cli.Set,
# because the order is not constant.
# Command tr allows to ignore differences in spacing (may occur with a
# different terminal size).
filter_help_text() {
    grep -v "Server:" |
        grep -v "Version:" |
        grep -v "Completion:" |
        grep -v "^(\*)" |
        sed -e "s/:{.*}//" |
        tr -d '[:space:]' || true
}

check_expected_syntax() {
    out_filename="$1"
    # cmd is deduced from file name, by removing ".out" prefix,
    # and replacing at most 2 dashes per a space (walt <category> <command>)
    cmd=$(echo "$out_filename" |
          sed -e "s/\.out$//" |
          sed -e 's/-/ /' |
          sed -e 's/-/ /')
    expected="$(filter_help_text < $TESTS_DIR/syntax/$out_filename)"
    result="$(LC_ALL=C $cmd --help | filter_help_text)"
    if [ "$result" != "$expected" ]
    then
        echo "$out_filename: '$cmd' online syntax help differs" \
             "from expected!"
        return 1    # fail
    fi
}

define_test "online syntax help" as {
    syntax_files=$(cd $TESTS_DIR/syntax; ls *.out)
    for syntax_file in $syntax_files
    do
        check_expected_syntax $syntax_file || return 1
    done
}
