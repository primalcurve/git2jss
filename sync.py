#!/usr/bin/env python
# pylint: disable=missing-docstring,invalid-name
import aiohttp
import argparse
import asyncio
import async_timeout
import getpass
import logging
import os
import pathlib
import subprocess
import sys
import urllib.parse as urlparse
import uvloop
import warnings
import xml.etree.ElementTree as ET
from xml.dom import minidom

# Logging configuration
logging.basicConfig(
    level=logging.DEBUG,
    format="%(levelname)7s: %(message)s",
    stream=sys.stderr,
)
LOG = logging.getLogger("")
LOG.setLevel(logging.INFO)

# The Jenkins file will contain a list of changes scripts and eas
# in $scripts and $eas.
# Use this variable to add a Slack emoji in front of each item if
# you use a post-build action for a Slack custom message
SLACK_EMOJI = ":white_check_mark:"
SUPPORTED_EXTENSIONS = (".sh", ".py", ".pl", ".swift", ".rb")
CATEGORIES = []
S_HEAD = {"Accept": "application/xml",
          "Content-Type": "application/xml"}
FILE_PATH = pathlib.Path(__file__).parent
S_AUTH = None
JPS_URL = None
TIME_OUT = None
RE_TRIES = 3


class JamfObject(object):
    def __init__(self, folder, *args, **kwargs):
        self.folder = FILE_PATH.joinpath(self.source, folder)
        self.xml_file = self.folder.joinpath(self.filename + ".xml")
        self.new_url = urlparse.urljoin(
            JPS_URL, f"/JSSResource/{self.resource}/id/0")
        self.name = None
        self.xml = None
        self.data = None
        self.upload_success = False

    def __str__(self):
        return f"{self.folder}"

    def resource_url(self):
        if not self.name:
            return None
        return urlparse.urljoin(
            JPS_URL, f"/JSSResource/{self.resource}/name/{self.name}")

    async def get(self, session, semaphore):
        if not self.xml:
            if not self.xml_file.exists():
                self.xml = await self.get_xml(session, semaphore)
            else:
                LOG.debug("Reading in XML file: %s", self.xml_file)
                self.xml = await parse_xml(self.xml_file)
                # Make sure we have the actual name from the XML
                # rather than using the folder name.
                self.name = self.xml.find("name").text
            await self.cleanup_xml()
            LOG.debug("XML Contents: %s", make_pretty_xml(self.xml))
        if not self.data:
            if not await self.get_data():
                LOG.error("No script file found in %s", self.folder)
                return  # Need to skip if no script.
        return self.xml

    async def put(self, session, semaphore):
        put_response = None
        for attempt in range(1, RE_TRIES):
            try:
                put_response = await put_resource(
                    self.xml, self.resource_url(),
                    self.new_url, session, semaphore)
                break
            except asyncio.exceptions.TimeoutError:
                LOG.error("%s: Upload timed out. This is attempt %d of %d",
                          self.name, attempt, RE_TRIES)
        if put_response in (201, 200):
            LOG.info("Uploaded %s: %s", self.class_name, self.name)
            return True
        LOG.error("Uploading %s %s Failed!", self.class_name, self.name)
        return False

    async def get_xml(self, session, semaphore):
        LOG.warning("%s: Inferring name from folder.", self.folder.name)
        self.name = self.folder.name
        LOG.warning("%s: XML Missing. Attempting GET from JSS.", self.name)
        # Get XML object from the JPS
        _template = await get_resource(self.resource_url(), session, semaphore)
        if not _template:
            LOG.error("%s: GET Failed! Using template: %s",
                      self.name, self.template)
            _template = await parse_xml(self.template)
        return _template

    async def _cleanup_xml(self):
        # Make sure the name matches what's in the repo.
        _name = self.xml.find("name")
        if _name is None:
            LOG.warning("%s: Name is missing from XML. Setting to '%s'. "
                        "Update XML file: '%s' to stop seeing this message.",
                        self.folder.name, self.folder.name, str(self.xml_file))
            ET.SubElement(self.xml, "name").text = self.folder.name
        elif not _name.text:
            LOG.warning("%s: Name is blank in the XML. Setting to '%s'. "
                        "Update XML file: '%s' to stop seeing this message.",
                        self.folder.name, folder.name, str(self.xml_file))
            self.xml.find("name").text = self.folder.name
        # Check the category
        _category = self.xml.find("category")
        if _category is None:
            LOG.warning("%s: Category is missing from XML. Setting to None. "
                        "Update XML file: '%s' to stop seeing this message.",
                        self.name, str(self.xml_file))
            ET.SubElement(self.xml, "category").text = "None"
        elif _category.text != "None" and _category.text not in CATEGORIES:
            LOG.warning("%s: Category '%s' not in the JSS. Setting to None. "
                        "Update XML file: '%s' to stop seeing this message.",
                        self.name, _category.text, str(self.xml_file))
            _category.text = "None"
        if self.xml.find(self.data_xpath) is not None:
            self.xml.find(self.data_xpath).clear()
        if self.xml.find("id") is not None:
            self.xml.remove(self.xml.find("id"))
        if self.xml.find("filename") is not None:
            self.xml.remove(self.xml.find("filename"))

    async def get_data(self):
        try:
            # Get all the script files within the folder, we'll only use
            # script_file[0] in case there are multiple files
            self._data_file = [f for f in self.folder.glob("*")
                               if f.suffix in SUPPORTED_EXTENSIONS][0]
            # Read the file and assign the contents to self.data
            with open(self._data_file, "r") as f:
                self.data = f.read()
            # Write data to the appropriate element within the XML.
            self.xml.find(self.data_xpath).text = self.data
        except IndexError:
            return None
        return self._data_file


