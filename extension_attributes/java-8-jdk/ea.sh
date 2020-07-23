#!/usr/bin/env bash
##########################################################################################
# Collects information to determine which version of the Java JDK is installed by        #
# looping through all the installed JDKs for the major version selected. And then        #
# comparing the build number to determine the highest value. Builds the result as        #
# 1.X.Y, ignoring the build number, where X is major version and Y is the minor version. #								  #	
########################################################################################## 
SEARCH_FOR_VERSION="8"
HIGHEST_BUILD="-1"
RESULT="Not Installed"

installed_jdks=$(/bin/ls /Library/Java/JavaVirtualMachines/)


for i in ${installed_jdks}; do
	version=$( /usr/bin/defaults read "/Library/Java/JavaVirtualMachines/${i}/Contents/Info.plist" CFBundleVersion )

	major_version=`/bin/echo "$version" | /usr/bin/awk -F'.' '{print $2}'`

	if [ "$major_version" -eq "$SEARCH_FOR_VERSION" ] ; then
		# Split on 1.X.0_XX to get build number
		build_number=`/bin/echo "$version" | /usr/bin/awk -F'0_' '{print $2}'`
		if [ "$build_number" -gt "$HIGHEST_BUILD" ] ; then
			HIGHEST_BUILD="$build_number"
			RESULT="1.$major_version.$build_number"
		fi	
	fi		
done

/bin/echo "<result>$RESULT</result>"