import time
from freshservice import FreshserviceDuplicateValueError
from Constants import *

def fs_log(mode, msg, object_name=None, object_type=None):
    if mode == logging.ERROR:
        logger.info(msg + f" object_name: {object_name} object_type: {object_type}")

    if mode == logging.INFO:
        logger.info(msg)
    elif mode == logging.DEBUG:
        logger.debug(msg)
    elif mode == logging.ERROR:
        logger.exception(msg)
    else:
        logger.info(msg)

def escape_value(name):
    if name:
        name = name.replace('<', '[')
        name = name.replace('>', ']')
        # Replace Unicode no-break spaces with normal spaces.
        name = name.replace(u'\xa0', ' ')
        name = name.strip()
    return name

def check_version(current_version, min_required_version, max_required_version):
    # intention is to have tags on mapping file 'tasks' called d42_min_version and d42_max_version

    # if current version is none, then getting d42 version must have failed, assume legacy version
    if current_version is None:
        logger.info("Device42 version is None. Defaulting to legacy version")
        current_version = "1.0.0"

    # assume all greater versions work
    if not min_required_version:
        min_required_version = "0.0.0"

    # assume all prior versions work
    if not max_required_version:
        max_required_version = "9999.9999.9999"

    # major.minor.revision.revision_2
    try:
        # parse the version components
        min_req_version = min_required_version.strip().split('.')
        min_req_major = int(min_req_version[0])
        min_req_minor = int(min_req_version[1])
        min_req_rev = int(min_req_version[2])

        max_req_version = max_required_version.strip().split('.')
        max_req_major = int(max_req_version[0])
        max_req_minor = int(max_req_version[1])
        max_req_rev = int(max_req_version[2])

        cur_version = current_version.strip().split('.')
        cur_major = int(cur_version[0])
        cur_minor = int(cur_version[1])
        cur_rev = int(cur_version[2])

        # check if the min is greater than max, it should not be if configured correctly
        if min_req_major > max_req_major:
            logger.error("check mapping.xml for min_req version that is greater than the max required version")
            return False
        elif min_req_major == max_req_major:
            if min_req_minor > max_req_minor:
                logger.error("check mapping.xml for min_req version that is greater than the max required version")
                return False
            elif min_req_minor == max_req_minor:
                if min_req_rev > max_req_rev:
                    logger.error("check mapping.xml for min_req version that is greater than the max required version")
                    return False
                # if all version components are equal, then the min and max must match, just continue

        # check if the minimum version requirements are met
        # current version is greater than or equal to the minimum version

        has_min_requirements = False
        has_max_requirements = False

        # check if the minimum version requirements are met
        # current version is greater than or equal to the minimum version
        if cur_major > min_req_major:
            has_min_requirements = True
        elif cur_major == min_req_major:
            if cur_minor > min_req_minor:
                has_min_requirements = True
            elif cur_minor == min_req_minor:
                if cur_rev >= min_req_rev:
                    has_min_requirements = True

        # check if the maximum version requirements are met
        # current version is less than or equal to the maximum version
        if cur_major < max_req_major:
            has_max_requirements = True
        elif cur_major == max_req_major:
            if cur_minor < max_req_minor:
                has_max_requirements = True
            elif cur_minor == max_req_minor:
                if cur_rev <= max_req_rev:
                    has_max_requirements = True

        if has_min_requirements and has_max_requirements:
            return True

        return False
    except Exception as e:
        logger.error("error checking if version of D42 is compatible. error: " + str(e))
        return False

