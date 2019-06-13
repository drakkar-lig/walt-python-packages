
define_test "walt advanced sql" as {
    result="$(echo "\dt" | walt advanced sql | grep -c logstreams)"
    [ $result -eq 1 ]
}

define_test "walt advanced update-hub-meta" as {
    walt advanced update-hub-meta
}
