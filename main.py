import os
import requests
import argparse
import sys
import logging
from datetime import datetime
import xml.etree.ElementTree as eTree
from lxml import etree
import configparser
import time
import json
from xmljson import badgerfish as bf
from freshservice import Freshservice
from device42 import Device42
from integration import FreshserviceIntegration


logger = logging.getLogger('log')
logger.setLevel(logging.INFO)
ch = logging.StreamHandler(sys.stdout)
ch.setFormatter(logging.Formatter('%(asctime)-15s\t%(levelname)s\t %(message)s'))
logger.addHandler(ch)
CUR_DIR = os.path.dirname(os.path.abspath(__file__))

requests.packages.urllib3.disable_warnings()

parser = argparse.ArgumentParser(description="freshservice")
parser.add_argument('-fsurl', '--freshserviceurl', action='store_true', help='Freshservice url')
parser.add_argument('-fstoken', '--freshservicetoken', action='store_true', help='Freshservice API token')
parser.add_argument('-fsuser', '--freshserviceusername', action='store_true', help='default approver', default=None)
parser.add_argument('-v', '--validate', action='store_true', help='validate mapping', default=False)
parser.add_argument('-del', '--delete', action='store_true', help='delete all assets in FS', default=False)
parser.add_argument('-delr', '--deleterelationships', action='store_true', help='delete all relationships in FS', default=False)

parser.add_argument('-d42url', '--d42url', action='store_true', help='Device42 URL')
parser.add_argument('-d42user', '--d42username', action='store_true', help='Device42 username')
parser.add_argument('-d42pass', '--d42password', action='store_true', help='Device42 password')

parser.add_argument('-d', '--debug', action='store_true', help='Enable debug output')
parser.add_argument('-q', '--quiet', action='store_true', help='Quiet mode - outputs only errors')
parser.add_argument('-c', '--config', help='Config file', default='mapping.xml')
parser.add_argument('-l', '--logfolder', help='log folder path', default='.')

def parse_config(url):
    config = eTree.parse(url)
    meta = config.getroot()
    config_json = bf.data(meta)

    return config_json

def validate_xml(xml_file, xsd_file):
    # Parse the XML and XSD files
    with open(xsd_file, 'r') as xsd_f:
        xsd_tree = etree.parse(xsd_f)
        xsd_schema = etree.XMLSchema(xsd_tree)

    with open(xml_file, 'r') as xml_f:
        xml_tree = etree.parse(xml_f)

    # Validate the XML file against the XSD schema
    if xsd_schema.validate(xml_tree):
        print("XML is valid against the provided XSD schema.")
    else:
        print("XML is not valid. Validation errors:")
        for error in xsd_schema.error_log:
            print(error)

def get_agent_from_freshservice(freshservice, email):
    default_approver = None
    try:
        agents = freshservice.get_all_agents()
        for agent in agents:
            if agent['email'].lower() == email.lower():
                return agent['id']
    except Exception as e:
        logger.exception(str(e))

    return default_approver

