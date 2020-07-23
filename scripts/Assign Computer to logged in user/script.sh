#!/bin/sh

currentUser=`defaults read /Library/Preferences/com.apple.loginwindow lastUserName`
firstName=`dscl . -read /Users/$currentUser RealName | tail -1 | awk '{print $1}' | tr '[:upper:]' '[:lower:]' | tr -d '[:punct:]'`
lastName=`dscl . -read /Users/$currentUser RealName | tail -1 | awk '{print $NF}' | tr '[:upper:]' '[:lower:]' | tr -d '[:punct:]'`

adUser="$currentUser@snapsheet.me"

jamf recon -endUsername $adUser

exit 0