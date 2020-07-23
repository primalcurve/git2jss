#!/bin/bash

while true
do
loggedinuser=$(/bin/ls -l /dev/console | /usr/bin/awk '{ print $3 }')
echo $loggedinuser
    if [ "${loggedinuser}" == "root" ] || [ "${loggedinuser}" == "_mbsetupuser" ]; then
    echo "is root or mbsetupuser"
    sleep 10
    else
    echo "is local user"
    break
    fi
done