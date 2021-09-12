#!/bin/bash
echo "Checking for CHANGELOG changes"
[ ! -z "$(git diff develop... -- ../CHANGELOG.rst)" ] || ( echo "Remember to update the CHANGELOG.rst" && exit 1 )