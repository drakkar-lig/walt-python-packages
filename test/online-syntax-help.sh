
# note: to generate a file syntax/<cmd>.out use
# LC_ALL=C <cmd> --help | sed -e "s/:{.*}//" > syntax/<cmd>.out
# for instance:
# LC_ALL=C walt advanced --help | sed -e "s/:{.*}//" > syntax/walt-advanced.out

check_expected_syntax() {
    out_filename="$1"
    # cmd is deduced from file name, by removing ".out" prefix,
    # and replacing at most 2 dashes per a space (walt <category> <command>)
    cmd=$(echo "$out_filename" | sed -e "s/\.out$//" | sed -e 's/-/ /' | sed -e 's/-/ /')
    expected="$(cat $TESTS_DIR/syntax/$out_filename | grep -v "Version:" | tr -d '[:space:]')"
    # the sed expression is used to discard the list of values of a cli.Set,
    # because the order is not constant
    # tr allows to ignore differences in spacing (may occur with a different terminal size)
    result="$(LC_ALL=C $cmd --help | grep -v "Version:" | sed -e "s/:{.*}//" | tr -d '[:space:]' || true)"
    if [ "$result" != "$expected" ]
    then
        echo "$out_filename: '$cmd' online syntax help differs from expected!"
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
