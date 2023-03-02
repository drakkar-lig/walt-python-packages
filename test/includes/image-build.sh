
IMAGE_BUILD_GIT_URL=https://github.com/eduble/pc-x86-64-test-suite-mod

test_walt_image_build() {
    image_name_dir="$1"
    image_name_url="$2"

    tmpdir=$(mktemp -d)

    # build from dir
    cd $tmpdir
    git clone $IMAGE_BUILD_GIT_URL .
    walt image build --from-dir . $image_name_dir
    cd

    # build from url
    walt image build --from-url $IMAGE_BUILD_GIT_URL $image_name_url

    # retrieve the file /root/test-result of each image
    # and verify they both contain OK
    walt image cp $image_name_dir:/root/test-result $tmpdir/test-result-dir
    res_dir="$(cat $tmpdir/test-result-dir)"
    walt image cp $image_name_url:/root/test-result $tmpdir/test-result-url
    res_url="$(cat $tmpdir/test-result-url)"
    if [ "$res_dir" != "OK" ]
    then
        echo "Failed: walt image build --from-dir" >&2
        exit 1
    fi
    if [ "$res_url" != "OK" ]
    then
        echo "Failed: walt image build --from-url" >&2
        exit 1
    fi

    # cleanup
    rm -rf tmpdir
}

