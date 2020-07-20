#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""git2jss: sync your git repository with your JSS

A fast asynchronous python library for syncing your scripts in git with your
JSS easily. This allows admins to keep their script in a version control system
for easy updating rather than googling and copy-pasting from resources that
they find online.

Example:
    To sync the most recent commits to your JSS:

        % python3 sync.py --url https://company.jamfcloud.com \
            --username git2jss-api-user

Usage:
    Required flags:
        --url                   url for the JSS (https://company.jamfcloud.com)
        --username              username in JSS with API privileges
    Optional flags:
        --password              for CI/CD (Will prompt for password if not set)
        --do_not_verify_ssl     skip ssl verification
        --overwrite             overwrite all scripts and extension attributes
        --limit                 limit max connections (default=25)
        --timeout               limit max connections (default=60)
        --retries               retry n times after timeout (default=3)
        --verbose               add additional logging output
        --update_all            upload all resources in ./extension_attributes
                                    and ./scripts
        --jenkins               to write a Jenkins file:jenkins.properties with
                                    $scripts and $eas and compare
                                    $GIT_PREVIOUS_COMMIT with $GIT_COMMIT

Attributes:
    ARGS (argparse.Namespace): contains all of the arguments passed to
        ``sync.py`` from the command line. See ``get_args`` documentation.
    SLACK_EMOJI (str): The Jenkins file will contain a list of changes scripts
        and eas in $scripts and $eas. Use this variable to add a Slack emoji
        in front of each item if you use a post-build action for a Slack custom
        message
    SUPPORTED_EXTENSIONS (tuple): Tuple of (str) objects defining supported
        file extensions for scripts and eas.
    CATEGORIES (list): Empty list that will be filled by connecting to the JSS
        and downloading the existing categories.
    FILE_PATH (pathlib.Path): Path to the folder containing sync.py at
        execution. This is defined by the ``__file__`` attribute's ``.parent``
    S_HEAD (dict): Dictionary containing the headers used by ``aiohttp`` when
        making requests to the JSS.
    S_AUTH (None): Default ``None``, but populated with ``aiohttp.BasicAuth``
        at runtime with the ``ARGS.username`` and password provided by either
        ``ARGS.password`` or ``getpass.getpass`` at execution.
    JPS_URL (None): Default ``None``, but populated with ARGS.url.
    TIME_OUT (None): Default ``None``, but populated with ARGS.timeout.
    RE_TRIES (int): Default ``3``, but populated with ARGS.retries.

Todo:
    * Make ``JamfObject`` a Factory to automate object creation.

"""
# pylint: disable=missing-docstring,invalid-name
import argparse
import asyncio
import getpass
import logging
import os
import pathlib
import subprocess
import sys
import urllib.parse as urlparse
import warnings
import xml.etree.ElementTree as ET
from xml.dom import minidom

import aiohttp
import async_timeout
import uvloop

# Logging configuration
logging.basicConfig(
    level=logging.DEBUG,
    format="%(levelname)7s: %(message)s",
    stream=sys.stderr,
)
LOG = logging.getLogger("")
LOG.setLevel(logging.INFO)

# Global Constants
SLACK_EMOJI = ":white_check_mark:"
SUPPORTED_EXTENSIONS = (".sh", ".py", ".pl", ".swift", ".rb")
CATEGORIES = []
FILE_PATH = pathlib.Path(__file__).parent
S_HEAD = {"Accept": "application/xml",
          "Content-Type": "application/xml"}
S_AUTH = None
JPS_URL = None
TIME_OUT = None
RE_TRIES = 3


class JamfObject(object):
    """Base Class for all Jamf Object types (scripts, eas, etc.)

    Most actual functionality should be abstracted in this class, with any
    object requiring specific functionality having it added to their class.

    Attributes:
        folder (str): Name of the folder containing the script and XML files
        xml_file (pathlib.Path): XML file defined by the subclass's
            ``filename`` class attribute
        new_url (str): url for creating a new object in the JSS defined by
            parsing a new url using ``urllib.parse.urljoin`` to join the
            ``JPS_URL`` global with the subclass's ``resource`` class atribute.
        name (str): If the XML file contains the ``<name>`` tag, then this name
            is used when GET or PUT are performed in the JSS. Otherwise,
            ``folder.name`` is used as a fallback.
        xml (xml.etree.ElementTree.Element): Element object containing the
            contents of the XML file if available, otherwise the ``get`` method
            will attempt to download the existing XML from the JSS. If neither
            are available, the template stored in ``templates/`` is used with
            the file defined by the subclass' ``filename`` class attribute.
        data (str): String containing the contents of the script file to be
            embedded in ``xml`` prior to the PUT stage. Populated by
            ``get_data`` when the ``get`` method is called. The script file
            is discovered by globbing ``folder`` and looking for files with a
            ``pathlib.Path.suffix`` defined in ``SUPPORTED_EXTENSIONS``.

    """
    def __init__(self, folder, *args, **kwargs):
        """Initialization of a JamfObject object

        Nothing much happens at initialization. No IO is used in order to not
        slow down the script, but because the ``get`` method requires an
        ``aiohttp`` session and ``asyncio`` semaphore so that any missing XML
        may be gathered from the JSS.

        Args:
            folder (str): Name of the folder containing the script and xml for
                each subclass object.

        """
        self.folder = FILE_PATH.joinpath(self.source, folder)
        self.xml_file = self.folder.joinpath(self.filename + ".xml")
        self.new_url = urlparse.urljoin(
            JPS_URL, f"/JSSResource/{self.resource}/id/0")
        self.name = None
        self.xml = None
        self.data = None

    def __str__(self):
        return f"{self.folder}"

    def resource_url(self):
        """Returns the URL for each extant object in the JSS

        Args:
            None

        Returns:
            None: if ``name`` is not defined
            str: returns a str parsed by ``urllib.parse.urljoin`` combining
                the ``JPS_URL`` global and the subclass' ``resource`` class
                attribute, and the discovered ``name`` attribute.

        """
        if not self.name:
            return None
        return urlparse.urljoin(
            JPS_URL, f"/JSSResource/{self.resource}/name/{self.name}")

    async def get(self, session, semaphore):
        """Gets the information needed to upload an object to the JSS either
        from the XML in the folder, the JSS, or from the template as needed.

        Args:
            session (aiohttp.ClientSession): an active session to eventually
                pass to the ``get_resource`` function if needed.
            semaphore (asyncio.BoundedSempahore): a Semaphore to prevent the
                script from establishing too many connections to the JSS.

        Returns:
            xml (xml.etree.ElementTree.Element): Though not strictly necessary
                for the execution of the script, the ``xml`` attribute is
                returned for testing purposes.

        """
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
        """PUTs the information gathered by the ``get`` method into the JSS.

        Args:
            session (aiohttp.ClientSession): an active session to eventually
                pass to the ``get_resource`` function if needed.
            semaphore (asyncio.BoundedSempahore): a Semaphore to prevent the
                script from establishing too many connections to the JSS.

        Returns:
            bool: True if the PUT succeeds, False if it does not.

        """
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
        """Called by the ``get`` method if the XML file is missing from
        ``folder``. Here is where the ``name`` is inferred from
        ``pathlib.Path.name``. This is not an ideal scenario, so warnings are
        issued. Then an attempt is made to GET from the JSS. If this fails,
        the XML template file defined in the subclass is used instead.

        Args:
            session (aiohttp.ClientSession): an active session to eventually
                pass to the ``get_resource`` function if needed.
            semaphore (asyncio.BoundedSempahore): a Semaphore to prevent the
                script from establishing too many connections to the JSS.

        Returns:
            _template (xml.etree.ElementTree.Element): returns either the
                GET results from the JSS or the template file contents.

        """
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
        """All of the common XML cleanup activities should be performed here
        to reduce the amount of duplicated code where possible. Any special
        actions should be taken in each subclass' ``cleanup_xml`` method.

        Args:
            None

        Returns:
            None

        """
        # If name is missing or blank, then set it to the folder name, but
        # issue a warning because this should not be considered good practice.
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
        """Globs the ``folder`` looking for files with extensions defined in
        the ``SUPPORTED_EXTENSIONS`` global. If more than one file is found,
        the first is used.

        Once a file is found, its contents are read and placed into ``data``
        and the ``xml`` is updated to include the script contents using the
        subclass' ``data_xpath`` class attribute.

        Args:
            None

        Returns:
            None: if a script file cannot be found, then return None
            _data_file (pathlib.Path): Path to data file, used for testing
                purposes.

        """
        # If name is missing or blank, then set it to the folder name, but
        # issue a warning because this should not be considered good practice.
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
    """Subclass of ``JamfObject`` that defines attributes and methods for
    Extension Attributes.

    Attributes:
        class_name (str): String used for pretty printing the name
        source (str): String used for building the pathlib.Path ``folder``
            attribute in JamfObject
        filename (str): String used for building multiple pathlib.Path objects
            to files such as the XML file and script file.
        resource (str): Used by JamfObject after "JSSResource" to define the
            ``new_url`` attribute and the ``resource_url`` method to build
            the URL for the object in the JSS.
        data_xpath (str): Used by JamfObject to define where to write the
            ``data`` attribute (script) string to the XML prior to PUT.
        template (pathlib.Path): Path to the template in case the XML file is
            missing or the object does not yet exist in the JSS.

    """
    class_name = "Extension Attribute"
    source = "extension_attributes"
    filename = "ea"
    resource = "computerextensionattributes"
    data_xpath = "input_type/script"
    template = FILE_PATH.joinpath("templates/ea.xml")

    def __init__(self, folder, *args, **kwargs):
        """Initialization of an ``ExtensionAttribute`` object

        Simply calls the superclass' (JamfObject) ``__init__`` method as most
        functionality is abstracted there.

        Args:
            folder (str): Name of the folder containing the script and xml for
                the ``ExtensionAttribute`` object.

        """
        super().__init__(folder, *args, **kwargs)

    def __repr__(self):
        return f"<ExtensionAttribute({self.name})>"

    async def cleanup_xml(self):
        """Called after ``xml`` is gathered in ``JamfObject`` in order to
        ensure the uploaded XML is clean of any superfluous tags.

        Args:
            None

        Returns:
            None

        """
        # Call JamfObject._cleanup_xml to reduce repeated code.
        await self._cleanup_xml()


class Script(JamfObject):
    """Subclass of ``JamfObject`` that defines attributes and methods for
    Scripts.

    Attributes:
        Attributes are identical in function to those in ``ExtensionAttribute``

    """
    class_name = "Script"
    source = "scripts"
    filename = "script"
    resource = "scripts"
    data_xpath = "script_contents"
    template = FILE_PATH.joinpath("templates/script.xml")

    def __init__(self, folder, *args, **kwargs):
        """Initialization of a ``Script`` object

        Simply calls the superclass' (JamfObject) ``__init__`` method as most
        functionality is abstracted there.

        Args:
            folder (str): Name of the folder containing the script and xml for
                the ``Script`` object.

        """
        super().__init__(folder, *args, **kwargs)

    def __repr__(self):
        return f"<Script({self.name})>"

    async def cleanup_xml(self):
        """Called after ``xml`` is gathered in ``JamfObject`` in order to
        ensure the uploaded XML is clean of any superfluous tags.

        Args:
            None

        Returns:
            None

        """
        # Call JamfObject._cleanup_xml to reduce repeated code.
        await self._cleanup_xml()
        # This tag is unique to Scripts so is only included here.
        if self.xml.find("script_contents_encoded") is not None:
            self.xml.remove(self.xml.find("script_contents_encoded"))


async def get_resource(url, session, semaphore, responses=(200,)):
    """GET using the ``asyncio.ClientSession`` and return the XML.

    Significantly reduces the amount of repeated code by making all GET calls
    come through one function, irrespective of need. Returns the results as
    an ``xml.etree.ElementTree.Element`` object for further processing.

    Args:
        url (str): Full url of the requested resource in the JSS
        session (aiohttp.ClientSession): an active session object
        semaphore (asyncio.BoundedSempahore): a Semaphore to prevent the
            script from establishing too many connections to the JSS.
        responses (tuple): Acceptable HTTP status codes from the session.

    Returns:
        None: If response.status contains an HTTP status code not listed in
            ``responses``, then None is returned.
        xml.etree.ElementTree.Element: Otherwise a Element object is returned
            for further processing.

    """
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
    LOG.debug("URL: %s GET Results: %s", url, get_results)
    return get_results


async def put_resource(xml_element, url, new_url, session, semaphore):
    """PUT using the ``asyncio.ClientSession`` and return success.

    Significantly reduces the amount of repeated code by making all PUT calls
    come through one function, irrespective of need. Returns the HTTP response
    status code for further processing.

    Args:
        xml_element (xml.etree.ElementTree.Element): XML object to PUT
            in the JSS.
        url (str): Full URL of the resource in the JSS
        new_url (str): URL for creating a new object if it does not already
            exist in the JSS.
        session (aiohttp.ClientSession): an active session object
        semaphore (asyncio.BoundedSempahore): a Semaphore to prevent the
            script from establishing too many connections to the JSS.

    Returns:
        response.status (int): Returns the response status (200, 409, etc.)

    """
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


async def parse_xml(_path):
    """Parses an XML file and returns the root object.

    Args:
        _path (pathlib.Path): Path to the XML file to be parsed.

    Returns:
        xml.etree.ElementTree.Element: root object of the XML file

    """
    # To remove the visual abstraction of ``getroot`` this is moved here.
    return ET.parse(_path).getroot()


def make_pretty_xml(element):
    """Parses an ``xml.etree.ElementTree.Element`` object and returns a string
    formatted for pretty-printing.

    Args:
        element (xml.etree.ElementTree.Element): XML object to convert.

    Returns:
        str: A string containing the XML

    """
    return minidom.parseString(ET.tostring(
        element, encoding="unicode", method="xml")
    ).toprettyxml(indent="    ")


async def get_existing_categories(session, semaphore):
    """GET the Categories from the JSS and return as a list.

    Args:
        session (aiohttp.ClientSession): an active session object
        semaphore (asyncio.BoundedSempahore): a Semaphore to prevent the
            script from establishing too many connections to the JSS.

    Returns:
        list: A ``list`` of ``str``s containing the names of the Categories
            in the JSS. If there are none, an empty list is returned.

    """
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

    If ``ARGS.jenkins`` is ``True``, then utilize the ``GIT_PREVIOUS_COMMIT``
    and ``GIT_COMMIT`` environment variables to discover the changes.

    Args:
        None

    Returns:
        tuple:
            ch_extattrs (list): ``list`` of ``str``s containing the names of
                the changed Extension Attributes.
            ch_scripts (list): ``list`` of ``str``s containing the names of
                the changed Scripts.

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
    """Returns a ``list`` of ``str``s used by ``write_jenkins_file`` to create
    the ``str`` to write to the Jenkins file.

    Nested function ``j_fmt``:
        Args:
            ch_item (str): Name of changed item

        Returns:
            str: ``ch_item`` added to Jenkins style ``str``

    Args:
        ch_type (str): The type of changed object (i.e. "eas", "scripts")
        ch_list (list): ``list`` of ``str``s containing the name of each
            changed object.

    Returns:
        list: items formatted by ``j_fmt`` for writing to the Jenkins File.

    """
    def j_fmt(ch_item):
        return f"{SLACK_EMOJI} {ch_item}\\n\\"
    return ([f"{ch_type}={j_fmt(ch_list[0])}"] +
            [j_fmt(ji) for ji in ch_list[1:]])


def write_jenkins_file():
    """Write CHANGED_EXT_ATTRS and CHANGED_SCRIPTS to Jenkins file.

    $eas will contain the changed extension attributes, and $scripts will
    contain the changed scripts

    If there are no changes, the variable will be set to "None"

    Args:
        None

    Returns:
        None

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
    """Globs a folder for subfolders.

    Args:
        _path (pathlib.Path): Folder to glob.

    Returns:
        list: Contains ``pathlib.Path`` objects for every folder.

    """
    return [f for f in FILE_PATH.joinpath(_path).glob("*") if f.is_dir()]


def get_args():
    """Parse command line arguments.

    Reads command line arguments and returns their values. If required
    arguments are missing, the script does not continue executing. Also
    provides usage information.

    Args:
        None

    Returns:
        argparse.Namespace: Object containing all of the command line arguments
            or their defaults as attributes.

    """
    parser = argparse.ArgumentParser(description="Sync repo with JamfPro")
    parser.add_argument(
        "--url", required=True, help=(
            "URL for the target JSS instance (i.e. "
            "'https://mycompany.jamfcloud.com')."))
    parser.add_argument(
        "--username", required=True, help=(
            "Username in JSS with API privileges."))
    parser.add_argument(
        "--password", help=(
            "Password for the 'username' account. If not provided, you will "
            "be prompted."))
    parser.add_argument(
        "--limit", type=int, default=25, help=(
            "Limit of the total number of connections to make to the JSS."))
    parser.add_argument(
        "--timeout", type=int, default=60, help=(
            "Number of seconds before a timeout is called and the request is "
            "attempted again."))
    parser.add_argument(
        "--retries", type=int, default=3, help=(
            "Number of times to retry a request after a timeout occurs."))
    parser.add_argument(
        "--verbose", action="store_true", help=(
            "Greatly increase the output of the logging."))
    parser.add_argument(
        "--do_not_verify_ssl", action="store_false", help=(
            "Do not verify the SSL Certificate of the target JSS."))
    parser.add_argument(
        "--update_all", action="store_true", help=(
            "Update all objects even if they are unchanged."))
    parser.add_argument(
        "--jenkins", action="store_true", help=(
            "Write a Jenkins file: jenkins.properties with updated scripts "
            "and eas, and compare the '$GIT_PREVIOUS_COMMIT' environment "
            "variable with '$GIT_COMMIT'"))
    return parser.parse_args()


async def main():
    """Main Program: Called with script is executed with ``python sync.py``

    This is where all of the ``JamfObject``s are defined. The
    ``aiohttp.ClientSession`` and ``asyncio.BoundedSemaphore`` are setup, the
    object information is gathered, and uploaded if necessary.

    Args:
        None

    Returns:
        int: Returns a 1 on error and a 0 when successful to be passed to
            ``sys.exit`` so that failed jobs are caught when executing in a
            CI/CD environment.

    """
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
        # PUT updated information into the JPS. Returns a list of bools.
        put_success = await asyncio.gather(
            *[asyncio.ensure_future(t.put(session, semaphore))
              for t in all_items])
    # Since put_success is a list of bools with True for a successful PUT and
    # False if not, if not all of them are True, then at least one was False
    # ergo throw an error.
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
