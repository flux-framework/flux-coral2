#!/bin/sh -e

cd shs-cassini-headers/include
install -m 0644 cassini_cntr_defs.h /usr/include
install -m 0644 cxi_prov_hw.h /usr/include
install -m 0644 cassini_user_defs.h /usr/include
cd ../..

cd shs-cxi-driver/include/uapi
install -m 0755 -d /usr/include/uapi/misc
install -m 0644 misc/cxi.h /usr/include/uapi/misc
if test -f ethernet/cxi-abi.h; then
    install -m 0755 -d /usr/include/uapi/ethernet
    install -m 0644 ethernet/cxi-abi.h /usr/include/uapi/ethernet
fi
cd ../../..

cd shs-libcxi
make install
