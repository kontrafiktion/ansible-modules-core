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
module: do_droplet
short_description: Create/delete a droplet in DigitalOcean
description:
     - Create/delete a droplet in DigitalOcean and optionally wait for it to be 'running'.
version_added: "2.2.0"
author: "Vincent Viallet (@zbal), Victor Volle (@kontrafiktion)"
options:
  state:
    description:
     - Indicate desired state of the target.
    default: present
    choices: ['present', 'active', 'absent', 'deleted']
  api_token:
    description:
     - DigitalOcean api token.
  id:
    description:
     - Numeric, the droplet id you want to operate on.
  name:
    description:
     - String, this is the name of the droplet - must be formatted by hostname rules.
  unique_name:
    description:
     - Bool, require unique hostnames.  By default, DigitalOcean allows multiple hosts with the same
       name. Setting this to "yes" allows only one host per name.  Useful for idempotence.
    default: "no"
    choices: [ "yes", "no" ]
  size:
    description:
     - This is the size you would like the droplet created with. (e.g. "2gb")
  image:
    description:
     - This is the image you would like the droplet created with (e.g. "ubuntu-14-04-x64").
  region:
    description:
     - This is the region you would like your server to be created in (e.g. "ams2").
  ssh_key_ids:
    description:
     - Optional, array of of SSH key (numeric) ID that you would like to be added to the server.
  virtio:
    description:
     - "Bool, turn on virtio driver in droplet for improved network and storage I/O."
    default: "yes"
    choices: [ "yes", "no" ]
  private_networking:
    description:
     - "Bool, add an additional, private network interface to droplet for inter-droplet communication."
    default: "no"
    choices: [ "yes", "no" ]
  backups_enabled:
    description:
     - Optional, Boolean, enables backups for your droplet.
    default: "no"
    choices: [ "yes", "no" ]
  user_data:
    description:
      - opaque blob of data which is made available to the droplet
    required: false
    default: None
  wait:
    description:
     - Wait for the droplet to be in state 'running' before returning.  If wait is "no" an ip_address may not be
       returned.
    default: "yes"
    choices: [ "yes", "no" ]
  wait_timeout:
    description:
     - How long before wait gives up, in seconds.
    default: 300

notes:
  - Two environment variables can be used, DO_API_KEY and DO_API_TOKEN. They both refer to the v2 token.
requirements:
  - "python >= 2.6"
'''


EXAMPLES = '''

# Create a new Droplet
# Will return the droplet details including the droplet id (used for idempotence)

- do_droplet:
    state: present
    name: mydroplet
    api_token: XXX
    size: 2gb
    region: ams2
    image: fedora-19-x64
    wait_timeout: 500

  register: my_droplet

- debug: msg="ID is {{ my_droplet.droplet.id }}"
- debug: msg="IP is {{ my_droplet.droplet.ip_address }}"

# Ensure a droplet is present
# If droplet id already exist, will return the droplet details and changed = False
# If no droplet matches the id, a new droplet will be created and the droplet details (including the new id) are
# returned, changed = True.

- do_droplet:
    state: present
    id: 123
    name: mydroplet
    api_token: XXX
    size: 2gb
    region: ams2
    image: fedora-19-x64
    wait_timeout: 500

# Create a droplet with ssh key
# The ssh key id can be passed as argument at the creation of a droplet (see ssh_key_ids).
# Several keys can be added to ssh_key_ids as id1,id2,id3
# The keys are used to connect as root to the droplet.

- do_droplet:
    state: present
    ssh_key_ids: 123,456
    name: mydroplet
    api_token: XXX
    size: 2gb
    region: ams2
    image: fedora-19-x64

