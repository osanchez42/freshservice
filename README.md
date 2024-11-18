[Device42](http://www.device42.com/) is a Continuous Discovery software for your IT Infrastructure. It helps you automatically maintain an up-to-date inventory of your physical, virtual, and cloud servers and containers, network components, software/services/applications, and their inter-relationships and inter-dependencies.


This repository contains script that helps you sync data from Device42 to Freshservice.

### Download and Installation
-----------------------------
Device42 v16.19.00+ 
Python 3.5+

The following Python Packages are required:

* certifi==2024.8.30
* cffi==1.17.1
* charset-normalizer==3.3.2
* cryptography==43.0.1
* idna==3.10
* lxml==5.3.0
* pycparser==2.22
* PyJWT==2.9.0
* pytz==2024.2
* requests==2.32.3
* urllib3==2.2.3
* xmljson==0.2.1

These can all be installed by running `pip install -r requirements.txt`.

Once installed, the script itself is run by this command: `python main.py`.

### Configuration
-----------------------------
Prior to using the script, it must be configured to connect to your Device42 instance and your Freshservice instance.
* Save a copy of mapping.xml.sample as mapping.xml. 
* In the config.ini file enter your URL, User, Password in the Device42 section
* In the config.ini file enter your URL, API Key, default approver email address (optional) in the Freshservice section; API Key can be obtained from Freshservice profile page

in the mapping.xml, you’ll see a Tasks section. 
Multiple Tasks can be setup to synchronize various CIs from Device42 to Freshservice.
In the <api> section of each task, there will be a <resource> section that queries Device42 to obtain the desired CIs. 
Full documentation of the Device42 API and endpoints is available at https://api.device42.com. 
Individual tasks within a mapping.xml file can be enabled or disabled at will by changing the `enable="true"` to `enable="false"` in the <task> section.

Once the Device42 API resource and Freshservice Target are entered, the <mapping> section is where fields from Device42 (the `resource` value) can be mapped to fields in Freshservice (the `target` value).
It is very important to adjust the list of default values in accordance between freshservice and device 42 (for example, service_level).

After configuring the fields to map as needed, the script should be ready to run. 

### Gotchas
-----------------------------
* Freshservice API Limit is 1000 calls per hour (https://api.freshservice.com/#ratelimit)
* Due to the nature of Freshservice rate limits, large inventories may take extended periods of time to migrate

Please use the following table as a reference only, actual times may vary due to request limit cooldowns and other internal API calls

|# of Devices| Migration Time|
|------------|---------------|
| 100   | 6 min |
| 1,000 | 1 hr |
| 5,000 | 5 hrs | 
|10,000 | 10 hrs |
|24,000 | 24 hrs |


### Compatibility
-----------------------------
* Script runs on Linux and Windows

### Info
-----------------------------
* mapping.xml - file from where we get fields relations between D42 and Freshservice
* mapping.xsd - file used to validate xml file
* device42.py - file with integration device42 instance
* freshservice.py - file with integration freshservice instance
* integration.py - initialization and processing file, where we prepare API calls

### Support
-----------------------------
We will support any issues you run into with the script and help answer any questions you have. Please reach out to us at support@device42.com

### Version
-----------------------------
3.0.0.11172024