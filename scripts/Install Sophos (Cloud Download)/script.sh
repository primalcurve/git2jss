#!/bin/bash
mkdir /private/var/tmp/sophos
cd /private/var/tmp/sophos

curl -L -O "https://api-cloudstation-us-east-2.prod.hydra.sophos.com/api/download/2981ce708e1451e5d53be8ce2c5958b6/SophosInstall.zip"
unzip SophosInstall.zip
chmod a+x /private/var/tmp/sophos/Sophos\ Installer.app/Contents/MacOS/Sophos\ Installer
chmod a+x /private/var/tmp/sophos/Sophos\ Installer.app/Contents/MacOS/tools/com.sophos.bootstrap.helper
sudo /private/var/tmp/sophos/Sophos\ Installer.app/Contents/MacOS/Sophos\ Installer --install;
/bin/rm -rf /private/var/tmp/sophos;
exit 0      ## Success
exit 1      ## Failure