#!/usr/bin/env bash

status="Not Installed"

if [ -d /Library/Security/SecurityAgentPlugins/JamfConnectLogin.bundle/ ]; then
RESULT=$( /usr/bin/defaults read /Library/Security/SecurityAgentPlugins/JamfConnectLogin.bundle/Contents/Info.plist CFBundleShortVersionString)
fi

/bin/echo "<result>$status</result>"