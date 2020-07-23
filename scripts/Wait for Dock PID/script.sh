#!/bin/bash
dockStatus=$(pgrep -x Dock)

echo "Waiting for Desktop..."

while [[ "$dockStatus" == "" ]]
do
  echo "Desktop is not loaded. Waiting."
  sleep 5
  dockStatus=$(pgrep -x Dock)
done

sleep 5
loggedinuser=$(/bin/ls -l /dev/console | /usr/bin/awk '{ print $3 }')
echo "$loggedinuser has successfully logged on! The Dock appaears to be loaded with PID $dockStatus."
exit 0