<?xml version="1.0" encoding="UTF-8"?><extensionAttribute>
<displayName>Boot Volume Type</displayName>
<description>Returns the volume format type for the current boot volume.</description>
<dataType>string</dataType>
<scriptContentsMac>#!/bin/sh&#13;
&#13;
echo "&lt;result&gt;$(diskutil info / | grep Personality | awk -F':' ' { print $NF } ' | sed -e 's/^[[:space:]]*//')&lt;/result&gt;"&#13;
&#13;
exit 0</scriptContentsMac>
<scriptContentsWindows/>
</extensionAttribute>