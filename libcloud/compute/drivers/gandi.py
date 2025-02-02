# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
Gandi driver for compute
"""
from datetime import datetime

from libcloud.common.gandi import (
    BaseGandiDriver,
    GandiException,
    NetworkInterface,
    IPAddress,
    Disk,
)
from libcloud.compute.base import KeyPair
from libcloud.compute.base import StorageVolume
from libcloud.compute.types import NodeState, Provider
from libcloud.compute.base import Node, NodeDriver
from libcloud.compute.base import NodeSize, NodeImage, NodeLocation


NODE_STATE_MAP = {
    "running": NodeState.RUNNING,
    "halted": NodeState.TERMINATED,
    "paused": NodeState.TERMINATED,
    "locked": NodeState.TERMINATED,
    "being_created": NodeState.PENDING,
    "invalid": NodeState.UNKNOWN,
    "legally_locked": NodeState.PENDING,
    "deleted": NodeState.TERMINATED,
}

NODE_PRICE_HOURLY_USD = 0.02

INSTANCE_TYPES = {
    "small": {
        "id": "small",
        "name": "Small instance",
        "cpu": 1,
        "memory": 256,
        "disk": 3,
        "bandwidth": 10240,
    },
    "medium": {
        "id": "medium",
        "name": "Medium instance",
        "cpu": 1,
        "memory": 1024,
        "disk": 20,
        "bandwidth": 10240,
    },
    "large": {
        "id": "large",
        "name": "Large instance",
        "cpu": 2,
        "memory": 2048,
        "disk": 50,
        "bandwidth": 10240,
    },
    "x-large": {
        "id": "x-large",
        "name": "Extra Large instance",
        "cpu": 4,
        "memory": 4096,
        "disk": 100,
        "bandwidth": 10240,
    },
}


class GandiNodeDriver(BaseGandiDriver, NodeDriver):
    """
    Gandi node driver

    """

    api_name = "gandi"
    friendly_name = "Gandi.net"
    website = "http://www.gandi.net/"
    country = "FR"
    type = Provider.GANDI
    # TODO : which features to enable ?
    features = {}

    def __init__(self, *args, **kwargs):
        """
        @inherits: :class:`NodeDriver.__init__`
        """
        super(GandiNodeDriver, self).__init__(*args, **kwargs)

    def _resource_info(self, type, id):
        try:
            obj = self.connection.request("hosting.%s.info" % type, int(id))
            return obj.object
        except Exception as e:
            raise GandiException(1003, e)

    def _node_info(self, id):
        return self._resource_info("vm", id)

    def _volume_info(self, id):
        return self._resource_info("disk", id)

    # Generic methods for driver
    def _to_node(self, vm):
        return Node(
            id=vm["id"],
            name=vm["hostname"],
            state=NODE_STATE_MAP.get(vm["state"], NodeState.UNKNOWN),
            public_ips=vm.get("ips", []),
            private_ips=[],
            driver=self,
            extra={
                "ai_active": vm.get("ai_active"),
                "datacenter_id": vm.get("datacenter_id"),
                "description": vm.get("description"),
            },
        )

    def _to_nodes(self, vms):
        return [self._to_node(v) for v in vms]

    def _to_volume(self, disk):
        extra = {"can_snapshot": disk["can_snapshot"]}
        return StorageVolume(
            id=disk["id"],
            name=disk["name"],
            size=int(disk["size"]),
            driver=self,
            extra=extra,
        )

    def _to_volumes(self, disks):
        return [self._to_volume(d) for d in disks]

    def list_nodes(self):
        """
        Return a list of nodes in the current zone or all zones.

        :return:  List of Node objects
        :rtype:   ``list`` of :class:`Node`
        """
        vms = self.connection.request("hosting.vm.list").object
        ips = self.connection.request("hosting.ip.list").object
        for vm in vms:
            vm["ips"] = []
            for ip in ips:
                if vm["ifaces_id"][0] == ip["iface_id"]:
                    ip = ip.get("ip", None)
                    if ip:
                        vm["ips"].append(ip)

        nodes = self._to_nodes(vms)
        return nodes

    def ex_get_node(self, node_id):
        """
        Return a Node object based on a node id.

        :param  name: The ID of the node
        :type   name: ``int``

        :return:  A Node object for the node
        :rtype:   :class:`Node`
        """
        vm = self.connection.request("hosting.vm.info", int(node_id)).object
        ips = self.connection.request("hosting.ip.list").object
        vm["ips"] = []
        for ip in ips:
            if vm["ifaces_id"][0] == ip["iface_id"]:
                ip = ip.get("ip", None)
                if ip:
                    vm["ips"].append(ip)
        node = self._to_node(vm)
        return node

    def reboot_node(self, node):
        """
        Reboot a node.

        :param  node: Node to be rebooted
        :type   node: :class:`Node`

        :return:  True if successful, False if not
        :rtype:   ``bool``
        """
        op = self.connection.request("hosting.vm.reboot", int(node.id))
        self._wait_operation(op.object["id"])
        vm = self._node_info(int(node.id))
        if vm["state"] == "running":
            return True
        return False

    def destroy_node(self, node):
        """
        Destroy a node.

        :param  node: Node object to destroy
        :type   node: :class:`Node`

        :return:  True if successful
        :rtype:   ``bool``
        """
        vm = self._node_info(node.id)
        if vm["state"] == "running":
            # Send vm_stop and wait for accomplish
            op_stop = self.connection.request("hosting.vm.stop", int(node.id))
            if not self._wait_operation(op_stop.object["id"]):
                raise GandiException(1010, "vm.stop failed")
            # Delete
        op = self.connection.request("hosting.vm.delete", int(node.id))
        if self._wait_operation(op.object["id"]):
            return True
        return False

    def deploy_node(self, **kwargs):
        """
        deploy_node is not implemented for gandi driver

        :rtype: ``bool``
        """
        raise NotImplementedError("deploy_node not implemented for gandi driver")

    def create_node(
        self,
        name,
        size,
        image,
        location=None,
        login=None,
        password=None,
        inet_family=4,
        keypairs=None,
    ):
        """
        Create a new Gandi node

        :keyword    name:   String with a name for this new node (required)
        :type       name:   ``str``

        :keyword    image:  OS Image to boot on node. (required)
        :type       image:  :class:`NodeImage`

        :keyword    location: Which data center to create a node in. If empty,
                              undefined behavior will be selected. (optional)
        :type       location: :class:`NodeLocation`

        :keyword    size:   The size of resources allocated to this node.
                            (required)
        :type       size:   :class:`NodeSize`

        :keyword    login: user name to create for login on machine (required)
        :type       login: ``str``

        :keyword    password: password for user that'll be created (required)
        :type       password: ``str``

        :keyword    inet_family: version of ip to use, default 4 (optional)
        :type       inet_family: ``int``

        :keyword    keypairs: IDs of keypairs or Keypairs object
        :type       keypairs: list of ``int`` or :class:`.KeyPair`

        :rtype: :class:`Node`
        """
        keypairs = keypairs or []

        if not login and not keypairs:
            raise GandiException(
                1020,
                "Login and password or ssh keypair "
                "must be defined for node creation",
            )

        if location and isinstance(location, NodeLocation):
            dc_id = int(location.id)
        else:
            raise GandiException(1021, "location must be a subclass of NodeLocation")

        if not size and not isinstance(size, NodeSize):
            raise GandiException(1022, "size must be a subclass of NodeSize")

        keypair_ids = [k if isinstance(k, int) else k.extra["id"] for k in keypairs]

        # If size name is in INSTANCE_TYPE we use new rating model
        instance = INSTANCE_TYPES.get(size.id)
        cores = instance["cpu"] if instance else int(size.id)

        src_disk_id = int(image.id)

        disk_spec = {"datacenter_id": dc_id, "name": "disk_%s" % name}

        vm_spec = {
            "datacenter_id": dc_id,
            "hostname": name,
            "memory": int(size.ram),
            "cores": cores,
            "bandwidth": int(size.bandwidth),
            "ip_version": inet_family,
        }

        if login and password:
            vm_spec.update(
                {"login": login, "password": password}  # TODO : use NodeAuthPassword
            )
        if keypair_ids:
            vm_spec["keys"] = keypair_ids

        # Call create_from helper api. Return 3 operations : disk_create,
        # iface_create,vm_create
        (op_disk, op_iface, op_vm) = self.connection.request(
            "hosting.vm.create_from", vm_spec, disk_spec, src_disk_id
        ).object

        # We wait for vm_create to finish
        if self._wait_operation(op_vm["id"]):
            # after successful operation, get ip information
            # thru first interface
            node = self._node_info(op_vm["vm_id"])
            ifaces = node.get("ifaces")
            if len(ifaces) > 0:
                ips = ifaces[0].get("ips")
                if len(ips) > 0:
                    node["ip"] = ips[0]["ip"]
            return self._to_node(node)

        return None

    def _to_image(self, img):
        return NodeImage(
            id=img["disk_id"], name=img["label"], driver=self.connection.driver
        )

    def list_images(self, location=None):
        """
        Return a list of image objects.

        :keyword    location: Which data center to filter a images in.
        :type       location: :class:`NodeLocation`

        :return:  List of GCENodeImage objects
        :rtype:   ``list`` of :class:`GCENodeImage`
        """
        try:
            if location:
                filtering = {"datacenter_id": int(location.id)}
            else:
                filtering = {}
            images = self.connection.request("hosting.image.list", filtering)
            return [self._to_image(i) for i in images.object]
        except Exception as e:
            raise GandiException(1011, e)

    def _to_size(self, id, size):
        return NodeSize(
            id=id,
            name="%s cores" % id,
            ram=size["memory"],
            disk=size["disk"],
            bandwidth=size["bandwidth"],
            price=(self._get_size_price(size_id="1") * id),
            driver=self.connection.driver,
        )

    def _instance_type_to_size(self, instance):
        return NodeSize(
            id=instance["id"],
            name=instance["name"],
            ram=instance["memory"],
            disk=instance["disk"],
            bandwidth=instance["bandwidth"],
            price=self._get_size_price(size_id=instance["id"]),
            driver=self.connection.driver,
        )

    def list_instance_type(self, location=None):
        return [
            self._instance_type_to_size(instance)
            for name, instance in INSTANCE_TYPES.items()
        ]

    def list_sizes(self, location=None):
        """
        Return a list of sizes (machineTypes) in a zone.

        :keyword  location: Which data center to filter a sizes in.
        :type     location: :class:`NodeLocation` or ``None``

        :return:  List of NodeSize objects
        :rtype:   ``list`` of :class:`NodeSize`
        """
        account = self.connection.request("hosting.account.info").object
        if account.get("rating_enabled"):
            # This account use new rating model
            return self.list_instance_type(location)
        # Look for available shares, and return a list of share_definition
        available_res = account["resources"]["available"]

        if available_res["shares"] == 0:
            return None
        else:
            share_def = account["share_definition"]
            available_cores = available_res["cores"]
            # 0.75 core given when creating a server
            max_core = int(available_cores + 0.75)
            shares = []
            if available_res["servers"] < 1:
                # No server quota, no way
                return shares
            for i in range(1, max_core + 1):
                share = {id: i}
                share_is_available = True
                for k in ["memory", "disk", "bandwidth"]:
                    if share_def[k] * i > available_res[k]:
                        # We run out for at least one resource inside
                        share_is_available = False
                    else:
                        share[k] = share_def[k] * i
                if share_is_available:
                    nb_core = i
                    shares.append(self._to_size(nb_core, share))
            return shares

    def _to_loc(self, loc):
        return NodeLocation(
            id=loc["id"], name=loc["dc_code"], country=loc["country"], driver=self
        )

    def list_locations(self):
        """
        Return a list of locations (datacenters).

        :return: List of NodeLocation objects
        :rtype: ``list`` of :class:`NodeLocation`
        """
        res = self.connection.request("hosting.datacenter.list")
        return [self._to_loc(loc) for loc in res.object]

    def list_volumes(self):
        """
        Return a list of volumes.

        :return: A list of volume objects.
        :rtype: ``list`` of :class:`StorageVolume`
        """
        res = self.connection.request("hosting.disk.list", {})
        return self._to_volumes(res.object)

    def ex_get_volume(self, volume_id):
        """
        Return a Volume object based on a volume ID.

        :param  volume_id: The ID of the volume
        :type   volume_id: ``int``

        :return:  A StorageVolume object for the volume
        :rtype:   :class:`StorageVolume`
        """
        res = self.connection.request("hosting.disk.info", volume_id)
        return self._to_volume(res.object)

    def create_volume(self, size, name, location=None, snapshot=None):
        """
        Create a volume (disk).

        :param  size: Size of volume to create (in GB).
        :type   size: ``int``

        :param  name: Name of volume to create
        :type   name: ``str``

        :keyword  location: Location (zone) to create the volume in
        :type     location: :class:`NodeLocation` or ``None``

        :keyword  snapshot: Snapshot to create image from
        :type     snapshot: :class:`Snapshot`

        :return:  Storage Volume object
        :rtype:   :class:`StorageVolume`
        """
        disk_param = {
            "name": name,
            "size": int(size),
            "datacenter_id": int(location.id),
        }
        if snapshot:
            op = self.connection.request(
                "hosting.disk.create_from", disk_param, int(snapshot.id)
            )
        else:
            op = self.connection.request("hosting.disk.create", disk_param)
        if self._wait_operation(op.object["id"]):
            disk = self._volume_info(op.object["disk_id"])
            return self._to_volume(disk)
        return None

    def attach_volume(self, node, volume, device=None):
        """
        Attach a volume to a node.

        :param  node: The node to attach the volume to
        :type   node: :class:`Node`

        :param  volume: The volume to attach.
        :type   volume: :class:`StorageVolume`

        :keyword  device: Not used in this cloud.
        :type     device: ``None``

        :return:  True if successful
        :rtype:   ``bool``
        """
        op = self.connection.request(
            "hosting.vm.disk_attach", int(node.id), int(volume.id)
        )
        if self._wait_operation(op.object["id"]):
            return True
        return False

    def detach_volume(self, node, volume):
        """
        Detaches a volume from a node.

        :param      node: Node which should be used
        :type       node: :class:`Node`

        :param      volume: Volume to be detached
        :type       volume: :class:`StorageVolume`

        :rtype: ``bool``
        """
        op = self.connection.request(
            "hosting.vm.disk_detach", int(node.id), int(volume.id)
        )
        if self._wait_operation(op.object["id"]):
            return True
        return False

    def destroy_volume(self, volume):
        """
        Destroy a volume.

        :param  volume: Volume object to destroy
        :type   volume: :class:`StorageVolume`

        :return:  True if successful
        :rtype:   ``bool``
        """
        op = self.connection.request("hosting.disk.delete", int(volume.id))
        if self._wait_operation(op.object["id"]):
            return True
        return False

    def _to_iface(self, iface):
        ips = []
        for ip in iface.get("ips", []):
            new_ip = IPAddress(
                ip["id"],
                NODE_STATE_MAP.get(ip["state"], NodeState.UNKNOWN),
                ip["ip"],
                self.connection.driver,
                version=ip.get("version"),
                extra={"reverse": ip["reverse"]},
            )
            ips.append(new_ip)
        return NetworkInterface(
            iface["id"],
            NODE_STATE_MAP.get(iface["state"], NodeState.UNKNOWN),
            mac_address=None,
            driver=self.connection.driver,
            ips=ips,
            node_id=iface.get("vm_id"),
            extra={"bandwidth": iface["bandwidth"]},
        )

    def _to_ifaces(self, ifaces):
        return [self._to_iface(i) for i in ifaces]

    def ex_list_interfaces(self):
        """
        Specific method to list network interfaces

        :rtype: ``list`` of :class:`GandiNetworkInterface`
        """
        ifaces = self.connection.request("hosting.iface.list").object
        ips = self.connection.request("hosting.ip.list").object
        for iface in ifaces:
            iface["ips"] = list(filter(lambda i: i["iface_id"] == iface["id"], ips))
        return self._to_ifaces(ifaces)

    def _to_disk(self, element):
        disk = Disk(
            id=element["id"],
            state=NODE_STATE_MAP.get(element["state"], NodeState.UNKNOWN),
            name=element["name"],
            driver=self.connection.driver,
            size=element["size"],
            extra={"can_snapshot": element["can_snapshot"]},
        )
        return disk

    def _to_disks(self, elements):
        return [self._to_disk(el) for el in elements]

    def ex_list_disks(self):
        """
        Specific method to list all disk

        :rtype: ``list`` of :class:`GandiDisk`
        """
        res = self.connection.request("hosting.disk.list", {})
        return self._to_disks(res.object)

    def ex_node_attach_disk(self, node, disk):
        """
        Specific method to attach a disk to a node

        :param      node: Node which should be used
        :type       node: :class:`Node`

        :param      disk: Disk which should be used
        :type       disk: :class:`GandiDisk`

        :rtype: ``bool``
        """
        op = self.connection.request(
            "hosting.vm.disk_attach", int(node.id), int(disk.id)
        )
        if self._wait_operation(op.object["id"]):
            return True
        return False

    def ex_node_detach_disk(self, node, disk):
        """
        Specific method to detach a disk from a node

        :param      node: Node which should be used
        :type       node: :class:`Node`

        :param      disk: Disk which should be used
        :type       disk: :class:`GandiDisk`

        :rtype: ``bool``
        """
        op = self.connection.request(
            "hosting.vm.disk_detach", int(node.id), int(disk.id)
        )
        if self._wait_operation(op.object["id"]):
            return True
        return False

    def ex_node_attach_interface(self, node, iface):
        """
        Specific method to attach an interface to a node

        :param      node: Node which should be used
        :type       node: :class:`Node`

        :param      iface: Network interface which should be used
        :type       iface: :class:`GandiNetworkInterface`

        :rtype: ``bool``
        """
        op = self.connection.request(
            "hosting.vm.iface_attach", int(node.id), int(iface.id)
        )
        if self._wait_operation(op.object["id"]):
            return True
        return False

    def ex_node_detach_interface(self, node, iface):
        """
        Specific method to detach an interface from a node

        :param      node: Node which should be used
        :type       node: :class:`Node`

        :param      iface: Network interface which should be used
        :type       iface: :class:`GandiNetworkInterface`

        :rtype: ``bool``
        """
        op = self.connection.request(
            "hosting.vm.iface_detach", int(node.id), int(iface.id)
        )
        if self._wait_operation(op.object["id"]):
            return True
        return False

    def ex_snapshot_disk(self, disk, name=None):
        """
        Specific method to make a snapshot of a disk

        :param      disk: Disk which should be used
        :type       disk: :class:`GandiDisk`

        :param      name: Name which should be used
        :type       name: ``str``

        :rtype: ``bool``
        """
        if not disk.extra.get("can_snapshot"):
            raise GandiException(1021, "Disk %s can't snapshot" % disk.id)
        if not name:
            suffix = datetime.today().strftime("%Y%m%d")
            name = "snap_%s" % (suffix)
        op = self.connection.request(
            "hosting.disk.create_from",
            {"name": name, "type": "snapshot"},
            int(disk.id),
        )
        if self._wait_operation(op.object["id"]):
            return True
        return False

    def ex_update_disk(self, disk, new_size=None, new_name=None):
        """Specific method to update size or name of a disk
        WARNING: if a server is attached it'll be rebooted

        :param      disk: Disk which should be used
        :type       disk: :class:`GandiDisk`

        :param      new_size: New size
        :type       new_size: ``int``

        :param      new_name: New name
        :type       new_name: ``str``

        :rtype: ``bool``
        """
        params = {}
        if new_size:
            params.update({"size": new_size})
        if new_name:
            params.update({"name": new_name})
        op = self.connection.request("hosting.disk.update", int(disk.id), params)
        if self._wait_operation(op.object["id"]):
            return True
        return False

    def _to_key_pair(self, data):
        key_pair = KeyPair(
            name=data["name"],
            fingerprint=data["fingerprint"],
            public_key=data.get("value", None),
            private_key=data.get("privatekey", None),
            driver=self,
            extra={"id": data["id"]},
        )
        return key_pair

    def _to_key_pairs(self, data):
        return [self._to_key_pair(k) for k in data]

    def list_key_pairs(self):
        """
        List registered key pairs.

        :return:   A list of key par objects.
        :rtype:   ``list`` of :class:`libcloud.compute.base.KeyPair`
        """
        kps = self.connection.request("hosting.ssh.list").object
        return self._to_key_pairs(kps)

    def get_key_pair(self, name):
        """
        Retrieve a single key pair.

        :param name: Name of the key pair to retrieve.
        :type name: ``str``

        :rtype: :class:`.KeyPair`
        """
        filter_params = {"name": name}
        kps = self.connection.request("hosting.ssh.list", filter_params).object
        return self._to_key_pair(kps[0])

    def import_key_pair_from_string(self, name, key_material):
        """
        Create a new key pair object.

        :param name: Key pair name.
        :type name: ``str``

        :param key_material: Public key material.
        :type key_material: ``str``

        :return: Imported key pair object.
        :rtype: :class:`.KeyPair`
        """
        params = {"name": name, "value": key_material}
        kp = self.connection.request("hosting.ssh.create", params).object
        return self._to_key_pair(kp)

    def delete_key_pair(self, key_pair):
        """
        Delete an existing key pair.

        :param key_pair: Key pair object or ID.
        :type key_pair: :class.KeyPair` or ``int``

        :return:   True of False based on success of Keypair deletion
        :rtype:    ``bool``
        """
        key_id = key_pair if isinstance(key_pair, int) else key_pair.extra["id"]
        success = self.connection.request("hosting.ssh.delete", key_id).object
        return success
