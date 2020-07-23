#!/bin/sh
/usr/local/bin/jamf setComputerName -useSerialNumber
/usr/local/bin/jamf recon
exit 0