def run():
    debug = False
    quiet = False
    last_update = "1900-01-01 00:00:00+00:00"
    device42_url = ""
    device42_user = ""
    device42_pass = ""
    freshservice_url = ""
    freshservice_api_key = ""
    freshervice_default_approver_email = ""
    freshservice_default_approver = None

    device42_object = None
    freshservice_object = None
    freshserviceIntegration_object = None

    # read args from command line
    args = parser.parse_args()

    if args.validate == True:
        print("Validating mapping.xml")
        validate_xml("mapping.xml", "mapping.xsd")
        return
    if not all([args.freshserviceurl, args.freshservicetoken, args.freshserviceusername, 
            args.d42url, args.d42username, args.d42password]):
        print("Not all command line args were supplied, fallback to config.ini")

        # read config file if exists
        if os.path.exists(os.path.join(os.getcwd(), "config.ini")):
            config = configparser.ConfigParser()
            config.read("config.ini")
            device42_url = config['Device42']['URL']
            device42_user = config['Device42']['Username']
            device42_pass = config['Device42']['Password']
            freshservice_url = config['Freshservice']['URL']
            freshservice_api_key = config['Freshservice']['APIKey']
            if config['Freshservice']['User'] != "":
                freshervice_default_approver_email = config['Freshservice']['User']
            settings = config['Settings']
            if config["Settings"]["Debug"]:
                debug = settings.getboolean("Debug")
            if config["Settings"]["Quiet"]:
                quiet = settings.getboolean("Quiet")
            if config["Meta"]["LastUpdate"]:
                try:
                    raw_timestamp = settings["LastUpdate"]
                    last_update = datetime.fromisoformat(raw_timestamp)
                except ValueError:
                    print(f"Invalid timestamp format in config: {raw_timestamp}")
        else:
            # read environmental variables if exists
            print("No config.ini file found, fallback to environment variables")
            for key in ["D42_URL", "D42_USER", "D42_PASS", "FS_URL", "FS_API_KEY"]:
                if key not in os.environ:
                    print(f"{key} missing from environmental variables, exiting")
                    return -1
            device42_url = os.environ.get("D42_URL")
            device42_user = os.environ.get("D42_USER")
            device42_pass = os.environ.get("D42_PASS")
            freshservice_url = os.environ.get("FS_URL")
            freshservice_api_key = os.environ.get("FS_API_KEY")
            if "FS_USER" in os.environ:
                    freshervice_default_approver_email = os.environ.get("FS_USER")
            if "D42_FS_DEBUG_LEVEL" in os.environ:
                debug = bool(os.environ.get("D42_FS_DEBUG"))
            if "D42_FS_QUIET" in os.environ:
                quiet = bool(os.environ.get("D42_FS_QUIET"))
            if "LAST_UPDATE" in os.environ:
                try:
                    raw_timestamp = os.environ.get("LAST_UPDATE")
                    last_update = datetime.fromisoformat(raw_timestamp)
                except ValueError:
                    print(f"Invalid timestamp format in config: {raw_timestamp}")
    else:
        config = parse_config(args.config)
        logger.debug("configuration info: %s" % (json.dumps(config)))
        settings = config["meta"]["settings"]

        device42_url = settings['device42']['@url']
        device42_user = settings['device42']['@user']
        device42_pass = settings['device42']['@pass']
        freshservice_url = settings['freshservice']['@url']
        freshservice_api_key = settings['freshservice']['@api_key']
        if '@default_approver_email' in settings['freshservice']:
            freshervice_default_approver_email = settings['freshservice']['@default_approver_email']
        if '@debug' in settings['meta']:
            debug = bool(settings['meta']['@debug'])
        if '@quiet' in settings['meta']:
            quiet = bool(settings['meta']['@quiet'])
        if '@last_update' in settings['meta']:
            try:
                raw_timestamp = settings['meta']['@last_update']  
                last_update = datetime.fromisoformat(raw_timestamp)
            except ValueError:
                print(f"Invalid timestamp format in config: {raw_timestamp}")

    if debug:
        logger.setLevel(logging.DEBUG)
    if quiet:
        logger.setLevel(logging.ERROR)

    # setup logging file
    try:
        log_file = f"d42_fs_sync_{int(time.time())}.log"
        logging.basicConfig(filename=log_file)
    except Exception as e:
        print("Error in config log: %s" % str(e))
        return -1
    
    # read the config files
    config = parse_config("mapping.xml")

    if freshervice_default_approver_email:
        freshservice_default_approver = get_agent_from_freshservice(freshervice_default_approver_email)
    
    freshservice_object = Freshservice(freshservice_url, freshservice_api_key, freshservice_default_approver, logger)
    if args.delete == True:
        print("Deleteing all assets in Freshservice")
        freshservice_object.delete_all_assets()
        return
    if args.deleterelationships == True:
        print("Deleteing all relationships in Freshservice")
        freshservice_object.delete_all_relationships()
        return
    device42_object = Device42(device42_url, device42_user, device42_pass, logger)
    freshserviceIntegration_object = FreshserviceIntegration(device42_object, freshservice_object, last_update, logger)
    freshserviceIntegration_object.process_tasks(config)

    print("Completed! View log at %s" % log_file)
    return 0

if __name__ == "__main__":
    run()