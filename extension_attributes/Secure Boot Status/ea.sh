#!/bin/bash

# Test Secure Boot status EA for Jamf.

test=$( nvram 94b73556-2197-4702-82a8-3e1337dafbfb:AppleSecureBootPolicy | awk '{ print $2 }' )

case "$test" in
	%02)
		echo "<result>Full</result>"
	;;
	
	%01)
		echo "<result>Medium</result>"
	;;
	
	%00)
		echo "<result>Disabled</result>"
	;;
	
	*)
		echo "<result>Secure Boot Not Present</result>"
	;;
esac