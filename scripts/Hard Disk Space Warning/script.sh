#!/bin/sh
description="We've noticed your hard disk is over 95% full. We recommend you manage your data in order to free up additional space in order to prevent performance issues.

If you'd like to get help seeing what is consuming your disk space, you can click the 'Help me' button below."

userChoice=$(/Library/Application\ Support/JAMF/bin/jamfHelper.app/Contents/MacOS/jamfHelper -windowType utility -title "Hard Drive Warning" -heading "Your disk is almost full" -description $description -button1 "Help me" -button2 "Close" -defaultButton 1 -cancelButton 2 -alignHeading center)

if [ "$userChoice" == "0" ]; then
	open /System/Library/CoreServices/Applications/Storage\ Management.app
else
	exit 0
fi