class FreshserviceIntegration(object):
    def __init__(self, device42, freshservice, last_update, logger):
        self.last_update = last_update
        self.freshservice = freshservice
        self.device42 = device42
        self.logger = logger
        self.total_processed = 0
        self.serial_number_device_counts = None
        self.fs_cache = dict()
        self.d42_cache = dict()
    
    def increase_processed(self, end_task=True, amount=1):
        if end_task:
            self.total_processed += amount
        

    def find_object_by_name(self, assets, name):
        for asset in assets:
            if asset["name"].lower() == escape_value(name).lower():
                return asset

        return None

    def find_object_in_map(self, objects_map, name):
        if name:
            return objects_map.get(escape_value(name).lower())

        return None

    def allow_asset_match(self, asset_device42_id, d42_item_device42_id):
        if asset_device42_id and d42_item_device42_id:
            asset_prefix = asset_device42_id.split('-')[0]
            d42_item_prefix = d42_item_device42_id.split('-')[0]

            return asset_prefix.lower() == d42_item_prefix.lower()

        # We can't compare the prefixes because we don't have one or both of them, so allow the match.
        return True

    def find_asset_in_maps(self, assets_maps, asset_match_values):
        freshservice = self.freshservice

        key = freshservice.create_assets_map_key_from_value(asset_match_values.device42_id)
        if key:
            asset = assets_maps['device42_id'].get(key)
            if asset:
                return asset

        key = freshservice.create_assets_map_key_from_value(asset_match_values.item_id)
        if key:
            asset = assets_maps['item_id'].get(key)
            if asset:
                if self.allow_asset_match(asset.get('device42_id'), asset_match_values.device42_id):
                    return asset

            # We have an item ID, but could not find a match.  Do not try to match on any other
            # criteria since we want to create a new asset for this.
            return None


        key = freshservice.create_assets_map_key_from_value(asset_match_values.serial_number)
        if key:
            if self.serial_number_device_counts is None:
                self.serial_number_device_counts = self.get_d42_cache_items(D42_CACHE_SERIAL_NUMBER_DEVICE_COUNTS)

            serial_number_lower = asset_match_values.serial_number.lower()
            do_check = True

            # If multiple devices in D42 have this serial number, we can't try to match on an asset serial number
            # because all the devices from D42 with this serial number would all match to the same asset which is
            # not what we want to happen.
            if self.serial_number_device_counts and serial_number_lower in self.serial_number_device_counts and \
               self.serial_number_device_counts[serial_number_lower] > 1:
                do_check = False

            if do_check:
                asset = assets_maps['serial_number'].get(key)
                if asset:
                    if self.allow_asset_match(asset.get('device42_id'), asset_match_values.device42_id):
                        return asset

        key = freshservice.create_assets_map_key_from_value(asset_match_values.uuid)
        if key:
            asset = assets_maps['uuid'].get(key)
            if asset:
                if self.allow_asset_match(asset.get('device42_id'), asset_match_values.device42_id):
                    return asset

        key = freshservice.create_assets_map_key_from_value(asset_match_values.imei_number)
        if key:
            asset = assets_maps['imei_number'].get(key)
            if asset:
                if self.allow_asset_match(asset.get('device42_id'), asset_match_values.device42_id):
                    return asset

        if asset_match_values.mac_address:
            # We will call the Freshservice API to find an asset with the MAC address.
            assets = freshservice.search_assets('mac_addresses', asset_match_values.mac_address)
            # Only consider it a match if we get back exactly 1 asset from Freshservice that has this
            # MAC address.
            if len(assets) == 1:
                asset = assets[0]
                if self.allow_asset_match(asset.get('device42_id'), asset_match_values.device42_id):
                    return asset

        key = freshservice.create_assets_map_key_from_value(escape_value(asset_match_values.name))
        if key:
            asset = assets_maps['name'].get(key)
            if asset:
                if self.allow_asset_match(asset.get('device42_id'), asset_match_values.device42_id):
                    return asset

        return None

    def update_asset_in_maps(self, old_asset, new_asset, assets_maps):
        if not old_asset and new_asset:
            # We added a new asset.
            self.freshservice.add_asset_to_maps(new_asset, assets_maps)
        elif old_asset and new_asset:
            # We updated an existing asset.
            self.freshservice.delete_asset_from_maps(old_asset, assets_maps)
            self.freshservice.add_asset_to_maps(new_asset, assets_maps)

    def find_object_id_in_map(self, objects_map, name):
        obj = self.find_object_in_map(objects_map, name)
        if obj:
            return obj["id"]

        return None

    def find_object_by_id_in_map(self, objects_map, id):
        for key in objects_map:
            if objects_map[key]['id'] == id:
                return objects_map[key]

        return None

    def get_asset_types_map(self):
        return self.get_cache_items(CACHE_ASSET_TYPES, "api/v2/asset_types", "asset_types")

    def get_assets_maps(self):
        return self.get_cache_items(CACHE_ASSETS, 'api/v2/assets?include=type_fields', 'assets')

    def get_trash_assets_maps(self):
        return self.get_cache_items(CACHE_TRASH_ASSETS, 'api/v2/assets?trashed=true&include=type_fields', 'assets')

    def get_softwares_map(self):
        return self.get_cache_items(CACHE_SOFTWARES, 'api/v2/applications', 'applications')

    def get_contracts_map(self):
        return self.get_cache_items(CACHE_CONTRACTS, 'api/v2/contracts', 'contracts')

    def get_products_map(self):
        return self.get_cache_items(CACHE_PRODUCTS, 'api/v2/products', 'products')

    def get_components_maps(self):
        return self.get_cache_items(CACHE_COMPONENTS, None, None)

    def get_log_object_type(self, asset_type_id):
        if asset_type_id is None:
            return None
        asset_types_map = self.get_asset_types_map()
        asset_type = self.find_object_by_id_in_map(asset_types_map, asset_type_id)
        if asset_type is None:
            return None
        object_type = asset_type['name']
        if 'parent_asset_type_id' in asset_type and \
            asset_type['parent_asset_type_id'] is not None:
            parent_asset_type_id = asset_type['parent_asset_type_id']
            parent_asset_type = self.find_object_by_id_in_map(asset_types_map, parent_asset_type_id)
            if parent_asset_type is not None:
                object_type = parent_asset_type['name'] + '/' + object_type

        return object_type

    def get_asset_type_field(self, asset_type_fields, map_info):
        # This field does not get returned by the API for
        # getting asset type fields, so create a field to account for it.
        if map_info['@target'] == 'source_asset_ids':
            return {'asset_type_id': None, 'name': map_info['@target']}

        for section in asset_type_fields:
            if section["field_header"] == map_info["@target-header"]:
                for field in section["fields"]:
                    name = map_info["@target"]
                    if "@target-field" in map_info:
                        name = map_info["@target-field"]
                    if field["asset_type_id"] is not None:
                        name += "_" + str(field["asset_type_id"])
                    if field["name"] == name:
                        return field

        return None

    def get_map_value_from_device42(self, source, map_info, b_add=False, asset_type_id=None):
        freshservice = self.freshservice

        d42_value = source[map_info["@resource"]]
        if d42_value is None and "@resource-secondary" in map_info:
            d42_value = source[map_info["@resource-secondary"]]
        if "@is-array" in map_info and map_info["@is-array"]:
            d42_vals = d42_value
            d42_value = None
            for d42_val in d42_vals:
                if map_info["@sub-key"] in d42_val:
                    d42_value = d42_val[map_info["@sub-key"]]
                    break
        else:
            if "value-mapping" in map_info:
                cache_key = "%s-%s" % (map_info["@resource"], map_info["@target"])
                if cache_key not in self.fs_cache:
                    if isinstance(map_info["value-mapping"]["item"], list):
                        items = map_info["value-mapping"]["item"]
                    else:
                        items = [map_info["value-mapping"]["item"]]

                    self.fs_cache[cache_key] = {item["@key"]: item["@value"] for item in items}
                d42_val = self.fs_cache[cache_key].get(d42_value)
                if d42_val is None and "@default" in map_info["value-mapping"]:
                    default_value = map_info["value-mapping"]["@default"]

                    # If we send a software status of "", we get the following error from the API:
                    # Error 400: {"description":"Validation failed","errors":[{"field":"status",
                    # "message":"It should be one of these values: 'blacklisted,ignored,managed'","code":"invalid_value"}]}
                    # So if we have a value in D42 that does not map to Freshservice (we don't currently have a value that
                    # does not map), instead of clearing the value in Freshservice by sending a "", it will try to set that
                    # value and this is not one of the available options.  However, if we set the software status to None,
                    # the value in Freshservice will get cleared.
                    if default_value == "null":
                        d42_val = None
                    else:
                        d42_val = default_value

                d42_value = d42_val
            else:
                pass

        if "@target-foreign-key" in map_info:
            target_foreign = map_info["@target-foreign"]
            if target_foreign not in self.fs_cache:
                self.fs_cache[target_foreign] = freshservice.get_objects_map("api/channel/device42/%s" % target_foreign, target_foreign, map_info["@target-foreign-key"])

            value = self.find_object_id_in_map(self.fs_cache[target_foreign], d42_value)
            if b_add and value is None and "@not-null" in map_info and map_info[
                "@not-null"]:  # and "@required" in map_info and map_info["@required"]
                if d42_value is not None:
                    if "@max-length" in map_info and len(d42_value) > map_info["@max-length"]:
                        name = d42_value[0:map_info["@max-length"] - 3] + "..."
                    else:
                        name = d42_value
                    if target_foreign in ["vendors", "groups", "agents"]:
                        new_item = freshservice.insert_and_get_by_name(target_foreign, name, None, map_info["@target-foreign-key"])
                    else:
                        new_item = freshservice.insert_and_get_by_name(target_foreign, name, asset_type_id, map_info["@target-foreign-key"])
                    self.fs_cache[target_foreign][new_item[map_info["@target-foreign-key"]].lower()] = new_item
                    d42_value = new_item["id"]
                else:
                    d42_value = None
            else:
                # If value is None, that means we could not find a match for the D42 value in Freshservice.
                # We will return the same D42 value since for product we will call this function again with
                # the required asset_type_id which is needed to create the value in Freshservice.
                if value is not None or "@not-null" not in map_info:
                    d42_value = value

        if "@escape" in map_info and map_info["@escape"]:
            d42_value = escape_value(d42_value)

        return d42_value

    def get_asset_type_field_from_map(self, asset_type_fields_map, asset_type_id, asset_type_fields, map_info):
        if asset_type_id not in asset_type_fields_map:
            asset_type_fields_map[asset_type_id] = dict()

        target_header = map_info["@target-header"] if "@target-header" in map_info else ""
        key = map_info["@resource"] + "-" + target_header
        if key in asset_type_fields_map[asset_type_id]:
            asset_type_field = asset_type_fields_map[asset_type_id][key]
        else:
            asset_type_field = self.get_asset_type_field(asset_type_fields, map_info)
            asset_type_fields_map[asset_type_id][key] = asset_type_field

        return asset_type_field

    def submit_relationship_create_job(self, relationships_to_create, submitted_items):
        freshservice = self.freshservice

        fs_log(logging.INFO, "adding relationship create job")
        # Creating relationships using the v2 API is now an asynchronous operation and is
        # performed using background jobs.  We will get back the job ID which can then be
        # used to query the status of the job.
        job_id = freshservice.insert_relationships({"relationships": relationships_to_create})
        fs_log(logging.INFO, "added new relationship create job %s" % job_id)

        return {
            "job_id": job_id,
            "relationships_to_create_count": len(relationships_to_create),
            "items": submitted_items
        }

    def submit_software_install_create_job(self, software_id, software_install_to_create, submitted_items):
        freshservice = self.freshservice

        fs_log(logging.INFO, "adding installation create job")
        # Creating software install using "/api/channel/device42/applications/%d/upsert-installations".
        job_id = freshservice.upsert_installation(software_id, {"installations": software_install_to_create})
        fs_log(logging.INFO, "added new installation create job %s" % job_id)

        return {
            "job_id": job_id,
            "installation_to_create_count": len(software_install_to_create),
            "items": submitted_items
        }

    def build_asset_type_migration_key_from_ids(self, old_asset_type_id, new_asset_type_id):
        key = '%d-%d' % (old_asset_type_id, new_asset_type_id)

        return key

    def build_asset_type_migration_key_from_names(self, asset_types_map, old_asset_type, new_asset_type):
        return self.build_asset_type_migration_key_from_ids(self.find_object_id_in_map(asset_types_map, old_asset_type),
                                                            self.find_object_id_in_map(asset_types_map, new_asset_type))

    def get_cloud_to_hardware_asset_types(self, asset_types_map):
        # Use a set where the key is a concatenation of old asset type and new asset type.
        # We use a set instead of a dictionary because an old asset type could map to different new
        # asset types (e.g. Virtual Machine).
        cloud_to_hardware_asset_type_ids = set()
        cloud_to_hardware_asset_type_ids.add(self.build_asset_type_migration_key_from_names(asset_types_map,
                                                                                            ASSET_TYPE_VIRTUAL_MACHINE_DEPRECATED,
                                                                                            ASSET_TYPE_SERVER))
        cloud_to_hardware_asset_type_ids.add(self.build_asset_type_migration_key_from_names(asset_types_map,
                                                                                            ASSET_TYPE_AWS_VM_DEPRECATED,
                                                                                            ASSET_TYPE_AWS_VM))
        cloud_to_hardware_asset_type_ids.add(self.build_asset_type_migration_key_from_names(asset_types_map,
                                                                                            ASSET_TYPE_AZURE_VM_DEPRECATED,
                                                                                            ASSET_TYPE_AZURE_VM))
        cloud_to_hardware_asset_type_ids.add(self.build_asset_type_migration_key_from_names(asset_types_map,
                                                                                            ASSET_TYPE_GCP_VM_DEPRECATED,
                                                                                            ASSET_TYPE_GCP_VM))
        cloud_to_hardware_asset_type_ids.add(self.build_asset_type_migration_key_from_names(asset_types_map,
                                                                                            ASSET_TYPE_VIRTUAL_MACHINE_DEPRECATED,
                                                                                            ASSET_TYPE_GCP_VM))
        cloud_to_hardware_asset_type_ids.add(self.build_asset_type_migration_key_from_names(asset_types_map,
                                                                                            ASSET_TYPE_VMWARE_VCENTER_VM_DEPRECATED,
                                                                                            ASSET_TYPE_VMWARE_VCENTER_VM))
        cloud_to_hardware_asset_type_ids.add(self.build_asset_type_migration_key_from_names(asset_types_map,
                                                                                            ASSET_TYPE_HOST_DEPRECATED,
                                                                                            ASSET_TYPE_HOST))
        cloud_to_hardware_asset_type_ids.add(self.build_asset_type_migration_key_from_names(asset_types_map,
                                                                                            ASSET_TYPE_VMWARE_VCENTER_HOST_DEPRECATED,
                                                                                            ASSET_TYPE_VMWARE_VCENTER_HOST))
        cloud_to_hardware_asset_type_ids.add(self.build_asset_type_migration_key_from_names(asset_types_map,
                                                                                            ASSET_TYPE_LOAD_BALANCER,
                                                                                            ASSET_TYPE_COMPUTER))
        cloud_to_hardware_asset_type_ids.add(self.build_asset_type_migration_key_from_names(asset_types_map,
                                                                                            ASSET_TYPE_VIRTUAL_MACHINE_DEPRECATED,
                                                                                            ASSET_TYPE_AZURE_LB))
        cloud_to_hardware_asset_type_ids.add(self.build_asset_type_migration_key_from_names(asset_types_map,
                                                                                            ASSET_TYPE_SERVER,
                                                                                            ASSET_TYPE_MOBILE))
        cloud_to_hardware_asset_type_ids.add(self.build_asset_type_migration_key_from_names(asset_types_map,
                                                                                            ASSET_TYPE_VIRTUAL_MACHINE_DEPRECATED,
                                                                                            ASSET_TYPE_VMWARE_VCENTER_IMAGE))

        cloud_to_hardware_asset_type_ids.add(self.build_asset_type_migration_key_from_names(asset_types_map,
                                                                                            ASSET_TYPE_AWS_K8S_NODE_DEPRECATED,
                                                                                            ASSET_TYPE_AWS_K8S_NODE))
        cloud_to_hardware_asset_type_ids.add(self.build_asset_type_migration_key_from_names(asset_types_map,
                                                                                            ASSET_TYPE_SERVER,
                                                                                            ASSET_TYPE_AWS_K8S_NODE))
        return cloud_to_hardware_asset_type_ids

    def update_objects_from_server(self, sources, _target, matching, mapping):
        freshservice = self.freshservice

        # This method gets called for both devices and business apps.  Since it gets called first for devices,
        # that is when the assets from Freshservice will get added to the cache.  When this method gets called
        #  for business apps, we can get the objects out of the cache.
        existing_assets_maps = self.get_assets_maps()
        asset_types_map = self.get_asset_types_map()

        if "asset_type_fields" not in self.fs_cache:
            self.fs_cache["asset_type_fields"] = {}

        asset_type_fields_map = dict()

        cloud_to_hardware_asset_type_ids = self.get_cloud_to_hardware_asset_types(asset_types_map)

        added = 0
        updated = 0
        error = 0
        total_log = None
        total_status = STATUS_SUCCESS

        for source in sources:
            error_skip = False
            while True:
                try:
                    asset_type_id = None
                    asset_match_values = AssetMatchValues(matching["source-1"], source)
                    existing_object = self.find_asset_in_maps(existing_assets_maps, asset_match_values)
                    source_asset_type_id = self.find_object_id_in_map(asset_types_map, source["asset_type"])

                    if existing_object is None:
                        asset_type_id = source_asset_type_id
                    else:
                        asset_type_id = existing_object["asset_type_id"]

                    if asset_type_id in self.fs_cache["asset_type_fields"]:
                        asset_type_fields = self.fs_cache["asset_type_fields"][asset_type_id]
                    else:
                        asset_type_fields = freshservice.get_asset_type_fields(asset_type_id)
                        self.fs_cache["asset_type_fields"][asset_type_id] = asset_type_fields

                    data = dict()
                    data['asset_type_id'] = asset_type_id
                    data["type_fields"] = dict()

                    # if there is only one field in the mapping, it will be dict.
                    if isinstance(mapping["field"], dict):
                        mapping["field"] = [mapping["field"]]

                    # validation
                    for map_info in mapping["field"]:
                        # If we are updating an existing asset, check if we should skip updating this field.
                        if existing_object and '@skip-update' in map_info and map_info['@skip-update']:
                            continue

                        if error_skip and "@error-skip" in map_info and map_info["@error-skip"]:
                            continue

                        asset_type_field = self.get_asset_type_field_from_map(asset_type_fields_map, asset_type_id, asset_type_fields, map_info)
                        if asset_type_field is None:
                            continue

                        value = self.get_map_value_from_device42(source, map_info)

                        if "@skip-if-null" in map_info and map_info["@skip-if-null"] and value is None:
                            continue

                        if "@target-type" in map_info:
                            target_type = map_info["@target-type"]
                        else:
                            target_type = None

                        if asset_type_field["asset_type_id"] is not None:
                            data["type_fields"][asset_type_field["name"]] = value
                        elif target_type != "dict":
                            data[map_info["@target"]] = value

                        is_valid = True
                        if value is not None and "@min-length" in map_info and len(value) < map_info["@min-length"]:
                            is_valid = False
                            if value == "" and "@set-space" in map_info and map_info["@set-space"]:
                                is_valid = True
                                value = " " * map_info["@min-length"]
                        # value might have been translated to an associated ID in Freshservice by get_map_value_from_device42
                        #  which is why we need to check that value is a string using isinstance.
                        if value is not None and "@max-length" in map_info and isinstance(value, str) and len(value) > map_info["@max-length"]:
                            value = value[0:map_info["@max-length"]-3] + "..."
                        if (value is None or value == "") and "@not-null" in map_info and map_info["@not-null"]:
                            if map_info["@target"] == "asset_tag":
                                is_valid = False
                            else:
                                # There is an issue with the Freshservice API where sending a null value for
                                # a field will result in the API returning an error like "Has 0 characters,
                                # it should have minimum of 1 characters and can have maximum of 255 characters".
                                # This prevents us from being able to clear these field values in Freshservice (even though
                                # the Freshservice UI allows you to clear these fields).  To get around this, we will send
                                # a single space for string values and a 0 for integer and float values when the value
                                # coming from D42 is null.
                                if target_type:
                                    if target_type == "integer" or target_type == "float":
                                        value = 0
                                    elif target_type in ["date", "datetime"]:
                                        value = None
                                        is_valid = False
                                    elif target_type == "boolean":
                                        value = False
                                    else:
                                        value = " "
                                else:
                                    value = " "

                        if "@target-foreign-key" in map_info:
                            value = self.get_map_value_from_device42(source, map_info, True, data["asset_type_id"])
                            is_valid = value is not None
                        elif "@target-type" in map_info and value is not None:
                            if target_type == "string":
                                try:
                                    value = str(value)
                                except Exception as e:
                                    logger.exception(f"Error converting value to string {e}")
                                    is_valid = False
                            
                            elif target_type == "integer":
                                try:
                                    value = int(value)
                                except Exception as e:
                                    logger.exception(f"Error converting value to integer {e}")
                                    is_valid = False
                            
                            elif target_type == "float":
                                try:
                                    value = float(value)
                                except Exception as e:
                                    logger.exception(f"Error converting value to float {e}")
                                    is_valid = False
                            
                            elif target_type == "boolean":
                                try:
                                    value = bool(value)
                                except Exception as e:
                                    logger.exception(f"Error converting vale to boolean {e}")
                                    is_valid = False 

                            elif target_type == "dropdown":
                                try:
                                    # Only try to find an option if we have a value and that value is not spaces.
                                    if value and value.strip():
                                        option = None
                                        for choice in asset_type_field["choices"]:
                                            d42_value = value.lower()
                                            choice_value = choice[0].lower()
                                            if d42_value == choice_value:
                                                option = choice[0]
                                                break
                                        if option is None:
                                            is_valid = False
                                        else:
                                            value = option
                                except Exception as e:
                                    logger.exception(f"Error selecting option for dropdown {e}")
                                    is_valid = False
                        if not is_valid:
                            fs_log(logging.DEBUG, "argument '%s' is invalid." % map_info["@target"])
                            if asset_type_field["asset_type_id"] is not None:
                                data["type_fields"].pop(asset_type_field["name"], None)
                            else:
                                data.pop(map_info["@target"], None)
                        if is_valid:
                            if target_type == "dict" and "@target-field" in map_info:
                                try:
                                    field_value = value
                                    if map_info["@target"] in data:
                                        value = data[map_info["@target"]]
                                    else:
                                        value = None
                                    if value is None:
                                        value = {}
                                    value[map_info["@target-field"]] = field_value
                                except Exception as e:
                                    logger.exception(f"Error converting vale to boolean {e}")
                                    is_valid = False

                            if asset_type_field["asset_type_id"] is not None:
                                data["type_fields"][asset_type_field["name"]] = value
                            else:
                                data[map_info["@target"]] = value

                    if existing_object is None:
                        fs_log(logging.INFO, "adding asset %s" % source["name"])
                        new_asset = freshservice.insert_asset(data)
                        fs_log(logging.INFO, "added new asset %d" % new_asset["id"])
                        # We added a new asset to Freshservice.  Add it to the maps of assets that we know exist
                        # in Freshservice.
                        self.update_asset_in_maps(existing_object, new_asset, existing_assets_maps)
                        added += 1
                    else:
                        fs_log(logging.INFO, "updating asset %s" % source["name"])
                        # This is a workaround for an issue with the Freshservice API where if a business service
                        # asset has the Managed By field filled in and we don't send an agent_id to update this
                        # field (we don't map any D42 data to this field and shouldn't need to because
                        # the API will only update the fields that we send), it will result in a validation
                        # error with the message:
                        # Assigned agent isn't a member of the group.
                        # So, if the business service asset has an agent_id already populated, we will send that
                        # same value over and that will avoid this error.
                        if source["asset_type"] == ASSET_TYPE_BUSINESS_SERVICE and "agent_id" in existing_object and existing_object["agent_id"]:
                            data["agent_id"] = existing_object["agent_id"]
                        updated_asset = freshservice.update_asset(data, existing_object["display_id"])
                        fs_log(logging.INFO, "updated existing asset %d" % updated_asset["id"])
                        self.update_asset_in_maps(existing_object, updated_asset, existing_assets_maps)
                        updated += 1

                    break
                except FreshserviceDuplicateValueError:
                    if not error_skip:
                        error_skip = True
                        continue
                    break
                except Exception as e:
                    object_name = existing_object["name"] if existing_object else source["name"]
                    log = "Error (%s) updating asset %s" % (str(e), object_name)
                    fs_log(logging.ERROR, log, object_name=object_name, object_type=self.get_log_object_type(asset_type_id))
                    total_status = STATUS_FAILED
                    if total_log is None:
                        total_log = log
                    else:
                        total_log += "\n" + log
                    error += 1
                    break

            self.increase_processed()

        self.increase_processed(False)
        return total_status, total_log, added, updated, error

    def delete_objects_from_server(self, sources, _target, matching, mapping):
        freshservice = self.freshservice

        existing_assets_maps = self.get_assets_maps()
        trash_assets_maps = self.get_trash_assets_maps()

        deleted = 0
        error = 0
        total_log = None
        total_status = STATUS_SUCCESS
        existing_object_maps = existing_assets_maps["device42_id"]
        trash_object_maps = trash_assets_maps["device42_id"]
        
        source_maps = {}
        for source in sources:
            asset_match_values = AssetMatchValues(matching["source-1"], source)
            if asset_match_values.device42_id is not None:
                if 'device42_id' not in source_maps:
                    source_maps['device42_id'] =  {}
                source_maps['device42_id'][freshservice.create_assets_map_key_from_value(asset_match_values.device42_id)] = True

        for existing_object_key in existing_object_maps:
            existing_object = existing_object_maps[existing_object_key]

            if 'device42_id' not in source_maps or existing_object_key in source_maps['device42_id']:
                continue
            
            if existing_object_key in trash_object_maps:
                continue

            try:
                fs_log(logging.INFO, "deleting asset %s" % existing_object["name"])
                freshservice.delete_asset(existing_object["display_id"])
                deleted += 1
                fs_log(logging.INFO, "deleted asset %s" % existing_object["name"])
            except Exception as e:
                log = "Error (%s) deleting asset %s" % (str(e), existing_object["name"])
                fs_log(logging.ERROR, log,
                        object_name=existing_object["name"],
                        object_type=self.get_log_object_type(existing_object["asset_type_id"]))
                total_status = STATUS_FAILED
                if total_log is None:
                    total_log = log
                else:
                    total_log += "\n" + log
                error += 1

            self.increase_processed()

        self.increase_processed(False)

        return total_status, total_log, deleted, error

    def update_softwares_from_server(self, sources, _target, mapping):
        freshservice = self.freshservice

        existing_softwares_map = self.get_softwares_map()

        updated = 0
        added = 0
        error = 0
        total_log = None
        total_status = STATUS_SUCCESS

        for source in sources:
            try:

                existing_object = self.find_object_in_map(existing_softwares_map, source["name"])

                if existing_object is not None:
                    fs_log(logging.INFO, "software %s already exists" % source["name"])
                    updated += 1
                    self.increase_processed()
                    continue

                data = dict()
                for map_info in mapping["field"]:
                    value = self.get_map_value_from_device42(source, map_info)

                    if "@skip-if-null" in map_info and map_info["@skip-if-null"] and value is None:
                        continue

                    # value might have been translated to an associated ID in Freshservice by get_map_value_from_device42
                    #  which is why we need to check that value is a string using isinstance.
                    if value is not None and "@max-length" in map_info and isinstance(value, str) and len(value) > map_info["@max-length"]:
                        value = value[0:map_info["@max-length"] - 3] + "..."

                    data[map_info["@target"]] = value

                fs_log(logging.INFO, "adding software %s" % source["name"])
                new_software = freshservice.insert_software(data)
                fs_log(logging.INFO, "added new software %d" % new_software["id"])
                # We added a new object to Freshservice.  Add it to the map of objects that we know exist
                # in Freshservice.
                existing_softwares_map[new_software["name"].lower()] = new_software
                added += 1
            except Exception as e:
                object_name = existing_object["name"] if existing_object else source["name"]
                log = "Error (%s) updating software %s" % (str(e), object_name)
                fs_log(logging.ERROR, log,
                        object_name=object_name,
                        object_type='Software')
                total_status = STATUS_FAILED
                if total_log is None:
                    total_log = log
                else:
                    total_log += "\n" + log
                error += 1

            self.increase_processed()

        self.increase_processed(False)

        return total_status, total_log, added, updated, error

    def delete_softwares_from_server(self, sources, _target, mapping):
        freshservice = self.freshservice
        existing_softwares_map = self.get_softwares_map()
        updated = 0
        error = 0
        total_log = None
        total_status = STATUS_SUCCESS
        existing_objects = existing_softwares_map.values()

        for existing_object in existing_objects:

            exist = False
            for source in sources:
                if source[mapping["@key"]] == existing_object[mapping["@key"]]:
                    exist = True
                    break

            if not exist:
                try:
                    fs_log(logging.INFO, "deleting software %s" % existing_object["name"])
                    freshservice.delete_software(existing_object["id"])
                    updated += 1
                    fs_log(logging.INFO, "deleted software %s" % existing_object["name"])
                except Exception as e:
                    log = "Error (%s) deleting software %s" % (str(e), existing_object["name"])
                    fs_log(logging.ERROR, log,
                           object_name=existing_object["name"],
                           object_type='Software')
                    total_status = STATUS_FAILED
                    if total_log is None:
                        total_log = log
                    else:
                        total_log += "\n" + log
                    error += 1

            self.increase_processed()

        self.increase_processed(False)

        return total_status, total_log, updated, error

    def update_products_from_server(self, sources, _target, mapping):
        freshservice = self.freshservice
        

        existing_products_map = self.get_products_map()
        asset_types_map = self.get_asset_types_map()
        asset_type_id = self.find_object_id_in_map(asset_types_map, _target["@asset-type"])

        updated = 0
        added = 0
        error = 0
        total_log = None
        total_status = STATUS_SUCCESS

        for source in sources:
            try:

                existing_object = self.find_object_in_map(existing_products_map, source["name"])
                data = dict()
                for map_info in mapping["field"]:
                    # If we are updating an existing product, check if we should skip updating this field.
                    if existing_object and '@skip-update' in map_info and map_info['@skip-update']:
                        continue

                    value = self.get_map_value_from_device42(source, map_info)

                    if "@skip-if-null" in map_info and map_info["@skip-if-null"] and value is None:
                        continue

                    # value might have been translated to an associated ID in Freshservice by get_map_value_from_device42
                    #  which is why we need to check that value is a string using isinstance.
                    if value is not None and "@max-length" in map_info and isinstance(value, str) and len(value) > map_info["@max-length"]:
                        value = value[0:map_info["@max-length"] - 3] + "..."

                    data[map_info["@target"]] = value

                if existing_object is None:
                    fs_log(logging.INFO, "adding product %s" % source["name"])
                    data['asset_type_id'] = asset_type_id
                    new_product = freshservice.insert_product(data)
                    fs_log(logging.INFO, "added new product %d" % new_product["id"])
                    # We added a new object to Freshservice.  Add it to the map of objects that we know exist
                    # in Freshservice.
                    existing_products_map[new_product["name"].lower()] = new_product
                    added += 1
                else:
                    fs_log(logging.INFO, "updating product %s" % source["name"])
                    updated_product_id = freshservice.update_product(data, existing_object["id"])
                    fs_log(logging.INFO, "updated existing product %d" % updated_product_id)
                    updated += 1
            except Exception as e:
                object_name = existing_object["name"] if existing_object else source["name"]
                log = "Error (%s) updating product %s" % (str(e), object_name)
                fs_log(logging.ERROR, log,
                        object_name=object_name,
                        object_type="Product")
                total_status = STATUS_FAILED
                if total_log is None:
                    total_log = log
                else:
                    total_log += "\n" + log
                error += 1

            self.increase_processed()

        self.increase_processed(False)

        return total_status, total_log, added, updated, error

    def create_software_installations(self, sources, _target, matching, mapping):
        freshservice = self.freshservice
        

        existing_assets_maps = self.get_assets_maps()
        existing_softwares_map = self.get_softwares_map()

        updated = 0
        added = 0
        error = 0
        total_log = None
        total_status = STATUS_SUCCESS
        # Key will be the software ID and the value will be a set of asset IDs that the software is
        # installed on.
        software_to_assets_map = dict()
        object_type = "Installation"
        object_items_map = dict()
        software_install_map = dict()

        for source in sources:
            try:
                object_name = None

                fs_log(logging.INFO, "Processing %s - %s." % (source[mapping["@device-name"]], source[mapping["@software-name"]]))
                asset_match_values = AssetMatchValues(matching["source-1"], source)
                asset = self.find_asset_in_maps(existing_assets_maps, asset_match_values)
                software = self.find_object_in_map(existing_softwares_map, source[mapping["@software-name"]])
                object_name = "Installation %s-%s" % (
                    asset["name"] if asset else source[mapping["@device-name"]],
                    software["name"] if software else source[mapping["@software-name"]]
                    )

                if asset is None:
                    error += 1
                    self.increase_processed()
                    log = "There is no asset(%s) in FS." % source[mapping["@device-name"]]
                    fs_log(logging.ERROR, log, object_name=object_name, object_type=object_type)
                    total_status = STATUS_FAILED
                    if total_log is None:
                        total_log = log
                    else:
                        total_log += "\n" + log
                    continue

                if software is None:
                    error += 1
                    self.increase_processed()
                    log = "There is no software(%s) in FS." % source[mapping["@software-name"]]
                    fs_log(logging.ERROR, log, object_name=object_name, object_type=object_type)
                    total_status = STATUS_FAILED
                    if total_log is None:
                        total_log = log
                    else:
                        total_log += "\n" + log
                    continue

                asset_type_id = asset["asset_type_id"]
                if not self.is_computer_asset(asset_type_id):
                    log = "Asset type(%d) is not computer in FS(%s)." % (asset_type_id, object_name)
                    updated += 1
                    self.increase_processed()
                    fs_log(logging.INFO, log)
                    continue

                if software["id"] not in software_to_assets_map:
                    installations = freshservice.get_installations_by_id(software["id"])
                    software_to_assets_map[software["id"]] = {i["installation_machine_id"] for i in installations}

                exist = asset["display_id"] in software_to_assets_map[software["id"]]
                if exist:
                    updated += 1
                    self.increase_processed()
                    fs_log(logging.INFO, "There is already installation in FS.")
                    continue

                if software["id"] not in software_install_map:
                    software_install_map[software["id"]] = []

                if software["id"] not in object_items_map:
                    object_items_map[software["id"]] = []

                software_install_map[software["id"]].append({
                    'installation_machine_id': asset["display_id"],
                    'version': source[mapping["@version"]],
                    'installation_date': source[mapping["@install-date"]]
                })

                object_items_map[software["id"]].append({
                    'object_name': object_name,
                    'object_type': object_type
                })

            except Exception as e:
                log = "Error (%s) creating installation %s" % (str(e), source[mapping["@device-name"]])
                fs_log(logging.ERROR, log, object_name=object_name, object_type=object_type)
                total_status = STATUS_FAILED
                if total_log is None:
                    total_log = log
                else:
                    total_log += "\n" + log
                error += 1

            self.increase_processed()

        submitted_jobs = list()
        object_items = list()
        for software_id in software_install_map:
            software_installs = software_install_map[software_id]
            object_items = object_items_map[software_id]
            count = len(software_installs)
            i = 0
            while i < count:
                submitted_jobs.append(self.submit_software_install_create_job(
                    software_id,
                    software_installs[i: i+SOFTWARE_INSTALL_BATCH_SIZE],
                    object_items[i: i+SOFTWARE_INSTALL_BATCH_SIZE]
                    ))
                i += SOFTWARE_INSTALL_BATCH_SIZE


        if submitted_jobs:
            jobs_to_check = list(submitted_jobs)
            next_jobs_to_check = list()

            start_time = time.time()
            while time.time() - start_time < MAX_JOB_WAIT_SECONDS:
                time.sleep(JOB_WAIT_SECONDS)

                for job_to_check in jobs_to_check:
                    try:
                        job = freshservice.get_job(job_to_check["job_id"])
                        status = job["status"]

                        if status == "success":
                            # All installations were created.
                            added += job_to_check["installation_to_create_count"]
                        elif status in ["failed", "partial"]:
                            # No installations were created (failed status) or some installations
                            # were created and some were not (partial status).
                            # We will need to look at the individual installations in order to
                            # determine how many were created and how many were not.
                            i = 0
                            for installation in job["installations"]:
                                if installation["success"]:
                                    added += 1
                                else:
                                    item = job_to_check["items"][i]
                                    log = "Job %s failed to create installation: %s" % (job_to_check["job_id"], item["object_name"])
                                    fs_log(logging.ERROR, log, object_name=item["object_name"], object_type=item["object_type"])
                                    total_status = STATUS_FAILED
                                    if total_log is None:
                                        total_log = log
                                    else:
                                        total_log += "\n" + log
                                    error += 1
                                i += 1
                        elif status in ["queued", "in progress"]:
                            # The job has not completed yet.
                            next_jobs_to_check.append(job_to_check)
                        else:
                            raise Exception("Received unknown job status of %s." % status)
                    except Exception as e:
                        log = "Error (%s) checking job %s" % (str(e), job_to_check["job_id"])
                        if total_log is None:
                            total_log = log
                        else:
                            total_log += "\n" + log
                        for item in job_to_check["items"]:
                            fs_log(logging.ERROR, log, object_name=item["object_name"], object_type=item["object_type"])
                        total_status = STATUS_FAILED
                        error += job_to_check["installation_to_create_count"]

                # Clear the list.
                del jobs_to_check[:]

                if next_jobs_to_check:
                    # We still have jobs we need to check.
                    jobs_to_check.extend(next_jobs_to_check)

                    # Clear the list so that we can add the next set of jobs that are
                    # still waiting to complete.
                    del next_jobs_to_check[:]
                else:
                    # There are no more jobs that we need to check, so we can stop
                    # checking.
                    break

            if jobs_to_check:
                # We finished waiting for the jobs to complete.  If there are still jobs
                # that did not complete yet, assume that they will failure.
                total_status = STATUS_FAILED
                for job_to_check in jobs_to_check:
                    error += job_to_check["installation_to_create_count"]

                submitted_jobs_count = len(submitted_jobs)
                jobs_not_completed_count = len(jobs_to_check)

                fs_log(logging.INFO, "%d of %d installation create jobs did not complete." % (jobs_not_completed_count, submitted_jobs_count))

                # If we find that a large portion of submitted jobs are not completed
                # by the time we stop checking them, we may want to increase the time
                # we are waiting for jobs to complete.
                fs_log(logging.error, "Some installation create jobs did not complete.")

        self.increase_processed(False)

        return total_status, total_log, added, updated, error

    def create_asset_relationships(self, sources, _target, matching, mapping):
        freshservice = self.freshservice
        

        existing_assets_maps = self.get_assets_maps()

        object_type = "(%s - %s)" % (
                mapping["@downstream-relationship"], mapping["@upstream-relationship"])

        fs_log(logging.INFO, "Getting relationship type in FS.")
        relationship_type = freshservice.get_relationship_type_by_content(mapping["@downstream-relationship"],
                                                                          mapping["@upstream-relationship"])
        fs_log(logging.INFO, "finished getting relationship type in FS.")
        if relationship_type is None:
            log = "There is no relationship type in FS. (%s - %s)" % (
                mapping["@downstream-relationship"], mapping["@upstream-relationship"])
            fs_log(logging.ERROR, log, object_name="Relationship", object_type=object_type)
            return STATUS_FAILED, log, 0, 0, len(sources)

        updated = 0
        added = 0
        error = 0
        total_log = None
        total_status = STATUS_SUCCESS

        # The key will be the display_id of the primary asset and the value will be a set of
        # the secondary asset display_id's that the primary asset is related to.
        relationships_map = dict()
        relationships_to_create = list()
        source_count = len(sources)
        submitted_jobs = list()
        submitted_items = list()

        for idx, source in enumerate(sources):
            try:
                object_name = None

                fs_log(logging.INFO, "Processing %s - %s." % (source[mapping["@key"]], source[mapping["@target-key"]]))
                primary_asset_match_values = AssetMatchValues(matching["source-1"], source)
                primary_asset = self.find_asset_in_maps(existing_assets_maps, primary_asset_match_values)
                secondary_asset_match_values = AssetMatchValues(matching["source-2"], source)
                secondary_asset = self.find_asset_in_maps(existing_assets_maps, secondary_asset_match_values)
                object_name = "Relationship %s-%s" % (
                    primary_asset["name"] if primary_asset else source[mapping["@key"]],
                    secondary_asset["name"] if secondary_asset else source[mapping["@target-key"]]
                    )

                if primary_asset is None:
                    error += 1
                    self.increase_processed()
                    log = "There is no dependent asset(%s) in FS." % source[mapping["@key"]]
                    fs_log(logging.ERROR, log, object_name=object_name, object_type=object_type)
                    total_status = STATUS_FAILED
                    if total_log is None:
                        total_log = log
                    else:
                        total_log += "\n" + log
                    continue

                if secondary_asset is None:
                    error += 1
                    self.increase_processed()
                    log = "There is no dependency asset(%s) in FS." % source[mapping["@target-key"]]
                    fs_log(logging.ERROR, log, object_name=object_name, object_type=object_type)
                    total_status = STATUS_FAILED
                    if total_log is None:
                        total_log = log
                    else:
                        total_log += "\n" + log
                    continue

                primary_asset_display_id = primary_asset["display_id"]

                if primary_asset_display_id == secondary_asset["display_id"]:
                    updated += 1
                    self.increase_processed()
                    fs_log(logging.INFO, "Primary and Secondary assets are same(%s)." % primary_asset["name"])
                    continue

                if primary_asset_display_id not in relationships_map:
                    relationships_map[primary_asset_display_id] = set()
                    relationships = freshservice.get_relationships_by_id(primary_asset_display_id)

                    for relationship in relationships:
                        if relationship["relationship_type_id"] == relationship_type["id"]:
                            relationships_map[primary_asset_display_id].add(relationship["secondary_id"])

                exist = secondary_asset["display_id"] in relationships_map[primary_asset_display_id]
                if exist:
                    updated += 1
                    self.increase_processed()
                    fs_log(logging.INFO, "There is already relationship in FS.")
                    continue

                relationships_to_create.append({
                    "relationship_type_id": relationship_type["id"],
                    "primary_id": primary_asset_display_id,
                    "primary_type": "asset",
                    "secondary_id": secondary_asset["display_id"],
                    "secondary_type": "asset"
                })

                submitted_items.append({
                    'object_name': object_name,
                    'object_type': object_type
                })

                relationships_to_create_count = len(relationships_to_create)
                relationships_map[primary_asset_display_id].add(secondary_asset["display_id"])

                # Create a new job if we reached our batch size or we are on the last item (which
                # means this is the last batch we will be submitting).
                if relationships_to_create_count >= RELATIONSHIP_BATCH_SIZE or idx == source_count - 1:
                    submitted_jobs.append(self.submit_relationship_create_job(relationships_to_create, submitted_items))

                    # Clear the list for the next batch of relationships we are going to send.
                    del relationships_to_create[:]
                    del submitted_items[:]
            except Exception as e:
                log = "Error (%s) creating relationship %s" % (str(e), source[mapping["@key"]])
                fs_log(logging.ERROR, log, object_name=object_name, object_type=object_type)
                total_status = STATUS_FAILED
                if total_log is None:
                    total_log = log
                else:
                    total_log += "\n" + log
                error += 1

            self.increase_processed()

        # We may not have submitted the last batch of relationships to create if the last item in
        # sources did not result in a relationship needing to be created (e.g. one of the assets
        # in the relationship did not exist in Freshservice, the relationship already existed in
        # Freshservice, etc.).  So if we have any relationships that we need to create that have
        # not been submitted, submit them now.
        if relationships_to_create:
            submitted_jobs.append(self.submit_relationship_create_job(relationships_to_create, submitted_items))

            del relationships_to_create[:]
            del submitted_items[:]

        if submitted_jobs:
            jobs_to_check = list(submitted_jobs)
            next_jobs_to_check = list()

            start_time = time.time()
            while time.time() - start_time < MAX_JOB_WAIT_SECONDS:
                time.sleep(JOB_WAIT_SECONDS)

                for job_to_check in jobs_to_check:
                    try:
                        job = freshservice.get_job(job_to_check["job_id"])
                        status = job["status"]

                        if status == "success":
                            # All relationships were created.
                            added += job_to_check["relationships_to_create_count"]
                        elif status in ["failed", "partial"]:
                            # No relationships were created (failed status) or some relationships
                            # were created and some were not (partial status).
                            # We will need to look at the individual relationships in order to
                            # determine how many were created and how many were not.
                            i = 0
                            for relationship in job["relationships"]:
                                if relationship["success"]:
                                    added += 1
                                else:
                                    log = "Job %s failed to create relationship: %s" % (job_to_check["job_id"], relationship)
                                    item = job_to_check["items"][i]
                                    fs_log(logging.ERROR, log, object_name=item["object_name"], object_type=item["object_type"])
                                    total_status = STATUS_FAILED
                                    if total_log is None:
                                        total_log = log
                                    else:
                                        total_log += "\n" + log
                                    error += 1
                                i += 1
                        elif status in ["queued", "in progress"]:
                            # The job has not completed yet.
                            next_jobs_to_check.append(job_to_check)
                        else:
                            raise Exception("Received unknown job status of %s." % status)
                    except Exception as e:
                        log = "Error (%s) checking job %s" % (str(e), job_to_check["job_id"])
                        if total_log is None:
                            total_log = log
                        else:
                            total_log += "\n" + log
                        for item in job_to_check["items"]:
                            fs_log(logging.ERROR, log, object_name=item["object_name"], object_type=item["object_type"])
                        total_status = STATUS_FAILED
                        error += job_to_check["relationships_to_create_count"]

                # Clear the list.
                del jobs_to_check[:]

                if next_jobs_to_check:
                    # We still have jobs we need to check.
                    jobs_to_check.extend(next_jobs_to_check)

                    # Clear the list so that we can add the next set of jobs that are
                    # still waiting to complete.
                    del next_jobs_to_check[:]
                else:
                    # There are no more jobs that we need to check, so we can stop
                    # checking.
                    break

            if jobs_to_check:
                # We finished waiting for the jobs to complete.  If there are still jobs
                # that did not complete yet, assume that they will failure.
                total_status = STATUS_FAILED
                for job_to_check in jobs_to_check:
                    error += job_to_check["relationships_to_create_count"]

                submitted_jobs_count = len(submitted_jobs)
                jobs_not_completed_count = len(jobs_to_check)

                fs_log(logging.INFO, "%d of %d relationship create jobs did not complete." % (jobs_not_completed_count, submitted_jobs_count))

                # If we find that a large portion of submitted jobs are not completed
                # by the time we stop checking them, we may want to increase the time
                # we are waiting for jobs to complete.
                fs_log(logging.ERROR, "Some relationship create jobs did not complete.")

        self.increase_processed(False)

        return total_status, total_log, added, updated, error

    def delete_asset_relationships(self, sources, _target, matching, mapping):
        freshservice = self.freshservice
        

        existing_assets_maps = self.get_assets_maps()

        deleted = 0
        error = 0
        total_log = None
        total_status = STATUS_SUCCESS
        relationship_type_map = {}
        relationship_map = {}

        for source in sources:
            try:

                downstream_relationship = source[mapping["@downstream-relationship"]]
                upstream_relationship = source[mapping["@upstream-relationship"]]
                object_name = "(%s - %s)" % (
                        downstream_relationship, upstream_relationship)

                if object_name in relationship_type_map:
                    relationship_type = relationship_type_map[object_name]
                else:
                    fs_log(logging.INFO, "Getting relationship type in FS.")
                    relationship_type = freshservice.get_relationship_type_by_content(downstream_relationship,
                                                                                    upstream_relationship)
                    relationship_type_map[object_name] = relationship_type
                    fs_log(logging.INFO, "finished getting relationship type in FS.")

                if relationship_type is None:
                    log = "There is no relationship type in FS. (%s - %s)" % (
                        downstream_relationship, upstream_relationship)
                    fs_log(logging.ERROR, log, object_name=object_name, object_type="Relationship")
                    total_status = STATUS_FAILED
                    if total_log is None:
                        total_log = log
                    else:
                        total_log += "\n" + log
                    error += 1
                    self.increase_processed()
                    continue
                
                primary_asset_match_values = AssetMatchValues(matching["source-1"], source)
                primary_asset = self.find_asset_in_maps(existing_assets_maps, primary_asset_match_values)
                secondary_asset_match_values = AssetMatchValues(matching["source-2"], source)
                secondary_asset = self.find_asset_in_maps(existing_assets_maps, secondary_asset_match_values)
                object_name = "Relationship %s-%s" % (
                    primary_asset["name"] if primary_asset else source[mapping["@key"]],
                    secondary_asset["name"] if secondary_asset else source[mapping["@target-key"]]
                    )

                if primary_asset is None:
                    fs_log(logging.INFO, "There is no dependent asset(%s) in FS." % source[mapping["@key"]])
                    continue

                if secondary_asset is None:
                    fs_log(logging.INFO, "There is no dependency asset(%s) in FS." % source[mapping["@target-key"]])
                    continue
                
                primary_asset_display_id = primary_asset["display_id"]
                secondary_asset_display_id = secondary_asset["display_id"]
                if primary_asset_display_id not in relationship_map:
                    relationship_map[primary_asset_display_id] = {}
                if relationship_type["id"] not in relationship_map[primary_asset_display_id]:
                    relationship_map[primary_asset_display_id][relationship_type["id"]] = {}
                relationship_map[primary_asset_display_id][relationship_type["id"]][secondary_asset_display_id] = True

            except Exception as e:
                log = "Error (%s) deleting relationship %s" % (str(e), source[mapping["@key"]])
                fs_log(logging.ERROR, log, object_name=object_name, object_type="Relationship")
                total_status = STATUS_FAILED
                if total_log is None:
                    total_log = log
                else:
                    total_log += "\n" + log
                error += 1
                self.increase_processed()

        existing_object_maps = existing_assets_maps["device42_id"]
        for existing_object_key in existing_object_maps:

            existing_object = existing_object_maps[existing_object_key]
            try:
                if 'device42_id' not in existing_object or existing_object['device42_id'] is None:
                    continue

                asset_display_id = existing_object["display_id"]

                relationships = freshservice.get_relationships_by_id(asset_display_id)

                for relationship in relationships:
                    try:
                        if asset_display_id != relationship["primary_id"]:
                            continue
                        if asset_display_id in relationship_map and \
                            relationship["relationship_type_id"] in relationship_map[asset_display_id] and \
                            relationship["secondary_id"] in relationship_map[asset_display_id][relationship["relationship_type_id"]]:
                            continue

                        object_name = "Relationship %s - %d - %d" % (
                                existing_object["name"], 
                                relationship["relationship_type_id"],
                                relationship["secondary_id"],
                            )

                        fs_log(logging.INFO, "Processing %s." % object_name)

                        freshservice.detach_relationship(relationship["id"])
                        deleted += 1
                        fs_log(logging.INFO, "detached relationship %d" % relationship["id"])
                    except Exception as e:
                        log = "Error (%s) deleting relationship %s" % (str(e), existing_object["name"])
                        fs_log(logging.ERROR, log, object_name=object_name, object_type="Relationship")
                        total_status = STATUS_FAILED
                        if total_log is None:
                            total_log = log
                        else:
                            total_log += "\n" + log
                        error += 1
                    self.increase_processed()
            except Exception as e:
                log = "Error (%s) deleting relationship %s" % (str(e), existing_object["name"])
                fs_log(logging.ERROR, log, object_name=existing_object["name"], object_type="Relationship")
                total_status = STATUS_FAILED
                if total_log is None:
                    total_log = log
                else:
                    total_log += "\n" + log
                error += 1
                self.increase_processed()

        self.increase_processed(False)

        return total_status, total_log, deleted, error

    def update_contracts_from_server(self, sources, _target, mapping):
        freshservice = self.freshservice
        

        existing_contracts_map = self.get_contracts_map()
        existing_softwares_map = self.get_softwares_map()

        added = 0
        updated = 0
        error = 0
        total_log = None
        total_status = STATUS_SUCCESS

        for source in sources:
            error_skip = False
            while True:
                try:

                    existing_object = self.find_object_in_map(existing_contracts_map, source["name"])

                    if existing_object is not None:
                        fs_log(logging.INFO, "contract %s already exists" % source["name"])
                        updated += 1
                        break

                    data = dict()
                    if not self.freshservice.default_approver:
                        raise Exception("The approver is required.")
                    data['approver_id'] = int(self.freshservice.default_approver)

                    # validation
                    for map_info in mapping["field"]:
                        if error_skip and "@error-skip" in map_info and map_info["@error-skip"]:
                            continue

                        if "@target-foreign-key" in map_info and map_info["@target-foreign"] == "applications":
                            existing_software = self.find_object_in_map(existing_softwares_map, source[map_info["@resource"]])
                            value = existing_software["id"]
                        else:
                            value = self.get_map_value_from_device42(source, map_info)

                        if "@skip-if-null" in map_info and map_info["@skip-if-null"] and value is None:
                            continue

                        if "@target-sub-key" not in map_info:
                            data[map_info["@target"]] = value
                        else:  # Item cost detail attributes
                            if map_info["@target"] not in data:
                                data[map_info["@target"]] = [{
                                    map_info["@target-sub-key"]: value
                                }]
                            else:
                                data[map_info["@target"]][0][map_info["@target-sub-key"]] = value

                        is_valid = True
                        if value is not None and "@min-length" in map_info and len(value) < map_info["@min-length"]:
                            is_valid = False
                            if value == "" and "@set-space" in map_info and map_info["@set-space"]:
                                is_valid = True
                                value = " " * map_info["@min-length"]
                        # value might have been translated to an associated ID in Freshservice by get_map_value_from_device42
                        #  which is why we need to check that value is a string using isinstance.
                        if value is not None and "@max-length" in map_info and isinstance(value, str) and len(value) > map_info["@max-length"]:
                            value = value[0:map_info["@max-length"]-3] + "..."
                        if (value is None or value == "") and "@not-null" in map_info and map_info["@not-null"]:
                            # There is an issue with the Freshservice API where sending a null value for
                            # a field will result in the API returning an error like "Has 0 characters,
                            # it should have minimum of 1 characters and can have maximum of 255 characters".
                            # This prevents us from being able to clear these field values in Freshservice (even though
                            # the Freshservice UI allows you to clear these fields).  To get around this, we will send
                            # a single space for string values and a 0 for integer and float values when the value
                            # coming from D42 is null.
                            if "@target-type" in map_info:
                                target_type = map_info["@target-type"]
                                if target_type == "integer" or target_type == "float":
                                    value = 0
                                elif target_type in ["date", "datetime"]:
                                    value = None
                                    is_valid = False
                                elif target_type == "boolean":
                                    value = False
                                else:
                                    value = " "
                            else:
                                value = " "

                        if value == 0 and "@not-zero" in map_info and map_info["@not-zero"]:
                            # Some fields in Freshservice do not allow a 0 value.
                            # D42 does allow a 0 for the value being synced over,
                            # so when we try to sync that data to Freshservice,
                            # the API returns an error like "It should be a Positive Number
                            # less than or equal to 99999999.99" when we send a 0 value to a field
                            # that does not accept 0.
                            # To get around this, we will send 1 for integer values and a 0.01
                            # for float values when the value coming from D42 is 0.
                            if "@target-type" in map_info:
                                target_type = map_info["@target-type"]
                                if target_type == "integer":
                                    value = 1
                                elif target_type == "float":
                                    value = 0.01
                                else:
                                    value = None
                                    is_valid = False
                            else:
                                value = 0.01

                        if "@target-foreign-key" in map_info and value is not None and isinstance(value, str):
                            value = self.get_map_value_from_device42(source, map_info, True)
                            is_valid = value is not None
                        if "@target-type" in map_info and value is not None:
                            target_type = map_info["@target-type"]
                            if target_type == "integer":
                                try:
                                    value = int(value)
                                except Exception as e:
                                    logger.info(f"Error converting target value to integer: {e}")
                                    is_valid = False
                            elif target_type == "boolean":
                                try:
                                    value = bool(value)
                                except Exception as e:
                                    logger.info(f"Error converting target value to integer: {e}")
                                    is_valid = False

                        if not is_valid:
                            fs_log(logging.DEBUG, "argument '%s' is invalid." % map_info["@target"])
                            if "@target-sub-key" not in map_info:
                                data.pop(map_info["@target"], None)
                            else:
                                data[[map_info["@target"]]][0].pop(map_info["@target-sub-key"])
                        if is_valid:
                            if "@target-sub-key" not in map_info:
                                data[map_info["@target"]] = value
                            else:
                                data[map_info["@target"]][0][map_info["@target-sub-key"]] = value

                    fs_log(logging.INFO, "adding contract %s" % source["name"])
                    new_contract = freshservice.insert_contract(data)
                    fs_log(logging.INFO, "added new contract %d" % new_contract["id"])
                    # We added a new object to Freshservice.  Add it to the map of objects that we know exist
                    # in Freshservice.
                    existing_contracts_map[new_contract["name"].lower()] = new_contract
                    added += 1

                    break
                except FreshserviceDuplicateValueError:
                    if not error_skip:
                        error_skip = True
                        continue
                    break
                except Exception as e:
                    object_name = existing_object["name"] if existing_object else source["name"]
                    log = "Error (%s) updating contract %s" % (str(e), object_name)
                    fs_log(logging.ERROR, log,
                           object_name=object_name,
                           object_type="Contract")
                    total_status = STATUS_FAILED
                    if total_log is None:
                        total_log = log
                    else:
                        total_log += "\n" + log
                    error += 1
                    break

            self.increase_processed()

        self.increase_processed(False)
        return total_status, total_log, added, updated, error

    def create_association_between_asset_and_contract(self, sources, _target, matching, mapping):
        freshservice = self.freshservice
        

        existing_assets_maps = self.get_assets_maps()
        existing_contracts_map = self.get_contracts_map()

        updated = 0
        added = 0
        error = 0
        total_log = None
        total_status = STATUS_SUCCESS
        # Key will be the contract ID and the value will be a set of asset IDs that the contract is
        # associated with.
        contract_to_assets_map = dict()
        object_type = "Association between asset and contract"

        for source in sources:
            try:
                object_name = None

                fs_log(logging.INFO, "Processing %s - %s." % (source[mapping["@device-name"]], source[mapping["@contract-name"]]))
                asset_match_values = AssetMatchValues(matching["source-1"], source)
                asset = self.find_asset_in_maps(existing_assets_maps, asset_match_values)
                contract = self.find_object_in_map(existing_contracts_map, source[mapping["@contract-name"]])
                object_name = "%s - %s." % (
                    asset["name"] if asset else source[mapping["@device-name"]],
                    contract["name"] if contract else source[mapping["@contract-name"]]
                    )

                if asset is None:
                    error += 1
                    self.increase_processed()
                    log = "There is no asset(%s) in FS." % source[mapping["@device-name"]]
                    fs_log(logging.ERROR, log, object_name=object_name, object_type=object_type)
                    total_status = STATUS_FAILED
                    if total_log is None:
                        total_log = log
                    else:
                        total_log += "\n" + log
                    continue

                if contract is None:
                    error += 1
                    self.increase_processed()
                    log = "There is no contract(%s) in FS." % source[mapping["@contract-name"]]
                    fs_log(logging.ERROR, log, object_name=object_name, object_type=object_type)
                    total_status = STATUS_FAILED
                    if total_log is None:
                        total_log = log
                    else:
                        total_log += "\n" + log
                    continue

                if contract["id"] not in contract_to_assets_map:
                    associated_assets = freshservice.get_associated_assets_by_contract(contract["id"])
                    contract_to_assets_map[contract["id"]] = {a["display_id"] for a in associated_assets}

                if asset['display_id'] in contract_to_assets_map[contract["id"]]:
                    updated += 1
                    self.increase_processed()
                    fs_log(logging.INFO, "There is already associated asset in FS.")
                    continue

                contract_to_assets_map[contract["id"]].add(asset['display_id'])
                data = dict()
                data['associated_asset_ids'] = list(contract_to_assets_map[contract["id"]])

                fs_log(logging.INFO, "adding associated asset %s-%s" % (source[mapping["@device-name"]], source[mapping["@contract-name"]]))
                freshservice.update_contract(data, contract["id"])
                added += 1
                fs_log(logging.INFO, "added associated asset %s-%s" % (source[mapping["@device-name"]], source[mapping["@contract-name"]]))
            except Exception as e:
                log = "Error (%s) creating associated assets %s-%s" % (str(e), source[mapping["@device-name"]], source[mapping["@contract-name"]])
                fs_log(logging.ERROR, log, object_name=object_name, object_type=object_type)
                total_status = STATUS_FAILED
                if total_log is None:
                    total_log = log
                else:
                    total_log += "\n" + log
                error += 1

            self.increase_processed()

        self.increase_processed(False)

        return total_status, total_log, added, updated, error

    def update_component_in_maps(self, asset_device42_id, asset_component, existing_components_maps):
        if asset_device42_id not in existing_components_maps:
            existing_components_maps[asset_device42_id] = {}
        existing_components_maps[asset_device42_id][asset_component['component_type']] = asset_component

    def is_computer_asset(self, asset_type_id):
        freshservice = self.freshservice

        if "asset_type_fields" not in self.fs_cache:
            self.fs_cache["asset_type_fields"] = {}

        if asset_type_id in self.fs_cache["asset_type_fields"]:
            asset_type_fields = self.fs_cache["asset_type_fields"][asset_type_id]
        else:
            asset_type_fields = freshservice.get_asset_type_fields(asset_type_id)
            self.fs_cache["asset_type_fields"][asset_type_id] = asset_type_fields
        
        for field_set in asset_type_fields:
            if field_set['field_header'] == ASSET_TYPE_COMPUTER:
                return True
        return False

    def update_components_from_server(self, sources, _target, matching, mapping):
        freshservice = self.freshservice
        

        existing_assets_maps = self.get_assets_maps()
        existing_components_maps = self.get_components_maps()

        source_maps = {}
        source_mapping = {}
        for source in sources:
            asset_device42_id = source[matching["source-1"]["@device42-id"]].lower()
            source_mapping[asset_device42_id] = source
            if asset_device42_id not in source_maps:
                source_maps[asset_device42_id] = {}

            source_map = source_maps[asset_device42_id]
            if source['component_type'] not in source_map:
                source_map[source['component_type']] = []
            
            source_map[source['component_type']].append(source)

        added = 0
        updated = 0
        error = 0
        total_log = None
        asset = None
        total_status = STATUS_SUCCESS

        for asset_device42_id in source_maps:
            source_map = source_maps[asset_device42_id]
            try:
                source = source_mapping[asset_device42_id]
                asset_match_values = AssetMatchValues(matching["source-1"], source)
                asset = self.find_asset_in_maps(existing_assets_maps, asset_match_values)
                if asset is None:
                    log = "There is no asset(%s) in FS." % asset_device42_id
                    for component_type in source_map:
                        sources = source_map[component_type]
                        error += len(sources)
                        for source in sources:
                            object_name = "Component %s-%s" % (
                                source['device_name'],
                                source["component_type"]
                                )
                            fs_log(logging.ERROR, log, object_name=object_name, object_type="Component")
                        self.increase_processed(amount=len(sources))
                    total_status = STATUS_FAILED
                    if total_log is None:
                        total_log = log
                    else:
                        total_log += "\n" + log
                    continue
                
                asset_type_id = asset["asset_type_id"]
                if not self.is_computer_asset(asset_type_id):
                    log = "Asset type(%d) is not computer in FS." % asset_type_id
                    for component_type in source_map:
                        sources = source_map[component_type]
                        updated += len(sources)
                        for source in sources:
                            object_name = "Component %s-%s" % (
                                asset['name'],
                                source["component_type"]
                                )
                            fs_log(logging.INFO, log, object_name=object_name, object_type="Component")
                        self.increase_processed(amount=len(sources))
                    if total_log is None:
                        total_log = log
                    else:
                        total_log += "\n" + log
                    continue

                if asset_device42_id not in existing_components_maps:
                    asset_components = freshservice.get_components_by_asset_id(asset["display_id"])
                    for asset_component in asset_components:
                        self.update_component_in_maps(asset_device42_id, asset_component, existing_components_maps)
                    
                for component_type in source_map:
                    sources = source_map[component_type]

                    existing_component = None
                    if asset_device42_id in existing_components_maps and component_type in existing_components_maps[asset_device42_id]:
                        existing_component = existing_components_maps[asset_device42_id][component_type]

                    payload = dict()
                    payload['component_data'] = []

                    for source in sources:
                        data = dict()
                        for map_info in mapping["field"]:
                            value = self.get_map_value_from_device42(source, map_info)
                            data[map_info["@target"]] = value

                            is_valid = True
                            if value is not None and "@min-length" in map_info and len(value) < map_info["@min-length"]:
                                is_valid = False
                                if value == "" and "@set-space" in map_info and map_info["@set-space"]:
                                    is_valid = True
                                    value = " " * map_info["@min-length"]

                            if value is not None and "@max-length" in map_info and isinstance(value, str) and len(value) > map_info["@max-length"]:
                                value = value[0:map_info["@max-length"]-3] + "..."
                            if (value is None or value == "") and "@not-null" in map_info and map_info["@not-null"]:
                                if "@target-type" in map_info:
                                    target_type = map_info["@target-type"]
                                    if target_type == "integer" or target_type == "float":
                                        value = 0
                                    elif target_type in ["date", "datetime"]:
                                        value = None
                                        is_valid = False
                                    else:
                                        is_valid = False
                                else:
                                    value = " "

                            if value == 0 and "@not-zero" in map_info and map_info["@not-zero"]:
                                if "@target-type" in map_info:
                                    target_type = map_info["@target-type"]
                                    if target_type == "integer":
                                        value = 1
                                    elif target_type == "float":
                                        value = 0.01
                                    else:
                                        value = None
                                        is_valid = False
                                else:
                                    value = 0.01

                            if "@target-type" in map_info and value is not None:
                                target_type = map_info["@target-type"]
                                if target_type == "integer":
                                    try:
                                        value = int(value)
                                    except:
                                        is_valid = False

                            if not is_valid:
                                fs_log(logging.DEBUG, "argument '%s' is invalid." % map_info["@target"])
                                data.pop(map_info["@target"], None)

                            if is_valid:
                                data[map_info["@target"]] = value
                        
                        payload['component_data'].append(data)
                        if len(payload['component_data']) >= 500:
                            fs_log(logging.INFO, "Reached max 500 components %s - %s" % (asset_device42_id, component_type))
                            break

                    if existing_component is None:
                        fs_log(logging.INFO, "adding component %s - %s" % (asset_device42_id, component_type))
                        payload['component_type'] = component_type
                        asset_component = freshservice.insert_component(asset["display_id"], payload)
                        fs_log(logging.INFO, "added new component %d" % asset_component["id"])
                        added += len(sources)
                    else:
                        fs_log(logging.INFO, "updating component %s - %s" % (asset_device42_id, component_type))
                        asset_component = freshservice.update_component(asset["display_id"], existing_component['id'], payload)
                        fs_log(logging.INFO, "updated component %d" % asset_component["id"])
                        updated += len(sources)

            except Exception as e:
                log = "Error (%s) updating component" % str(e)
                for component_type in source_map:
                    sources = source_map[component_type]
                    error += len(sources)
                    for source in sources:
                        object_name = "Component %s-%s" % (
                            asset['name'] if asset else source['device_name'],
                            source["component_type"]
                            )
                        fs_log(logging.ERROR, log, object_name=object_name, object_type="Component")
                total_status = STATUS_FAILED
                if total_log is None:
                    total_log = log
                else:
                    total_log += "\n" + log

            for component_type in source_map:
                sources = source_map[component_type]
                self.increase_processed(amount=len(sources))

        self.increase_processed(False)
        return total_status, total_log, added, updated, error

    def task_execute(self, task, execute=True):
        

        if "@description" in task:
            fs_log(logging.INFO, "Execute task - %s" % task["@description"])

        _resource = task["api"]["resource"]
        _target = task["api"]["target"]

        if "@doql" in _resource:
            doql = str(_resource['@doql']).strip()
        else:
            doql = None

        _type = None
        if "@type" in task:
            _type = task["@type"]

        matching = None
        if 'matching' in task:
            matching = task['matching']

        mapping = task['mapping']

        if "@doql-suffix" in mapping:
            suffix = mapping['@doql-suffix']
            suffix = suffix % self.last_update
            doql = "%s %s" % (doql, suffix)

        object_name = None
        if "@name" in task:
            object_name = task["@name"]
        elif "@description" in task:
            object_name = task["@description"]
        else:
            object_name = "N/A"
            
        doql_results = self.middle_post(doql)
        if doql_results['err']:
            if execute:
                fs_log(logging.ERROR, doql_results["msg"], object_name=object_name, object_type="Task")
                return STATUS_FAILED, doql_results["msg"], 0, 0, 0, 1

            return STATUS_FAILED, doql_results["msg"], 0, 0, 0, 0

        sources = doql_results["objects"]

        if _type and _type in ("contract", "contract_asset") and self.freshservice.default_approver is None:  # to support Backward compatibility
            return STATUS_SUCCESS, None, 0, 0, 0, 0

        if not execute:
            return STATUS_SUCCESS, None, len(sources), 0, 0, 0

        added = 0
        updated = 0
        deleted = 0
        error = 0
        try:
            if _type == "asset_relationship":
                if "@delete" in _target and _target["@delete"]:
                    status, log, deleted, error = self.delete_asset_relationships(sources, _target, matching, mapping)
                else:
                    status, log, added, updated, error = self.create_asset_relationships(sources, _target, matching, mapping)
            elif _type == "software":
                if "@delete" in _target and _target["@delete"]:
                    status, log, updated, error = self.delete_softwares_from_server(sources, _target, mapping)
                else:
                    status, log, added, updated, error = self.update_softwares_from_server(sources, _target, mapping)
            elif _type == "software_installation":
                if "@delete" in _target and _target["@delete"]:
                    status, log, updated, error = self.delete_softwares_from_server(sources, _target, mapping)
                else:
                    status, log, added, updated, error = self.create_software_installations(sources, _target, matching, mapping)
            elif _type == "contract":
                status, log, added, updated, error = self.update_contracts_from_server(sources, _target, mapping)
            elif _type == "contract_asset":
                status, log, added, updated, error = self.create_association_between_asset_and_contract(sources, _target, matching, mapping)
            elif _type == "product":
                status, log, added, updated, error = self.update_products_from_server(sources, _target, mapping)
            elif _type == "component":
                status, log, added, updated, error = self.update_components_from_server(sources, _target, matching, mapping)
            else:
                if "@delete" in _target and _target["@delete"]:
                    status, log, deleted, error = self.delete_objects_from_server(sources, _target, matching, mapping)
                else:
                    status, log, added, updated, error = self.update_objects_from_server(sources, _target, matching, mapping)
            return status, log, added, updated, deleted, error
        except Exception as e:
            fs_log(logging.ERROR, str(e), object_name=object_name, object_type="Task")
            return STATUS_FAILED, str(e), 0, 0, 0, 1

    def get_d42_cache_items(self, cache_name):
        cache_items = None
        if cache_name in self.d42_cache:
            fs_log(logging.INFO, "Getting items %s in D42 from cache." % cache_name)
            cache_items = self.d42_cache[cache_name]
            fs_log(logging.INFO, "Finished getting items %s in D42 from cache." % cache_name)
        else:
            if cache_name == D42_CACHE_SERIAL_NUMBER_DEVICE_COUNTS:
                fs_log(logging.INFO, "Getting items %s in D42." % cache_name)
                doql = "select lower(d.serial_no) as serial_no, count(*) as device_count "\
                       "from view_device_v1 d "\
                       "where d.serial_no is not null and d.serial_no <> '' "\
                       "group by lower(d.serial_no)"
                doql_results = self.middle_post(doql)
                if doql_results['err']:
                    fs_log(logging.ERROR, doql_results["msg"])
                else:
                    cache_items = dict()
                    rows = doql_results["objects"]
                    for row in rows:
                        cache_items[row["serial_no"]] = row["device_count"]
                    self.d42_cache[cache_name] = cache_items
                fs_log(logging.INFO, "Finished getting items %s in D42." % cache_name)

        return cache_items

    def get_cache_items(self, cache_name, path, model):
        if cache_name in self.fs_cache:
            fs_log(logging.INFO, "Getting all existing %s in FS from cache." % cache_name)
            cache_items = self.fs_cache[cache_name]
            fs_log(logging.INFO, "Finished getting all existing %s in FS from cache." % cache_name)
        elif path is not None:
            fs_log(logging.INFO, "Getting all existing %s in FS." % cache_name)
            if cache_name in [CACHE_ASSETS, CACHE_TRASH_ASSETS]:
                cache_items = self.freshservice.get_assets_maps(path, model)
            else:
                cache_items = self.freshservice.get_objects_map(path, model)
            self.fs_cache[cache_name] = cache_items
            fs_log(logging.INFO, "Finished getting all existing %s in FS." % cache_name)
        else:
            fs_log(logging.INFO, "Setting cache %s as blank." % cache_name)
            self.fs_cache[cache_name] = {}
            cache_items = self.fs_cache[cache_name]
            fs_log(logging.INFO, "Finished setting cache %s as blank." % cache_name)

        return cache_items

    def process_tasks(self, config):
        if "task" not in config["meta"]["tasks"]:
            fs_log(logging.ERROR, "No task")
            return
        
        try:
            if isinstance(config["meta"]["tasks"]["task"], list):
                tasks = config["meta"]["tasks"]["task"]
            else:
                tasks = [config["meta"]["tasks"]["task"]]

            count_added = 0
            count_updated = 0
            count_deleted = 0
            count_error = 0
            total_log = None
            total_status = STATUS_SUCCESS
            total_count = 0

            d42_version = self.device42.get_version()

            for task in tasks:
                if not task["@enable"]:
                    continue

                _target = task["api"]["target"]
                if "@delete" in _target and _target["@delete"]:
                    continue

                # get supported d42 versions for the task
                min_supported_version = task["@d42_min_version"] if "@d42_min_version" in task else None
                max_supported_version = task["@d42_max_version"] if "@d42_max_version" in task else None

                # check if the task should be run based on the current D42's version and the limits of task
                if check_version(d42_version, min_supported_version, max_supported_version):
                    # run the task
                    print(f"[Info] {task['@description']} running")
                else:
                    print(f"[Error] {task['@description']} was not run due to incompatibility with current D42 version")
                    continue  # continue to the next task

                status, log, added, updated, deleted, error = self.task_execute(task, False)
                total_count += added

                if status != STATUS_SUCCESS:
                    if total_log is None:
                        total_log = log
                    else:
                        total_log += "\n" + (log if log is not None else "")
                    total_status = status

            for task in tasks:
                if not task["@enable"]:
                    continue

                # get supported d42 versions for the task
                min_supported_version = task["@d42_min_version"] if "@d42_min_version" in task else None
                max_supported_version = task["@d42_max_version"] if "@d42_max_version" in task else None

                # check if the task should be run based on the current D42's version and the limits of task
                if check_version(d42_version, min_supported_version, max_supported_version):
                    # run the task
                    print(f"[Info] {task['@description']} running")
                else:
                    print(f"[Error] {task['@description']} was not run due to incompatibility with current D42 version")
                    continue  # continue to the next task

                status, log, added, updated, deleted, error = self.task_execute(task)
                count_added += added
                count_updated += updated
                count_deleted += deleted
                count_error += error

            print("Completed!")
        except Exception as e:
            fs_log(logging.ERROR, str(e))
    
    def middle_post(self, query):
        resp = None
        try:
            resp = self.device42.doql(query)
            err = False
            doql_result = {
                'err': err,
                'objects': resp
            }
        except Exception as e:
            print(str(e))
            doql_result = {
                'err': True,
                'msg': str(e)
            }
            logger.exception(str(e))
        return doql_result

class AssetMatchValues(object):
    # This list is like the one defined in class Freshservice except that it also includes mac_address.
    # We don't create a map for assets that has a key of the MAC address since we will call the
    # Freshservice API to find an asset with a MAC address.
    ASSET_MATCH_FIELDS = ["device42_id", "name", "serial_number", "uuid", "item_id", "mac_address", "imei_number"]

    def __init__(self, source_mapping, source):
        for field in self.ASSET_MATCH_FIELDS:
            setattr(self, field, None)

            # Convert the field to how it appears in the dictionary representation
            # of the XML.  For example, if the field is device42_id, the XML attribute
            # in the dictionary would be @device42-id.
            key = '@%s' % field.replace('_', '-')

            if key in source_mapping and source_mapping[key]:
                if source_mapping[key] in source:
                    val = source[source_mapping[key]]
                    setattr(self, field, val)