'''

import os
import q
import time


class TimeoutError(Exception):

    def __init__(self, msg, id):
        super(TimeoutError, self).__init__(msg)
        self.id = id


class JsonfyMixIn(object):

    def to_json(self):
        return self.__dict__


class Response(object):

    def __init__(self, resp, info):
        self.body = None
        if resp:
            self.body = resp.read()
        self.info = info

    @property
    def json(self):
        if not self.body:
            # In some error cases fetch_url reads the body and places it in the info!
            if "body" in self.info:
                return json.loads(self.info["body"])
            return None
        try:
            return json.loads(self.body)
        except ValueError as e:
            return None

    @property
    def status_code(self):
        return self.info["status"]


class Rest(object):

    def __init__(self, module, api_token):
        self.module = module
        self.headers = {'Authorization': 'Bearer {}'.format(api_token), 'Content-type': 'application/json'}
        self.baseurl = 'https://api.digitalocean.com/v2'

    def _url_builder(self, path):
        if path[0] == '/':
            path = path[1:]
        return '%s/%s' % (self.baseurl, path)

    def send(self, method, path, data=None, headers=None):
        url = self._url_builder(path)
        data = self.module.jsonify(data)

        resp, info = fetch_url(self.module, url, data=data, headers=self.headers, method=method)
        return Response(resp, info)


class Droplet(JsonfyMixIn):
    module = None
    api_token = None

    def __init__(self, droplet_json):
        q("__init__", droplet_json)
        self.status = 'new'
        self.__dict__.update(droplet_json)

    def is_powered_on(self):
        return self.status == 'active'

    def update_attr(self, attrs=None):
        if attrs:
            for k, v in attrs.iteritems():
                setattr(self, k, v)
        else:
            json = Droplet._show_droplet(self.id)
            q("x", json)
            if json['ip_address']:
                self.update_attr(json)

    @classmethod
    def _populate_droplet_ips(cls, droplet):
        droplet[u'ip_address'] = ''
        for networkIndex in range(len(droplet['networks']['v4'])):
            network = droplet['networks']['v4'][networkIndex]
            if network['type'] == 'public':
                droplet[u'ip_address'] = network['ip_address']
            if network['type'] == 'private':
                droplet[u'private_ip_address'] = network['ip_address']

    @classmethod
    def _show_droplet(cls, id):
        rest = Rest(cls.module, cls.api_token)
        response = rest.send("GET", "/droplets/%s".format(id))
        # TODO: error handling
        droplet = response.json["droplet"]
        q("show", droplet)
        Droplet._populate_droplet_ips(droplet)
        q("show", droplet['ip_address'])
        return droplet


    # @classmethod
    # def _new_droplet(cls, name, size, image, region, ssh_key_ids, virtio,
    #                  private_networking_lower, backups_enabled_lower, user_data):
    #     rest = Rest(cls.module, cls.api_token)
    #     data = {"name": name, "size": size, "image": image, "region": region,
    #             "ssh_key_ids": ssh_key_ids, "virtio": virtio,
    #             "private_networking_lower": private_networking_lower,
    #             "backups_enabled_lower": backups_enabled_lower, "user_data": user_data}

    #     response = rest.send("POST", '/droplets', data=data)
    #     if "droplet" not in response.json:
    #         return response.
    #     return response.json["droplet"]

    @classmethod
    def _power_on_droplet(cls, id):
        pass

    @classmethod
    def _destroy_droplet(cls, id):
        pass

    @classmethod
    def _all_active_droplets(cls):
        rest = Rest(cls.module, cls.api_token)
        response = rest.send("GET", "/droplets?per_page=2")
        # TODO: error handling
        if "droplets" in response.json:
            q(response.json["droplets"])
            if "links" in response.json:
                print("LINKS:", response.json["links"])
        return response.json["droplets"]

    def power_on(self):
        assert self.status == 'off', 'Can only power on a closed one.'
        json = Droplet._power_on_droplet(self.id)
        self.update_attr(json)

    def ensure_powered_on(self, wait=True, wait_timeout=300):
        if self.is_powered_on():
            return
        if self.status == 'off':  # powered off
            self.power_on()

        if wait:
            end_time = time.time() + wait_timeout
            while time.time() < end_time:
                time.sleep(min(20, end_time - time.time()))
                self.update_attr()
                if self.is_powered_on():
                    if not self.ip_address:
                        raise TimeoutError('No ip is found.', self.id)
                    return
            raise TimeoutError('Wait for droplet running timeout', self.id)

    def destroy(self):
        return Droplet._destroy_droplet(self.id, scrub_data=True)

    @classmethod
    def setup(cls, module, api_token):
        cls.module = module
        cls.api_token = api_token

    @classmethod
    def add(cls, name, size, image, region, ssh_key_ids=None, virtio=True, private_networking=False,
            backups_enabled=False, user_data=None):

        rest = Rest(cls.module, cls.api_token)
        data = {"name": name, "size": size, "image": image, "region": region,
                "ssh_key_ids": ssh_key_ids, "virtio": virtio,
                "private_networking_lower": str(private_networking).lower(),
                "backups_enabled_lower": str(backups_enabled).lower(), 
                "user_data": user_data}

        response = rest.send("POST", '/droplets', data=data)
        if "droplet" not in response.json:
            pass # TODO
        return response.json["droplet"]

    @classmethod
    def find(cls, id=None, name=None):
        if not id and not name:
            return False

        droplets = cls.list_all()

        # Check first by id.  digital ocean requires that it be unique
        for droplet in droplets:
            if droplet.id == id:
                return droplet

        # Failing that, check by hostname.
        for droplet in droplets:
            if droplet.name == name:
                return droplet

        return False

    @classmethod
    def list_all(cls):
        json = cls._all_active_droplets()
        return map(cls, json)


def core(module):
    def getkeyordie(k):
        v = module.params[k]
        if v is None:
            module.fail_json(msg='Unable to load %s' % k)
        return v

    try:
        api_token = module.params['api_token'] or os.environ['DO_API_TOKEN'] or os.environ['DO_API_KEY']
    except KeyError as e:
        module.fail_json(msg='Unable to load %s' % e.message)

    changed = True
    state = module.params['state']

    Droplet.setup(module, api_token)
    if state in ('active', 'present'):

        # First, try to find a droplet by id.
        droplet = Droplet.find(id=module.params['id'])

        # If we couldn't find the droplet and the user is allowing unique
        # hostnames, then check to see if a droplet with the specified
        # hostname already exists.
        if not droplet and module.params['unique_name']:
            droplet = Droplet.find(name=getkeyordie('name'))

        # If both of those attempts failed, then create a new droplet.
        if not droplet:
            droplet = Droplet.add(
                name=getkeyordie('name'),
                size=getkeyordie('size'),
                image=getkeyordie('image'),
                region=getkeyordie('region'),
                ssh_key_ids=module.params['ssh_key_ids'],
                virtio=module.params['virtio'],
                private_networking=module.params['private_networking'],
                backups_enabled=module.params['backups_enabled'],
                user_data=module.params.get('user_data'),
            )

        if droplet.is_powered_on():
            changed = False

        droplet.ensure_powered_on(
            wait=getkeyordie('wait'),
            wait_timeout=getkeyordie('wait_timeout')
        )

        module.exit_json(changed=changed, droplet=droplet.to_json())

    elif state in ('absent', 'deleted'):
        # First, try to find a droplet by id.
        droplet = Droplet.find(module.params['id'])

        # If we couldn't find the droplet and the user is allowing unique
        # hostnames, then check to see if a droplet with the specified
        # hostname already exists.
        if not droplet and module.params['unique_name']:
            droplet = Droplet.find(name=getkeyordie('name'))

        if not droplet:
            module.exit_json(changed=False, msg='The droplet is not found.')

        event_json = droplet.destroy()
        module.exit_json(changed=True)
    elif state in ('debug'):
        x = Droplet._all_active_droplets()
        q(x)
        module.exit_json(changed=True, response=x)


def main():
    module = AnsibleModule(
        argument_spec=dict(
            state=dict(choices=['active', 'present', 'absent', 'deleted', 'debug'], default='present'),
            api_token=dict(aliases=['API_TOKEN'], no_log=True),
            name=dict(type='str'),
            size=dict(aliases=['size_id']),
            image=dict(aliases=['image_id']),
            region=dict(aliases=['region_id']),
            ssh_key_ids=dict(type='list'),
            virtio=dict(type='bool', default='yes'),
            private_networking=dict(type='bool', default='no'),
            backups_enabled=dict(type='bool', default='no'),
            id=dict(aliases=['droplet_id'], type='int'),
            unique_name=dict(type='bool', default='no'),
            user_data=dict(default=None),
            wait=dict(type='bool', default=True),
            wait_timeout=dict(default=300, type='int'),
        ),
        required_together=(
            ['size', 'image', 'region'],
        ),
        required_one_of=(
            ['id', 'name'],
        ),
    )

    try:
        core(module)
    except TimeoutError as e:
        module.fail_json(msg=str(e), id=e.id)

# import module snippets
from ansible.module_utils.basic import *
from ansible.module_utils.urls import *

if __name__ == '__main__':
    main()
