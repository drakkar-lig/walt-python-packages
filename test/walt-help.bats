
@test "walt help list" {
    run walt help list
    [ "$status" -eq 0 ]
}

@test "walt help show" {
    # send "q" after 2 seconds.
    # walt command should not timeout, and return code 0 (OK)
    { sleep 2; echo q; } | timeout -s INT 3 walt help show
    [ "$?" = "0" ]
}
