#!/usr/bin/python
# -*- coding: utf-8 -*-

# This file is part of Ansible
#
# Ansible is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Ansible is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ansible.  If not, see <http://www.gnu.org/licenses/>.
DOCUMENTATION = '''
---
module: digital_ocean_tag
short_description: Create and remove tag(s) to DigitalOcean resource.
description:
    - Create and remove tag(s) to DigitalOcean resource.
version_added: "2.2"
options:
  name:
    description:
     - The name of the tag. The supported characters for names include
       alphanumeric characters, dashes, and underscores.
  resource_id:
    description:
    - The ID of the resource to operate on.
  resource_type:
    description:
    - The type of resource to operate on. Currently only tagging of
      droplets is supported.
    default: droplet
    choices: ['droplet']
  state:
    description:
     - Whether the tag should be present or absent on the resource.
    default: present
    choices: ['present', 'absent']
  api_token:
    description:
     - DigitalOcean api token.

notes:
  - Two environment variables can be used, DO_API_KEY and DO_API_TOKEN.
    They both refer to the v2 token.
  - As of Ansible 2.0, Version 2 of the DigitalOcean API is used.

requirements:
  - "python >= 2.6"
  - requests
'''


EXAMPLES = '''
- name: create a tag
  digital_ocean_tag:
    name: production
    state: present

- name: tag a resource; creating the tag if it does not exists
  digital_ocean_tag:
    name: "{{ item }}"
    resource_id: YYY
    state: present
  with_items:
    - staging
    - dbserver

- name: untag a resource
  digital_ocean_tag:
    name: staging
    resource_id: YYY
    state: absent

# Deleting a tag also untags all the resources that have previously been
# tagged with it
- name: remove a tag
  digital_ocean_tag:
    name: dbserver
    state: absent
'''


RETURN = '''
data:
    description: a DigitalOcean Tag resource
    returned: success and no resource constraint
    type: dict
    sample: {
        "tag": {
        "name": "awesome",
        "resources": {
          "droplets": {
            "count": 0,
            "last_tagged": null
          }
        }
      }
    }
'''

import json

HAS_REQUESTS = True
try:
    import requests
except ImportError:
    HAS_REQUESTS = False

api_base = 'https://api.digitalocean.com/v2'


def core(module):
    try:
        api_token = module.params['api_token'] or \
                os.environ['DO_API_TOKEN'] or os.environ['DO_API_KEY']
    except KeyError as e:
        module.fail_json(msg='Unable to load %s' % e.message)

    state = module.params['state']
    name = module.params['name']
    resource_id = module.params['resource_id']
    resource_type = module.params['resource_type']

    headers = {'Authorization': 'Bearer {}'.format(api_token),
               'Content-type': 'application/json'}

    if state in ('present'):
        if name is None:
            module.fail_json(msg='parameter `name` is missing')

        # Ensure Tag exists
        url = "{}/tags".format(api_base)
        payload = {'name': name}
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        if response.status_code == 201:
            changed = True
        elif response.status_code == 422:
            changed = False
        else:
            response.raise_for_status()

        # No resource defined, we're done.
        if resource_id is None:
            module.exit_json(changed=changed, data=response.json())

        # Tag a resource
        url = "{}/tags/{}/resources".format(api_base, name)
        payload = {
            'resources': [{
                'resource_id': resource_id,
                'resource_type': resource_type}]}
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        if response.status_code == 204:
            module.exit_json(changed=True)
        response.raise_for_status()

    elif state in ('absent'):
        if name is None:
            module.fail_json(msg='parameter `name` is missing')

        if resource_id:
            url = "{}/tags/{}/resources".format(api_base, name)
            payload = {
                'resources': [{
                    'resource_id': resource_id,
                    'resource_type': resource_type}]}
            response = requests.delete(url, headers=headers,
                    data=json.dumps(payload))
        else:
            url = "{}/tags/{}".format(api_base, name)
            response = requests.delete(url, headers=headers)
        if response.status_code == 204:
            module.exit_json(changed=True)
        response.raise_for_status()


def main():
    module = AnsibleModule(
        argument_spec=dict(
            name=dict(type='str'),
            resource_id=dict(aliases=['droplet_id'], type='int'),
            resource_type=dict(choices=['droplet'], default='droplet'),
            state=dict(choices=['present', 'absent'], default='present'),
            api_token=dict(aliases=['API_TOKEN'], no_log=True),
        ),
        required_one_of=(['name', 'state'],),
    )
    if not HAS_REQUESTS:
        module.fail_json(msg='requests required for this module')

    try:
        core(module)
    except Exception as e:
        module.fail_json(msg=str(e))

# import module snippets
from ansible.module_utils.basic import *  # noqa
if __name__ == '__main__':
    main()
