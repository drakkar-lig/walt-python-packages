
@test "walt advanced sql" {
    result="$(echo "\dt" | walt advanced sql | grep -c logstreams)"
    [ "$result" -eq 1 ]
}

@test "walt advanced update-hub-meta" {
    run walt advanced update-hub-meta
    [ "$status" -eq 0 ]
}
