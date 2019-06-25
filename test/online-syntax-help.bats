
check_expected_syntax() {
    out_filename="$1"
    # cmd is deduced from file name, by removing ".out" prefix,
    # and replacing at most 2 dashes per a space (walt <category> <command>)
    cmd=$(echo "$out_filename" | sed -e "s/\.out$//" | sed -e 's/-/ /' | sed -e 's/-/ /')
    expected="$(cat $BATS_TEST_DIRNAME/syntax/$out_filename)"
    result="$(LC_ALL=C $cmd --help || true)"
    if [ "$result" != "$expected" ]
    then
        echo "$out_filename: '$cmd' online syntax help differs from expected!"
        return 1    # fail
    fi
}

@test "online syntax help" {
    syntax_files=$(cd $BATS_TEST_DIRNAME/syntax; ls *.out)
    for syntax_file in $syntax_files
    do
        check_expected_syntax $syntax_file
    done
}
