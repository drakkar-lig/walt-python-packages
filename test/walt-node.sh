
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