class ExtensionAttribute(JamfObject):
    class_name = "Extension Attribute"
    source = "extension_attributes"
    filename = "ea"
    resource = "computerextensionattributes"
    data_xpath = "input_type/script"
    template = FILE_PATH.joinpath("templates/ea.xml")

    def __init__(self, folder, *args, **kwargs):
        super().__init__(folder, *args, **kwargs)

    def __repr__(self):
        return f"<ExtensionAttribute({self.name})>"

    async def cleanup_xml(self):
        await self._cleanup_xml()


class Script(JamfObject):
    class_name = "Script"
    source = "scripts"
    filename = "script"
    resource = "scripts"
    data_xpath = "script_contents"
    template = FILE_PATH.joinpath("templates/script.xml")

    def __init__(self, folder, *args, **kwargs):
        super().__init__(folder, *args, **kwargs)

    def __repr__(self):
        return f"<Script({self.name})>"

    async def cleanup_xml(self):
        await self._cleanup_xml()
        if self.xml.find("script_contents_encoded") is not None:
            self.xml.remove(self.xml.find("script_contents_encoded"))


async def get_resource(url, session, semaphore, responses=(200,)):
    get_results = None
    async with semaphore:
        with async_timeout.timeout(TIME_OUT):
            async with session.get(url, auth=S_AUTH, headers=S_HEAD) as resp:
                _text = await resp.text()
                LOG.debug(
                    "Response from URL: %s Status: %s Text: %s",
                    url, resp.status, _text)
                if resp.status in responses:
                    get_results = ET.fromstring(_text)
    LOG.debug("GET Results: %s", get_results)
    return get_results


async def put_resource(xml_element, url, new_url, session, semaphore):
    async with semaphore:
        with async_timeout.timeout(TIME_OUT):
            async with session.get(url, auth=S_AUTH, headers=S_HEAD) as resp:
                LOG.debug("URL: %s Initial PUT status: %s", url, resp.status)
                if resp.status == 200:
                    resp = await session.put(
                        url,
                        auth=S_AUTH,
                        data=ET.tostring(xml_element),
                        headers=S_HEAD)
                else:
                    resp = await session.post(
                        new_url,
                        auth=S_AUTH,
                        data=ET.tostring(xml_element),
                        headers=S_HEAD)
    LOG.debug("URL: %s Final PUT status: %s", url, resp.status)
    return resp.status


async def parse_xml(path):
    return ET.parse(path).getroot()


def make_pretty_xml(element):
    return minidom.parseString(ET.tostring(
        element, encoding="unicode", method="xml")
    ).toprettyxml(indent="    ")


async def get_existing_categories(session, semaphore):
    categories = await get_resource(
        urlparse.urljoin(JPS_URL, "/JSSResource/categories"),
        session, semaphore,
        responses=(200, 201))
    if categories:
        return [c.find("name").text for c in [
                e for e in categories.findall("category")]]
    return []


def check_for_changes():
    """Looks for files that were changed between the current commit and
       the last commit so we don't upload everything on every run
         --jenkins will utilize $GIT_PREVIOUS_COMMIT and $GIT_COMMIT
           environmental variables
         --update_all can be invoked to upload all scripts and
           extension attributes
    """
    git_cmd = ["git", "--no-pager", "diff", "--name-only"]
    # This line will work with the environmental variables in Jenkins
    if ARGS.jenkins:
        ch_cmd = git_cmd + [ev for ev in [
            os.environ.get("GIT_PREVIOUS_COMMIT"),
            os.environ.get("GIT_COMMIT")]
            if ev]
    # Compare the last two commits to determine the list of files that
    # were changed
    else:
        l_cmd = ["git", "log", "-2", "--pretty=oneline",
                 "--pretty=format:%h"]
        git_commits = subprocess.check_output(l_cmd).splitlines()
        ch_cmd = git_cmd + [git_commits[1], git_commits[0]]
    git_changes = str(subprocess.check_output(ch_cmd)).splitlines()
    ch_extattrs, ch_scripts = [], []
    for ch in git_changes:
        ch_path = pathlib.Path(ch).parts
        try:
            is_extension_attribute = all((
                "extension_attributes" in ch_path,
                ch_path[1] not in ch_extattrs))
            is_script = all((
                "scripts" in ch_path,
                ch_path[1] not in ch_scripts))
        except IndexError:
            continue
        if is_extension_attribute:
            ch_extattrs.append(ch_path[1])
        elif is_script:
            ch_scripts.append(ch_path[1])
    return ch_extattrs, ch_scripts


