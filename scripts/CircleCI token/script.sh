#!/bin/bash

user=`defaults read /Library/Preferences/com.apple.loginwindow lastUserName`

if [[ ! -e /Users/$user/.snapsheet/ ]]; then
    mkdir /Users/$user/.snapsheet/
elif [[ ! -d /Users/$user/.snapsheet/ ]]; then
    echo "/Users/$user/.snapsheet/ already exists but is not a directory" 1>&2
    exit 1
fi

rm -rf /Users/$user/.snapsheet/.env

touch /Users/$user/.snapsheet/.env

{
  echo 'REMOTE_DEPLOY_CIRCLECI_TOKEN='$4
  echo '# THIS FILE WILL BE REGULARLY OVERWRITTEN BY DEVICE MANAGEMENT'
  echo '# ANY ADDITIONS TO THIS FILE ARE DONE SO AT YOUR OWN RISK'
} > /Users/$user/.snapsheet/.env

exit 0