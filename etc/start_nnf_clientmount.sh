#!/bin/bash

flux getrabbit || exit 0  # exit if not configured with rabbits

# start the nnf-clientmount service
systemctl start nnf-clientmount
