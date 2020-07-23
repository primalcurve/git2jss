#!/bin/sh

echo "<result>$(diskutil info / | grep Personality | awk -F':' ' { print $NF } ' | sed -e 's/^[[:space:]]*//')</result>"

exit 0