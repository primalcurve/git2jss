#!/bin/sh

currentUser=`defaults read /Library/Preferences/com.apple.loginwindow lastUserName`

/usr/sbin/scutil --set ComputerName "$currentUser"
/usr/sbin/scutil --set HostName "$currentUser"
/usr/sbin/scutil --set LocalHostName "$currentUser"

/usr/local/bin/jamf recon

exit 0