#!/bin/bash

THIS_DIR="$(cd "$(dirname $0)"; pwd)"
TESTS_DIR="$(cd "$THIS_DIR/../test"; pwd)"
TESTSUITE_TMP_DIR="$(mktemp -d)"
export TESTSUITE_TMP_DIR

__test_suite_debug_tests=0

if [ "$1" = "--debug" ]
then
    __test_suite_debug_tests=1
    shift
fi

__testsuite_num_tests=0
__testsuite_num_tests_failed=0
__testsuite_num_tests_skipped=0
__testsuite_test_name=""

skip_test() {
    echo "$*" > $TESTSUITE_TMP_DIR/skipped
    return 1
}

__testsuite_exec_prev_test() {
    if [[ $__testsuite_test_name != "" ]]
    then
        __testsuite_num_tests=$((__testsuite_num_tests+1))
        echo -n "   $__testsuite_test_name"

        # we have to enable 'errexit' option (i.e. '-e') for the test code fragment.
        # however, if it is still activated when the test function exits, it will
        # make this framework code end immediately.
        # and code such as the following does not work:
        # __testsuite_func && retcode=$? || retcode=$?
        # because 'errexit' is disabled in such an expression
        # (see https://stackoverflow.com/a/19789651)
        # so we use parenthesis to start a subshell in which we can set this option
        # independently from this framework code.
        __testsuite_output="$(
            if [ $__test_suite_debug_tests -eq 1 ]
            then
            (
                set -xeuo pipefail
                __testsuite_func
            ) 1>&2  # debug: send everything to stderr for immediate display
            else
            (
                set -xeuo pipefail
                __testsuite_func
            ) 2>&1  # not debug: catch and hide everything (unless an error is detected)
            fi
        )"
        __testsuite_result=$?

        if [ "$__testsuite_result" = 0 ]
        then
            echo -e '\r \xE2\x9C\x94'
        elif [ -f $TESTSUITE_TMP_DIR/skipped ]
        then
            __testsuite_num_tests_skipped=$((__testsuite_num_tests_skipped+1))
            echo -e "\e[33m\r - $__testsuite_test_name -- skipped -- $(cat $TESTSUITE_TMP_DIR/skipped)\e[0m"
            rm $TESTSUITE_TMP_DIR/skipped
        else
            __testsuite_num_tests_failed=$((__testsuite_num_tests_failed+1))
            echo -e "\e[31m\r \xE2\x9C\x97 $__testsuite_test_name"
            echo "$__testsuite_output"
            echo -e "\e[0m"
        fi
    fi
    __testsuite_test_name=""
}

declare -a SH_TEST_FILES
declare -a PY_TEST_FILES
while [[ $# != 0 ]]
do
    case "$1" in
        --help|-h)
            echo "$(basename "$0"): [tests]"
            echo "    [tests] is the list of tests to run.  Should be the"\
                 "name of a test in the $TESTS_DIR directory, without its"\
                 ".sh or .py extension.  Default: run all tests."
            exit 0
            ;;
        -*)
            echo >&2 -- "$1: unsupported option"
            exit 1
            ;;
        *)
            if [ -e "$TESTS_DIR/$1.sh" ]
            then
                SH_TEST_FILES+=("$TESTS_DIR/$1.sh")
            elif [ -e "$TESTS_DIR/$1.py" ]
            then
                PY_TEST_FILES+=("$TESTS_DIR/$1.py")
            else
                echo >&2 "$1: no such test"
                exit 1
            fi
            ;;
    esac
    shift
done

if [[ ${#SH_TEST_FILES[@]} == 0 && ${#PY_TEST_FILES[@]} == 0 ]]
then
    ls "$TESTS_DIR"/*.sh >/dev/null 2>&1 && SH_TEST_FILES=("$TESTS_DIR"/*.sh)
    ls "$TESTS_DIR"/*.py >/dev/null 2>&1 && PY_TEST_FILES=("$TESTS_DIR"/*.py)
fi

__prepared_sh_source="$TMPDIR/prepared_source.sh"

for __testsuite_source_file in "${SH_TEST_FILES[@]}"
do
    sed -e 's/\<define_test\>/__testsuite_exec_prev_test; __testsuite_test_name=$(echo/' \
        -e 's/\<as\>/); __testsuite_func() /' "$__testsuite_source_file" > "$__prepared_sh_source"
    source "$__prepared_sh_source"
    __testsuite_exec_prev_test
done

cd "$TESTS_DIR"/..
for __testsuite_source_file in "${PY_TEST_FILES[@]}"
do
    $THIS_DIR/py-test-file.py "$__testsuite_source_file" describe | while read num_test __testsuite_test_name
    do
        cat << EOF
__testsuite_exec_prev_test
__testsuite_test_name="$__testsuite_test_name"
__testsuite_func() {
    $THIS_DIR/py-test-file.py "$__testsuite_source_file" run $num_test
}
EOF
    done > "$__prepared_sh_source"
    source "$__prepared_sh_source"
    __testsuite_exec_prev_test
done

rm -rf "$TMPDIR"

# summary
echo
echo -n " $__testsuite_num_tests test(s), "
if [[ $__testsuite_num_tests_skipped -gt 0 ]]
then
    echo -en "\e[33m$__testsuite_num_tests_skipped skipped\e[0m, "
fi
if [[ $__testsuite_num_tests_failed -eq 0 ]]
then
    echo "no failure."
else
    echo -e "\e[31m$__testsuite_num_tests_failed failure(s)\e[0m."
fi

