
define_test "walt advanced sql" as {
    result="$(echo "\dt" | walt advanced sql | grep -c logstreams)"
    [ $result -eq 1 ]
}

define_test "walt advanced update-hub-meta" as {
    walt advanced update-hub-meta
}

define_test "walt advanced dump-bash-autocomplete" as {
    autocomp_file=$(mktemp)
    walt advanced dump-bash-autocomplete > $autocomp_file
    bash $autocomp_file   # check we got regular bash code
    rm $autocomp_file
}
