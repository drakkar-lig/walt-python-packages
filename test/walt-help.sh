
define_test "walt help list" as {
    walt help list
}

define_test "walt help show (no tty)" as {
    # test non-interactive (no tty)
    walt help show | grep -i walt
}

define_test "walt help show (tty)" as {
    # test interactive session
    # we use expect to emulate a tty session.
    # we send "q" after 2 seconds.
    # walt command should not timeout, and return code 0 (OK)
    which expect || {
        skip_test 'requires the "expect" command'
    }

    expect << EOF
set timeout 4
spawn walt help show
sleep 2
send "q\r"
expect {
    eof     { exit 0 }
    timeout { puts "timeout: 'walt help show' did not quit 4 seconds after 'q' was sent!"; exit 1 }
}
EOF
}
