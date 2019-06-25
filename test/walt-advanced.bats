
@test "walt advanced sql" {
    result="$(echo "\dt" | walt advanced sql | grep -c logstreams)"
    [ "$result" -eq 1 ]
}
