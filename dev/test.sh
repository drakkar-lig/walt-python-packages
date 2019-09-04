#!/bin/bash

THIS_DIR="$(cd $(dirname $0); pwd)"
TESTS_DIR="$(cd $THIS_DIR/../test; pwd)"

__testsuite_num_tests=0
__testsuite_num_tests_failed=0
__testsuite_test_name=""

__testsuite_exec_prev_test() {
    if [ "$__testsuite_test_name" != "" ]
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
            (
                set -xeuo pipefail
                __testsuite_func
            ) 2>&1
        )"
        __testsuite_result=$?

        if [ "$__testsuite_result" = 0 ]
        then
            echo -e '\r \xE2\x9C\x94'
        else
            __testsuite_num_tests_failed=$((__testsuite_num_tests_failed+1))
            echo -e "\e[31m\r \xE2\x9C\x97 $__testsuite_test_name"
            echo "$__testsuite_output"
            echo -e "\e[0m"
        fi
    fi
    __testsuite_test_name=""
}

__testsuite_modified_source=$(mktemp)

for __testsuite_source_file in $TESTS_DIR/*.sh
do
    sed -e 's/\<define_test\>/__testsuite_exec_prev_test; __testsuite_test_name=$(echo/' \
        -e 's/\<as\>/); __testsuite_func() /' $__testsuite_source_file > $__testsuite_modified_source
    source $__testsuite_modified_source
    __testsuite_exec_prev_test
done

rm $__testsuite_modified_source

# summary
echo
echo -n " $__testsuite_num_tests test(s), "
if [ $__testsuite_num_tests_failed -eq 0 ]
then
    echo "no failure."
else
    echo -e "\e[31m$__testsuite_num_tests_failed failure(s)\e[0m."
fi

