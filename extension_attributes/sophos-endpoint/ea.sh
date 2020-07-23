#!/usr/bin/env bash
################################################################################
# A script to collect the version of Sophos Endpoint is currently installed.   #
# If Sophos is not installed "Not Installed" will return back                  #
################################################################################

RESULT="Not Installed"

if [ -d /Applications/Sophos\ Endpoint.app ]; then
RESULT=$( /usr/bin/defaults read /Library/Sophos\ Anti-Virus/product-info ProductVersion)
fi

/bin/echo "<result>$RESULT</result>"
