#!/bin/sh -e

# Last tested with libcxi main branch, at:
#  Thu Sep 4 17:33:35 2025 -0500
#  1eab4498d397c91de4f3652b9dfec1f9045fa4c8
# and contemporaeous cxi-driver.

git clone \
    --recursive --depth=1 https://github.com/HewlettPackard/shs-cassini-headers
mkdir -p cassini-headers
ln -s ../shs-cassini-headers cassini-headers/install

git clone -b ${SHS_CXI_DRIVER_BRANCH:-main} \
    --recursive --depth=1 https://github.com/HewlettPackard/shs-cxi-driver

git clone -b ${SHS_LIBCXI_BRANCH:-main} \
    --recursive --depth=1 https://github.com/HewlettPackard/shs-libcxi

BUILD_CPPFLAGS="-I$(pwd)/shs-cassini-headers/include -I$(pwd)/shs-cxi-driver/include"
BUILD_CFLAGS="-Wno-unused-but-set-variable"

cd shs-libcxi
./autogen.sh
CFLAGS="$BUILD_CPPFLAGS $BUILD_CFLAGS" ./configure --prefix=/usr
make
