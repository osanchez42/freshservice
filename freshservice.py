import re
import requests
from datetime import datetime
import time
from urllib.parse import quote
from Constants import *

class FreshserviceBaseException(Exception):
    pass


class FreshserviceHTTPError(FreshserviceBaseException):
    pass


class FreshserviceDuplicateValueError(FreshserviceHTTPError):
    pass


class Freshservice(object):
    CITypeServerName = "Server"
    PAGE_SIZE = 100
    JWT_VALID_FOR_SECONDS = 600
    JWT_RECREATE_WHEN_SECONDS_LEFT = 30
    ASSET_MATCH_FIELDS = ["device42_id", "name", "serial_number", "uuid", "item_id", "imei_number"]

    def __init__(self, url, api_key, freshservice_default_approver, logger):
        self.base = url
        self.api_token = api_key
        self.logger = logger
        self.default_approver = freshservice_default_approver
        self.base_url = self.base
        self.headers = {}
        self.last_time_call_api = None
        self.period_call_api = 1
        self.api_call_count = 0
        self.asset_types = None
        self.serial_number_field_regex = re.compile('^serial_number_[0-9]+$')
        self.uuid_field_regex = re.compile('^uuid_[0-9]+$')
        self.item_id_field_regex = re.compile('^item_id_[0-9]+$')
        self.imei_number_field_regex = re.compile('^imei_number_[0-9]+$')

    def _send(self, method, path, data=None, headers=None):
        """ General method to send requests """
        now = datetime.now()
        self.api_call_count += 1

        is_getting_exist = False
        if method == 'GET' and data is not None and "page" in data:
            is_getting_exist = True

        # if not is_getting_exist and self.last_time_call_api is not None and (
        #             now - self.last_time_call_api).total_seconds() < self.period_call_api:
        #     time.sleep(self.period_call_api - (now - self.last_time_call_api).total_seconds())

        url = "%s/%s" % (self.base_url, path)
        params = None
        if method == 'GET':
            params = data
            data = None

        all_headers = self.headers
        if headers:
            all_headers.update(headers)

        retries = 0
        max_retries = 3
        retry_delay = 2  # second


        while True:
            if method == 'GET':
                resp = requests.request(method, url, auth=(self.api_token, "X"), data=data, params=params, headers=all_headers)
            else:
                resp = requests.request(method, url, auth=(self.api_token, "X"), json=data, params=params, headers=all_headers)

            self.last_time_call_api = datetime.now()

            if not resp.ok:
                if resp.status_code == 429:
                    self._log("HTTP %s (%s) Error %s: %s\n request was %s" %
                              (method, path, resp.status_code, resp.text, data))

                    retry_after = DEFAULT_RETRY_AFTER
                    header_value = resp.headers.get(RETRY_AFTER_HEADER)
                    if header_value:
                        try:
                            retry_after = int(header_value)
                        except ValueError as e:
                            self._log('Failed to convert Retry-After value of "%s" to int: %s' % (header_value, str(e)))

                    self._log("Throttling %d second(s)..." % retry_after)
                    time.sleep(retry_after)
                    continue

                if resp.status_code == 400:
                    exception = None
                    try:
                        error_resp = resp.json()
                        if error_resp["description"] == "Validation failed":
                            for error in error_resp["errors"]:
                                if ((error["field"] == "serial_number" or error["field"] == "item_id") and \
                                        (error["message"] == " must be unique" or error["message"] == " is not unique")) or \
                                        (error["field"] == "base" and error["message"] and error["message"].lower() == "asset already exists"):
                                    exception = FreshserviceDuplicateValueError("HTTP %s (%s) Error %s: %s\n request was %s" %
                                                                (method, path, resp.status_code, resp.text, data))
                                    break
                    except Exception:
                        pass

                    if exception is not None:
                        raise exception
                elif resp.status_code >= 500:
                    # Retry the request if we got back a 5xx status code in case the error is temporary
                    # like a network issue.
                    if retries < max_retries:
                        retries += 1
                        self._log("Retrying in %d seconds..." % retry_delay)
                        # This is an exponential delay:
                        # retry 1 delay is 2 seconds
                        # retry 2 delay is 4 seconds
                        # retry 3 delay is 8 seconds
                        time.sleep(retry_delay)
                        retry_delay *= 2
                        continue

                raise FreshserviceHTTPError("HTTP %s (%s) Error %s: %s\n request was %s" %
                                            (method, path, resp.status_code, resp.text, data))

            if method == "DELETE":
                return True

            if resp.status_code == 204:
                return {}

            retval = resp.json()
            return retval

    def _get(self, path, data=None):
        return self._send("GET", path, data=data)

    def _post(self, path, data, headers=None):
        if not path.endswith('/'):
            path += '/'
        return self._send("POST", path, data=data, headers=headers)

    def _patch(self, path, data, headers=None):
        if not path.endswith('/'):
            path += '/'
        return self._send("PATCH", path, data=data, headers=headers)

    def _put(self, path, data=None, headers=None):
        if not path.endswith('/'):
            path += '/'
        return self._send("PUT", path, data=data, headers=headers)

    def _delete(self, path, data=None):
        return self._send("DELETE", path, data)

    def _log(self, message):
        if self.logger:
            self.logger.debug(message)

    def insert_asset(self, data):
        path = "api/channel/device42/assets"
        result = self._post(path, data)
        return self.create_basic_object(result["asset"])

    def update_asset(self, data, display_id):
        path = "api/channel/device42/assets/%d" % display_id
        result = self._put(path, data)
        return self.create_basic_object(result["asset"])

    def delete_asset(self, display_id):
        path = "api/channel/device42/assets/%d" % display_id
        result = self._delete(path)
        return result

    def search_assets(self, search_field, search_value):
        search = quote("%s:'%s'" % (search_field, search_value))
        path = 'pi/channel/device42/assets?include=type_fields&search="%s"' % search
        result = self._get(path)
        basic_objects = []
        for asset in result['assets']:
            basic_objects.append(self.create_basic_object(asset))

        return basic_objects

    def get_assets_by_asset_type(self, asset_type_id):
        path = "api/channel/device42/assets?include=type_fields&query=\"asset_type_id:%d\"" % asset_type_id
        assets = self._get(path)
        return assets["assets"]

    def get_components_by_asset_id(self, asset_id):
        path = "api/channel/device42/assets/%d/components" % asset_id
        result = self._get(path)
        return result["components"]

    def insert_component(self, asset_id, data):
        path = "api/channel/device42/applications"
        result = self._post(path, data)
        return result["component"]

    def update_component(self, asset_id, component_id, data):
        path = "api/channel/device42/assets/%d/components/%d" % (asset_id, component_id)
        result = self._put(path, data)
        return result["component"]

    def insert_software(self, data):
        path = "api/channel/device42/applications"
        result = self._post(path, data)
        return self.create_basic_object(result["application"])

    def delete_software(self, id):
        path =  "api/channel/device42/applications/%d" % id
        result = self._delete(path)
        return result

    def insert_product(self, data):
        path = "api/channel/device42/products"
        result = self._post(path, data)
        return self.create_basic_object(result["product"])

    def update_product(self, data, id):
        path = "api/channel/device42/products/%d" % id
        result = self._put(path, data)
        return result["product"]["id"]

    def insert_contract(self, data):
        path = "api/channel/device42/contracts"
        result = self._post(path, data)
        return self.create_basic_object(result["contract"])

    def update_contract(self, data, id):
        path = "api/channel/device42/contracts/%d" % id
        result = self._put(path, data)
        return result["contract"]["id"]

    def get_associated_assets_by_contract(self, contract_id):
        path = "api/channel/device42/contracts/%d/associated-assets" % contract_id
        return self.request(path, "GET", "associated_assets")

    def get_all_ci_types(self):
        if self.asset_types is not None:
            return self.asset_types
        path = "api/channel/device42/asset_types"
        self.asset_types = self.request(path, "GET", "asset_types")
        return self.asset_types

    def get_ci_type_by_name(self, name, all_ci_types=None):
        if all_ci_types is None:
            all_ci_types = self.get_all_ci_types()

        for ci_type in all_ci_types:
            if ci_type["name"] == name:
                return ci_type

        return None

    def get_all_server_ci_types(self):
        all_ci_types = self.get_all_ci_types()

        server_types = []
        server_type = self.get_ci_type_by_name("Server", all_ci_types)
        if server_type is None:
            return []

        server_types.append(server_type)
        for ci_type in all_ci_types:
            if ci_type["parent_asset_type_id"] == server_type["id"]:
                server_types.append(ci_type)

        return server_types

    def get_server_ci_type(self):
        return self.get_ci_type_by_name(self.CITypeServerName)

    def get_windows_server_ci_type(self):
        return self.get_ci_type_by_name(self.CITypeWindowsServerName)

    def get_unix_server_ci_type(self):
        return self.get_ci_type_by_name(self.CITypeUnixServerName)

    def get_asset_type_fields(self, asset_type_id):
        path = "api/channel/device42/asset_types/%d/fields" % asset_type_id
        return self._get(path)["asset_type_fields"]

    def get_all_server_assets(self):
        server_asset_types = self.get_all_server_ci_types()
        server_assets = []
        for asset_type in server_asset_types:
            assets = self.get_assets_by_asset_type(asset_type["id"])
            server_assets += assets

        return server_assets

    def get_products(self):
        path = "api/channel/device42/products"
        products = self._get(path)
        return products["products"]

    def get_vendors(self):
        path = "api/channel/device42/vendors"
        vendors = self._get(path)
        return vendors["vendors"]

    def get_agents(self, search, page, per_page):
        path = "api/channel/device42/agents"
        data = {'page': page, 'per_page': per_page}
        if search and len(search) >= 2:
            data['query'] = '"~[name|first_name|last_name|email]:\'' + search + '\'"'
        vendors = self._get(path, data)
        return vendors["agents"]

    def get_id_by_name(self, model, name, foreign_key="name"):
        path = "api/channel/device42/%s" % model
        models = self.request(path, "GET", model)
        for model in models:
            if foreign_key in model and model[foreign_key] is not None and name is not None and \
                            model[foreign_key].lower() == name.lower():
                return model["id"]

        return None

    def insert_and_get_by_name(self, model, name, asset_type_id, foreign_key="name"):
        path = "api/channel/device42/%s" % model
        if asset_type_id is not None:
            data = {foreign_key: name, "asset_type_id": asset_type_id}
        else:
            data = {foreign_key: name}
        models = self._post(path, data)
        for key in models:
            return self.create_basic_object(models[key])

        return None

    def request(self, source_url, method, model):
        if method == "GET":
            models = []
            page = 1
            while True:
                result = self._get(source_url, data={"page": page, "per_page": self.PAGE_SIZE})
                if model in result:
                    models += result[model]
                    if len(result[model]) == 0:
                        break
                else:
                    break

                page += 1

            return models
        return []

    def normalize_value(self, val):
        if val:
            # Replace Unicode no-break spaces with normal spaces.
            # We are doing the same with the data we get from D42.
            # This will allow us to find objects in Freshservice regardless if the name
            # is using Unicode no-break spaces or normal ASCII spaces since the Unicode
            # no-break spaces will always be converted to normal ASCII spaces.
            return val.replace(u'\xa0', ' ')

        return val

    def create_basic_object(self, m):
        # Create an object using only the properties that we will need.  This object will
        # be stored in the cache, so we want to try to minimize the memory footprint of it.
        obj = {"id": m["id"]}

        if "device42_id" in m:
            obj["device42_id"] = m["device42_id"]

        if "name" in m:
            obj["name"] = self.normalize_value(m["name"])

        if "email" in m:
            obj["email"] = m["email"]

        # Not all models have a display_id (e.g. assets do, but asset types do not).
        if "display_id" in m:
            obj["display_id"] = m["display_id"]

        if "agent_id" in m:
            obj["agent_id"] = m["agent_id"]

        if "asset_type_id" in m:
            obj["asset_type_id"] = m["asset_type_id"]

        if "parent_asset_type_id" in m:
            obj["parent_asset_type_id"] = m["parent_asset_type_id"]

        if "type_fields" in m:
            found_serial_number_field = False
            found_uuid_field = False
            found_item_id_field = False
            found_imei_number_field = False

            for field in m["type_fields"]:
                if found_serial_number_field and found_uuid_field and found_item_id_field and found_imei_number_field:
                    break

                if not found_serial_number_field:
                    if self.serial_number_field_regex.match(field) is not None:
                        obj["serial_number"] = m["type_fields"][field]
                        found_serial_number_field = True

                if not found_uuid_field:
                    if self.uuid_field_regex.match(field) is not None:
                        obj["uuid"] = m["type_fields"][field]
                        found_uuid_field = True

                if not found_item_id_field:
                    if self.item_id_field_regex.match(field) is not None:
                        obj["item_id"] = m["type_fields"][field]
                        found_item_id_field = True

                if not found_imei_number_field:
                    if self.imei_number_field_regex.match(field) is not None:
                        obj["imei_number"] = m["type_fields"][field]
                        found_imei_number_field = True

        return obj

    def get_assets_maps(self, source_url, model):
        objects = self.request(source_url, "GET", model)

        # We will have a map for each criterion that we want to find an asset by:
        # 1) Device42 ID
        # 2) name
        # 3) serial number
        # 4) UUID
        # 5) item ID
        # 6) imei number
        assets_maps = dict()

        # Create a map for each field we want to be able to search for an asset by.
        # The name of the map will be same as the name of the field we want to search by.
        # For example, if we want to find an asset with serial number "123", we will search
        # the map named "serial_number".
        for field in self.ASSET_MATCH_FIELDS:
            assets_maps[field] = dict()

        for obj in objects:
            basic_obj = self.create_basic_object(obj)
            self.add_asset_to_maps(basic_obj, assets_maps)

        return assets_maps

    def add_asset_to_maps(self, asset, assets_maps):
        for field in self.ASSET_MATCH_FIELDS:
            key = self._create_assets_map_key(asset, field)
            if key:
                assets_maps[field][key] = asset

    def delete_asset_from_maps(self, asset, assets_maps):
        for field in self.ASSET_MATCH_FIELDS:
            key = self._create_assets_map_key(asset, field)
            if key and key in assets_maps[field]:
                del assets_maps[field][key]

    def _create_assets_map_key(self, obj, field):
        key = None

        if field in obj:
            key = self.create_assets_map_key_from_value(obj[field])

        return key

    def create_assets_map_key_from_value(self, val):
        key = None
        if val:
            key = val.strip()
            if key:
                key = self.normalize_value(val).lower()

        return key

    def get_objects_map(self, source_url, model, foreign_key="name"):
        objects = self.request(source_url, "GET", model)
        # Return a dictionary where the key is the lowercase name of the object (usually, but could be any other property
        # of the object like the display id) and the value is the basic object (e.g. id, name, etc.).
        return {self.normalize_value(obj[foreign_key]).lower() if isinstance(obj[foreign_key], str) else obj[foreign_key]: self.create_basic_object(obj) for obj in objects}

    def get_relationship_type_by_content(self, downstream, upstream):
        path = "api/channel/device42/relationship-types"
        relationship_types = self.request(path, "GET", "relationship_types")

        for relationship_type in relationship_types:
            if relationship_type["downstream_relation"] == downstream and relationship_type["upstream_relation"] == upstream:
                return relationship_type

        return None

    def get_relationships_by_id(self, asset_id):
        path = "api/channel/device42/assets/%d/relationships" % asset_id
        return self.request(path, "GET", "relationships")

    def insert_relationships(self, data):
        path = "api/channel/device42/relationships/bulk-create"
        job = self._post(path, data)
        return job["job_id"]

    def detach_relationship(self, relationship_id):
        path = "api/channel/device42/relationships?ids=%d" % relationship_id
        return self._delete(path)

    def get_installations_by_id(self, display_id):
        path = "api/channel/device42/applications/%d/installations" % display_id
        return self.request(path, "GET", "installations")

    def insert_installation(self, display_id, data):
        path = "api/channel/device42/applications/%d/installations" % display_id
        installation = self._post(path, data)
        if len(installation) > 0:
            return installation['installation']["id"]

        return -1

    # Im not sure if there is an endpoint for this in public API
    def upsert_installation(self, display_id, data):
        path = "api/channel/device42/applications/%d/upsert-installations" % display_id
        job = self._post(path, data)
        return job["job_id"]

    def get_job(self, job_id):
        path = "api/channel/device42/jobs/%s" % job_id
        return self._get(path)

    def register_main_appliance(self, data):
        path = "api/channel/device42/main-appliance/register"
        self._post(path, data)

    def oauth2_app(self, data):
        path = "api/channel/device42/oauth2/apps"
        return self._post(path, data)

    def oauth2_app_update(self, app_id, data):
        path = "api/channel/device42/oauth2/apps/" + app_id
        return self._patch(path, data)

    def oauth2_app_delete(self, app_id):
        path = "api/channel/device42/oauth2/apps/" + app_id
        return self._delete(path)

    def get_organization(self):
        path = "api/channel/device42/organization"
        return self._get(path)

    def get_all_assets(self, assets=[], page=1):
        path = f"api/v2/assets?per_page=100&page={page}"
        resp = self._get(path)
        current_assets = resp.get('assets', [])
        assets += current_assets

        if not current_assets:
            return assets

        return self.get_all_assets(assets, page + 1)

    def get_all_relationships(self, relationships=[], page=1):
        path = f"api/v2/relationships?per_page=100&page={page}"
        resp = self._get(path)
        current_relationships = resp.get('relationships', [])
        relationships += current_relationships

        if not current_relationships:
            return relationships

        return self.get_all_relationships(relationships, page + 1)
    
    def delete_asset(self, asset_id):
        path = "api/v2/assets/%d" % asset_id
        return self._delete(path)
    
    def delete_all_assets(self):
        all_assets = self.get_all_assets()
        for asset in all_assets:
            display_id = asset.get('display_id')
            if display_id:
                print("deleting asset with display id: %d" % display_id)
                path = "api/v2/assets/%d/delete_forever" % display_id
                self._put(path, None, {'content-type': 'application/json'})
    
    def delete_all_relationships(self):
        all_relationships = self.get_all_relationships()
        all_relationship_ids = []
        for relationship in all_relationships:
            relationship_id = relationship.get('id')
            if relationship_id:
                all_relationship_ids.append(str(relationship_id))
        # delete in max 100 relationship chunks
        while all_relationship_ids:
            path = "api/v2/relationships?ids=%s" % ",".join(all_relationship_ids[:100])
            self._delete(path)
            all_relationship_ids = all_relationship_ids[100:]


