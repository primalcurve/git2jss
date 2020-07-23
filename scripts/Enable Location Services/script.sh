#!/bin/bash

# write enabled key
sudo -u _locationd /usr/bin/defaults -currentHost write com.apple.locationd LocationServicesEnabled -int 1

# enable icon in menu bar
/usr/bin/defaults write /Library/Preferences/com.apple.locationmenu "ShowSystemServices" -bool YES

exit 0