def jenkins_format(ch_type, ch_list):
    def j_fmt(ch_item):
        return f"{SLACK_EMOJI} {ch_item}\\n\\"
    return ([f"{ch_type}={j_fmt(ch_list[0])}"] +
            [j_fmt(ji) for ji in ch_list[1:]])


def write_jenkins_file():
    """Write CHANGED_EXT_ATTRS and CHANGED_SCRIPTS to jenkins file.
        $eas will contains the changed extension attributes,
        $scripts will contains the changed scripts
        If there are no changes, the variable will be set to "None"
    """
    ea_contents = ["eas=None"]
    sc_contents = ["scripts=None"]
    if CHANGED_EXT_ATTRS:
        ea_contents = jenkins_format("eas", CHANGED_EXT_ATTRS)
    ea_contents[-1] = ea_contents[-1].rstrip("\\")
    if CHANGED_SCRIPTS:
        sc_contents = jenkins_format("scripts", CHANGED_SCRIPTS)
    with open("jenkins.properties", "w") as f:
        f.write("\n".join(ea_contents + sc_contents))


async def find_subdirs(_path):
    return [f for f in FILE_PATH.joinpath(_path).glob("*") if f.is_dir()]


def get_args():
    parser = argparse.ArgumentParser(description="Sync repo with JamfPro")
    parser.add_argument("--url", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password")
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--do_not_verify_ssl", action="store_false")
    parser.add_argument("--update_all", action="store_true")
    parser.add_argument("--jenkins", action="store_true")
    return parser.parse_args()


async def main():
    # pylint: disable=global-statement
    global CATEGORIES
    # Create the base objects for each type of upload.
    # Future: Make JamfObject a Factory to automate this.
    extension_attributes = sorted([
        ExtensionAttribute(ea.name)
        for ea in await find_subdirs("extension_attributes")
        if ea.name in CHANGED_EXT_ATTRS or ARGS.update_all],
        key=lambda ea: ea.folder)
    scripts = sorted([
        Script(sc.name)
        for sc in await find_subdirs("scripts")
        if sc.name in CHANGED_SCRIPTS or ARGS.update_all],
        key=lambda sc: sc.folder)
    all_items = extension_attributes + scripts
    # Start processing objects.
    semaphore = asyncio.BoundedSemaphore(ARGS.limit)
    tcp_connector = aiohttp.TCPConnector(ssl=ARGS.do_not_verify_ssl)
    async with aiohttp.ClientSession(connector=tcp_connector) as session:
        CATEGORIES = await get_existing_categories(session, semaphore)
        # GET item information (XML,etc).
        await asyncio.gather(
            *[asyncio.ensure_future(t.get(session, semaphore))
              for t in all_items])
        LOG.debug("Information Collected. Beginning upload process.")
        print("\n\n== Beginning Upload ==\n")
        # PUT updated information into the JPS.
        put_success = await asyncio.gather(
            *[asyncio.ensure_future(t.put(session, semaphore))
              for t in all_items])
    if not all(put_success):
        LOG.error("There was a problem uploading one or more items. "
                  "Please check the log output and act accordingly.")
        return 1
    return 0


if __name__ == "__main__":
    # Setup Globals
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    # Get command-line arguments
    ARGS = get_args()
    JPS_URL = ARGS.url
    TIME_OUT = ARGS.timeout
    RE_TRIES = ARGS.retries
    LOG.info("JPS Instance: %s", JPS_URL)
    # Future, incorporate this into the async part of the script.
    CHANGED_EXT_ATTRS, CHANGED_SCRIPTS = check_for_changes()
    if not CHANGED_EXT_ATTRS and not CHANGED_SCRIPTS and not ARGS.update_all:
        LOG.info("No Changes to transfer to JPS.")
        sys.exit(0)
    LOG.info("Changed Extension Attributes: %s", CHANGED_EXT_ATTRS)
    LOG.info("Changed Scripts: %s", CHANGED_SCRIPTS)
    if ARGS.jenkins:
        write_jenkins_file()
    # Ask for password if not supplied via command line args
    if not ARGS.password:
        ARGS.password = getpass.getpass()
    S_AUTH = aiohttp.BasicAuth(ARGS.username, ARGS.password)
    loop = asyncio.get_event_loop()
    if ARGS.verbose:
        LOG.setLevel(logging.DEBUG)
        loop.set_debug(True)
        loop.slow_callback_duration = 0.001
        warnings.simplefilter("always", ResourceWarning)
    sys.exit(loop.run_until_complete(main()))
