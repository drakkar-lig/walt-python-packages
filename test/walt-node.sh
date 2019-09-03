
# we cannot use 'walt node run' in a bats test (issue with keyword "run"),
# so we call this function instead
walt_node_rn()
{
    # we should run this in a subprocess (bats issue related to keyword "run"?)
    # otherwise subsequent tests will not be visible
    {
        walt node run "$@"
    } &
    wait -n
}

# apparently bats does not like keyword "expose" either
test_walt_node_xpse()
{
    node="$1"

    # run a echo server on the node for 5 seconds
    {
        timeout -s INT 5 walt node run "$node" -- busybox nc -l -p 80 -e /bin/cat
    } &

    # use walt node expose for the same period, to expose the port on local machine
    {
        timeout -s INT 5 walt node expose "$node" 80 46871
    } &

    # check that text is echoed locally
    sleep 2
    echo OK | nc 127.0.0.1 46871 | grep OK
}

test_walt_node_blnk()
{
    node="$1"
    status_file="$(mktemp)"

    # run walt node blink
    {
        echo launch blink && \
        timeout -s INT 10 walt node blink "$node" 5 && \
        echo end blink
    } &

    # in our test image, /bin/blink updates a file /tmp/blink-status
    # between 0 and 5 seconds it should be "on", then "off"
    sleep 1 && \
    echo launch cp && \
    walt node cp $node:/tmp/blink-status $status_file && cat $status_file >&2 && cat $status_file | grep "on" && \
    sleep 5 && \
    echo launch cp && \
    walt node cp $node:/tmp/blink-status $status_file && cat $status_file >&2 && cat $status_file | grep "off"
}
