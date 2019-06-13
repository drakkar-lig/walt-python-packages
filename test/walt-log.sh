source $TESTS_DIR/includes/common.sh

test_suite_checkpoint() {
    if [ ! -e /tmp/test_suite_checkpoint ]
    then
        echo test-suite-$$ > /tmp/test_suite_checkpoint
    fi
    cat /tmp/test_suite_checkpoint
}

checkpoint_exists() {
    walt log list-checkpoints | grep "$1 "
}

background_emit_log() {
    delay="$1"
    node="$2"
    logstream="$3"
    logline="$4"

    {
        sleep $delay
        walt node run $node walt-log-echo "$logstream" "$logline"
    } &

    return 0
}

test_log_show_realtime() {
    delay="$1"
    node="$2"
    logstream="$3"
    logline="$4"

    {   # the command should timeout (return code 124)
        timeout -s INT $delay walt log show --realtime --nodes $node --streams "$logstream" || [ "$?" = "124" ]
    } | grep "$logline"
}

test_log_show_history() {
    histrange="$1"
    node="$2"
    logstream="$3"
    logline="$4"

    walt log show --history "$histrange" --nodes $node --streams "$logstream" | grep "$logline"
}

define_test "walt log list-checkpoints" as {
    walt log list-checkpoints
}

define_test "walt log add-checkpoint" as {
    walt log add-checkpoint $(test_suite_checkpoint)
    checkpoint_exists $(test_suite_checkpoint)
}

define_test "walt log show" as {
    walt node create $(test_suite_node)
    node_exists $(test_suite_node)
    walt node wait $(test_suite_node)
    background_emit_log 2 $(test_suite_node) test-suite testing
    test_log_show_realtime 5 $(test_suite_node) test-suite testing
    test_log_show_history $(test_suite_checkpoint): $(test_suite_node) test-suite testing
}

define_test "walt log wait" as {
    background_emit_log 3 $(test_suite_node) test-suite testing
    timeout -s INT 6 walt log wait --nodes $(test_suite_node) --streams "test-suite" "testing"
}

define_test "walt log remove-checkpoint" as {
    walt node remove $(test_suite_node)
    walt log remove-checkpoint $(test_suite_checkpoint)
    if checkpoint_exists $(test_suite_checkpoint)
    then
        return 1    # failed
    fi
}
