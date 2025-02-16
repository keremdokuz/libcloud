# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance withv
# the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from libcloud.utils.py3 import ET
from libcloud.utils.xml import findall, findtext, fixxpath
from libcloud.utils.misc import reverse_dict
from libcloud.common.nttcis import (
    TYPES_URN,
    API_ENDPOINTS,
    DEFAULT_REGION,
    NttCisPool,
    NttCisVIPNode,
    NttCisConnection,
    NttCisPoolMember,
    NttCisDefaultiRule,
    NttCisVirtualListener,
    NttCisPersistenceProfile,
    NttCisDefaultHealthMonitor,
    NttCisVirtualListenerCompatibility,
    get_params,
    process_xml,
)
from libcloud.loadbalancer.base import DEFAULT_ALGORITHM, Driver, Member, Algorithm, LoadBalancer
from libcloud.loadbalancer.types import State, Provider


class NttCisLBDriver(Driver):
    """
    NttCis LB driver.
    """

    selected_region = None
    connectionCls = NttCisConnection
    name = "NTTC-CIS Load Balancer"
    website = "https://cloud.nttcis.com/"
    type = Provider.NTTCIS
    api_version = 1.0

    _VALUE_TO_ALGORITHM_MAP = {
        "ROUND_ROBIN": Algorithm.ROUND_ROBIN,
        "LEAST_CONNECTIONS_MEMBER": Algorithm.LEAST_CONNECTIONS_MEMBER,
        "LEAST_CONNECTIONS_NODE": Algorithm.LEAST_CONNECTIONS_NODE,
        "OBSERVED_MEMBER": Algorithm.OBSERVED_MEMBER,
        "OBSERVED_NODE": Algorithm.OBSERVED_NODE,
        "PREDICTIVE_MEMBER": Algorithm.PREDICTIVE_MEMBER,
        "PREDICTIVE_NODE": Algorithm.PREDICTIVE_NODE,
    }
    _ALGORITHM_TO_VALUE_MAP = reverse_dict(_VALUE_TO_ALGORITHM_MAP)

    _VALUE_TO_STATE_MAP = {
        "NORMAL": State.RUNNING,
        "PENDING_ADD": State.PENDING,
        "PENDING_CHANGE": State.PENDING,
        "PENDING_DELETE": State.PENDING,
        "FAILED_ADD": State.ERROR,
        "FAILED_CHANGE": State.ERROR,
        "FAILED_DELETE": State.ERROR,
        "REQUIRES_SUPPORT": State.ERROR,
    }

    def __init__(
        self,
        key,
        network_domain_id,
        secret=None,
        secure=True,
        host=None,
        port=None,
        api_version=None,
        region=DEFAULT_REGION,
        **kwargs,
    ):
        self.network_domain_id = network_domain_id

        if region not in API_ENDPOINTS and host is None:
            raise ValueError("Invalid region: %s, no host specified" % (region))
        if region is not None:
            self.selected_region = API_ENDPOINTS[region]

        super().__init__(
            key=key,
            secret=secret,
            secure=secure,
            host=host,
            port=port,
            api_version=api_version,
            region=region,
            **kwargs,
        )

    def _ex_connection_class_kwargs(self):
        """
        Add the region to the kwargs before the connection is instantiated
        """

        kwargs = super()._ex_connection_class_kwargs()
        kwargs["region"] = self.selected_region
        return kwargs

    def create_balancer(
        self,
        name,
        listener_port=None,
        port=None,
        protocol=None,
        algorithm=None,
        members=None,
        optimization_profile="TCP",
        ex_listener_ip_address=None,
    ):
        """

        Create a new load balancer instance

        :param name: Name of the new load balancer (required)
        :type  name: ``str``

        :param listener_port: An integer in the range of 1-65535.
                              If not supplied, it will be taken to
                              mean 'Any Port'
        :type  port: ``int

        :param port: An integer in the range of 1-65535. If not supplied,
                     it will be taken to mean 'Any Port'  Assumed that
                     node ports will different from listener port.
        :type  port: ``int``

        :param protocol: Loadbalancer protocol, defaults to http.
        :type  protocol: ``str``

        :param members: list of Members to attach to balancer (optional)
        :type  members: ``list`` of :class:`Member`

        :param algorithm: Load balancing algorithm, defaults to ROUND_ROBIN.
        :type algorithm: :class:`.Algorithm`

        :param optimization_profile: For STANDARD type and protocol TCP
                                     an optimization type of TCP, LAN_OPT,
                                     WAN_OPT, MOBILE_OPT, or TCP_LEGACY is
                                     required. Default is TCP
        :type  protocol: ``str``

        :param ex_listener_ip_address: Must be a valid IPv4 in dot-decimal
                                       notation (x.x.x.x).
        :type ex_listener_ip_address: ``str``

        :rtype: :class:`LoadBalancer`
        """

        network_domain_id = self.network_domain_id
        if protocol is None:
            protocol = "http"
        if algorithm is None:
            algorithm = DEFAULT_ALGORITHM

        # Create a pool first

        pool = self.ex_create_pool(
            network_domain_id=network_domain_id,
            name=name,
            ex_description=None,
            balancer_method=self._ALGORITHM_TO_VALUE_MAP[algorithm],
        )

        # Attach the members to the pool as nodes
        if members is not None:
            for member in members:
                if not isinstance(member, Member):
                    member = self.ex_create_node(
                        network_domain_id=network_domain_id,
                        name=member.name,
                        ip=member.private_ips[0],
                        ex_description=None,
                    )
                self.ex_create_pool_member(pool=pool, node=member, port=port)

        # Create the virtual listener (balancer)
        listener = self.ex_create_virtual_listener(
            network_domain_id=network_domain_id,
            name=name,
            ex_description=name,
            port=listener_port,
            pool=pool,
            protocol=protocol,
            optimization_profile=optimization_profile,
            listener_ip_address=ex_listener_ip_address,
        )

        return LoadBalancer(
            id=listener.id,
            name=listener.name,
            state=State.RUNNING,
            ip=listener.ip,
            port=port,
            driver=self,
            extra={
                "pool_id": pool.id,
                "network_domain_id": network_domain_id,
                "listener_ip_address": ex_listener_ip_address,
            },
        )

    def ex_update_listener(self, virtual_listener, **kwargs):
        """
        Update a current virtual listener.
        :param virtual_listener: The listener to be updated
        :return: The edited version of the listener
        """
        edit_listener_elm = ET.Element(
            "editVirtualListener",
            {
                "xmlns": TYPES_URN,
                "id": virtual_listener.id,
                "xmlns:xsi": "http://www.w3.org/2001/" "XMLSchema-instance",
            },
        )
        for k, v in kwargs.items():
            if v is None:
                ET.SubElement(edit_listener_elm, k, {"xsi:nil": "true"})
            else:
                ET.SubElement(edit_listener_elm, k).text = v

        result = self.connection.request_with_orgId_api_2(
            "networkDomainVip/editVirtualListener",
            method="POST",
            data=ET.tostring(edit_listener_elm),
        ).object
        response_code = findtext(result, "responseCode", TYPES_URN)
        return response_code in ["IN_PROGRESS", "OK"]

    def list_balancers(self, ex_network_domain_id=None):
        """
        List all loadbalancers inside a geography or in given network.

        In NTTC-CIS terminology these are known as virtual listeners

        :param ex_network_domain_id: UUID of Network Domain
               if not None returns only balancers in the given network
               if None then returns all pools for the organization
        :type  ex_network_domain_id: ``str``

        :rtype: ``list`` of :class:`LoadBalancer`
        """
        params = None
        if ex_network_domain_id is not None:
            params = {"networkDomainId": ex_network_domain_id}

        return self._to_balancers(
            self.connection.request_with_orgId_api_2(
                "networkDomainVip/virtualListener", params=params
            ).object
        )

    def get_balancer(self, balancer_id):
        """
        Return a :class:`LoadBalancer` object.

        :param balancer_id: id of a load balancer you want to fetch
        :type  balancer_id: ``str``

        :rtype: :class:`LoadBalancer`
        """

        bal = self.connection.request_with_orgId_api_2(
            "networkDomainVip/virtualListener/%s" % balancer_id
        ).object
        return self._to_balancer(bal)

    def list_protocols(self):
        """
        Return a list of supported protocols.

        Since all protocols are support by NTTC-CIS, this is a list
        of common protocols.

        :rtype: ``list`` of ``str``
        """
        return ["http", "https", "tcp", "udp", "ftp", "smtp"]

    def balancer_list_members(self, balancer):
        """
        Return list of members attached to balancer.

        In NTTC-CIS terminology these are the members of the pools
        within a virtual listener.

        :param balancer: LoadBalancer which should be used
        :type  balancer: :class:`LoadBalancer`

        :rtype: ``list`` of :class:`Member`
        """
        pool_members = self.ex_get_pool_members(balancer.extra["pool_id"])
        members = []
        for pool_member in pool_members:
            members.append(
                Member(
                    id=pool_member.id,
                    ip=pool_member.ip,
                    port=pool_member.port,
                    balancer=balancer,
                    extra=None,
                )
            )
        return members

    def balancer_attach_member(self, balancer, member):
        """
        Attach a member to balancer

        :param balancer: LoadBalancer which should be used
        :type  balancer: :class:`LoadBalancer`

        :param member: Member to join to the balancer
        :type member: :class:`Member`

        :return: Member after joining the balancer.
        :rtype: :class:`Member`
        """
        node = self.ex_create_node(
            network_domain_id=balancer.extra["network_domain_id"],
            name="Member." + member.ip,
            ip=member.ip,
            ex_description="",
        )
        if node is False:
            return False
        pool = self.ex_get_pool(balancer.extra["pool_id"])
        pool_member = self.ex_create_pool_member(pool=pool, node=node, port=member.port)
        member.id = pool_member.id
        return member

    def balancer_detach_member(self, balancer, member):
        """
        Detach member from balancer

        :param balancer: LoadBalancer which should be used
        :type  balancer: :class:`LoadBalancer`

        :param member: Member which should be used
        :type member: :class:`Member`

        :return: ``True`` if member detach was successful, otherwise ``False``.
        :rtype: ``bool``
        """
        create_pool_m = ET.Element("removePoolMember", {"xmlns": TYPES_URN, "id": member.id})

        result = self.connection.request_with_orgId_api_2(
            "networkDomainVip/removePoolMember",
            method="POST",
            data=ET.tostring(create_pool_m),
        ).object
        response_code = findtext(result, "responseCode", TYPES_URN)
        return response_code in ["IN_PROGRESS", "OK"]

    def destroy_balancer(self, balancer):
        """
        Destroy a load balancer (virtual listener)

        :param balancer: LoadBalancer which should be used
        :type  balancer: :class:`LoadBalancer`

        :return: ``True`` if the destroy was successful, otherwise ``False``.
        :rtype: ``bool``
        """
        delete_listener = ET.Element(
            "deleteVirtualListener", {"xmlns": TYPES_URN, "id": balancer.id}
        )

        result = self.connection.request_with_orgId_api_2(
            "networkDomainVip/deleteVirtualListener",
            method="POST",
            data=ET.tostring(delete_listener),
        ).object
        response_code = findtext(result, "responseCode", TYPES_URN)
        return response_code in ["IN_PROGRESS", "OK"]

    def ex_set_current_network_domain(self, network_domain_id):
        """
        Set the network domain (part of the network) of the driver

        :param network_domain_id: ID of the pool (required)
        :type  network_domain_id: ``str``
        """
        self.network_domain_id = network_domain_id

    def ex_get_current_network_domain(self):
        """
        Get the current network domain ID of the driver.

        :return: ID of the network domain
        :rtype: ``str``
        """
        return self.network_domain_id

    def ex_create_pool_member(self, pool, node, port=None):
        """
        Create a new member in an existing pool from an existing node

        :param pool: Instance of ``NttCisPool`` (required)
        :type  pool: ``NttCisPool``

        :param node: Instance of ``NttCisVIPNode`` (required)
        :type  node: ``NttCisVIPNode``

        :param port: Port the the service will listen on
        :type  port: ``str``

        :return: The node member, instance of ``NttCisPoolMember``
        :rtype: ``NttCisPoolMember``
        """
        create_pool_m = ET.Element("addPoolMember", {"xmlns": TYPES_URN})
        ET.SubElement(create_pool_m, "poolId").text = pool.id
        ET.SubElement(create_pool_m, "nodeId").text = node.id
        if port is not None:
            ET.SubElement(create_pool_m, "port").text = str(port)
        ET.SubElement(create_pool_m, "status").text = "ENABLED"
        response = self.connection.request_with_orgId_api_2(
            "networkDomainVip/addPoolMember",
            method="POST",
            data=ET.tostring(create_pool_m),
        ).object

        member_id = None
        node_name = None
        for info in findall(response, "info", TYPES_URN):
            if info.get("name") == "poolMemberId":
                member_id = info.get("value")
            if info.get("name") == "nodeName":
                node_name = info.get("value")

        return NttCisPoolMember(
            id=member_id,
            name=node_name,
            status=State.RUNNING,
            ip=node.ip,
            port=port,
            node_id=node.id,
        )

    def ex_create_node(
        self,
        network_domain_id,
        name,
        ip,
        ex_description=None,
        connection_limit=25000,
        connection_rate_limit=2000,
    ):
        """
        Create a new node

        :param network_domain_id: Network Domain ID (required)
        :type  name: ``str``

        :param name: name of the node (required)
        :type  name: ``str``

        :param ip: IPv4 address of the node (required)
        :type  ip: ``str``

        :param ex_description: Description of the node (required)
        :type  ex_description: ``str``

        :param connection_limit: Maximum number
                of concurrent connections per sec
        :type  connection_limit: ``int``

        :param connection_rate_limit: Maximum number of concurrent sessions
        :type  connection_rate_limit: ``int``

        :return: Instance of ``NttCisVIPNode``
        :rtype: ``NttCisVIPNode``
        """
        create_node_elm = ET.Element("createNode", {"xmlns": TYPES_URN})
        ET.SubElement(create_node_elm, "networkDomainId").text = network_domain_id
        ET.SubElement(create_node_elm, "name").text = name
        if ex_description is not None:
            ET.SubElement(create_node_elm, "description").text = str(ex_description)
        ET.SubElement(create_node_elm, "ipv4Address").text = ip
        ET.SubElement(create_node_elm, "status").text = "ENABLED"
        ET.SubElement(create_node_elm, "connectionLimit").text = str(connection_limit)
        ET.SubElement(create_node_elm, "connectionRateLimit").text = str(connection_rate_limit)

        response = self.connection.request_with_orgId_api_2(
            action="networkDomainVip/createNode",
            method="POST",
            data=ET.tostring(create_node_elm),
        ).object

        node_id = None
        node_name = None
        for info in findall(response, "info", TYPES_URN):
            if info.get("name") == "nodeId":
                node_id = info.get("value")
            if info.get("name") == "name":
                node_name = info.get("value")
        return NttCisVIPNode(id=node_id, name=node_name, status=State.RUNNING, ip=ip)

    def ex_update_node(self, node):
        """
        Update the properties of a node

        :param pool: The instance of ``NttCisNode`` to update
        :type  pool: ``NttCisNode``

        :return: The instance of ``NttCisNode``
        :rtype: ``NttCisNode``
        """
        create_node_elm = ET.Element("editNode", {"xmlns": TYPES_URN})
        create_node_elm.set("id", node.id)
        ET.SubElement(create_node_elm, "healthMonitorId").text = node.health_monitor_id
        ET.SubElement(create_node_elm, "connectionLimit").text = str(node.connection_limit)
        ET.SubElement(create_node_elm, "connectionRateLimit").text = str(node.connection_rate_limit)

        self.connection.request_with_orgId_api_2(
            action="networkDomainVip/editNode",
            method="POST",
            data=ET.tostring(create_node_elm),
        ).object
        return node

    def ex_set_node_state(self, node, enabled):
        """
        Change the state of a node (enable/disable)

        :param pool: The instance of ``NttCisNode`` to update
        :type  pool: ``NttCisNode``

        :param enabled: The target state of the node
        :type  enabled: ``bool``

        :return: The instance of ``NttCisNode``
        :rtype: ``NttCisNode``
        """
        create_node_elm = ET.Element("editNode", {"xmlns": TYPES_URN})
        ET.SubElement(create_node_elm, "status").text = "ENABLED" if enabled is True else "DISABLED"

        self.connection.request_with_orgId_api_2(
            action="networkDomainVip/editNode",
            method="POST",
            data=ET.tostring(create_node_elm),
        ).object
        return node

    def ex_create_pool(
        self,
        network_domain_id,
        name,
        balancer_method,
        ex_description,
        health_monitors=None,
        service_down_action="NONE",
        slow_ramp_time=30,
    ):
        """
        Create a new pool

        :param network_domain_id: Network Domain ID (required)
        :type  name: ``str``

        :param name: name of the node (required)
        :type  name: ``str``

        :param balancer_method: The load balancer algorithm (required)
        :type  balancer_method: ``str``

        :param ex_description: Description of the node (required)
        :type  ex_description: ``str``

        :param health_monitors: A list of health monitors to use for the pool.
        :type  health_monitors: ``list`` of
            :class:`NttCisDefaultHealthMonitor`

        :param service_down_action: What to do when node
                                    is unavailable NONE, DROP or RESELECT
        :type  service_down_action: ``str``

        :param slow_ramp_time: Number of seconds to stagger ramp up of nodes
        :type  slow_ramp_time: ``int``

        :return: Instance of ``NttCisPool``
        :rtype: ``NttCisPool``
        """
        # Names cannot contain spaces.
        name.replace(" ", "_")
        create_node_elm = ET.Element("createPool", {"xmlns": TYPES_URN})
        ET.SubElement(create_node_elm, "networkDomainId").text = network_domain_id
        ET.SubElement(create_node_elm, "name").text = name
        ET.SubElement(create_node_elm, "description").text = str(ex_description)
        ET.SubElement(create_node_elm, "loadBalanceMethod").text = str(balancer_method)

        if health_monitors is not None:
            for monitor in health_monitors:
                ET.SubElement(create_node_elm, "healthMonitorId").text = str(monitor.id)

        ET.SubElement(create_node_elm, "serviceDownAction").text = service_down_action
        ET.SubElement(create_node_elm, "slowRampTime").text = str(slow_ramp_time)

        response = self.connection.request_with_orgId_api_2(
            action="networkDomainVip/createPool",
            method="POST",
            data=ET.tostring(create_node_elm),
        ).object

        pool_id = None
        for info in findall(response, "info", TYPES_URN):
            if info.get("name") == "poolId":
                pool_id = info.get("value")

        return NttCisPool(
            id=pool_id,
            name=name,
            description=ex_description,
            status=State.RUNNING,
            load_balance_method=str(balancer_method),
            health_monitor_id=None,
            service_down_action=service_down_action,
            slow_ramp_time=str(slow_ramp_time),
        )

    def ex_create_virtual_listener(
        self,
        network_domain_id,
        name,
        ex_description,
        port=None,
        pool=None,
        listener_ip_address=None,
        persistence_profile=None,
        fallback_persistence_profile=None,
        irule=None,
        protocol="TCP",
        optimization_profile="TCP",
        connection_limit=25000,
        connection_rate_limit=2000,
        source_port_preservation="PRESERVE",
    ):
        """
        Create a new virtual listener (load balancer)

        :param network_domain_id: Network Domain ID (required)
        :type  name: ``str``

        :param name: name of the listener (required)
        :type  name: ``str``

        :param ex_description: Description of the node (required)
        :type  ex_description: ``str``

        :param port: An integer in the range of 1-65535. If not supplied,
                     it will be taken to mean 'Any Port'
        :type  port: ``int``

        :param pool: The pool to use for the listener
        :type  pool: :class:`NttCisPool`

        :param listener_ip_address: The IPv4 Address of the virtual listener
        :type  listener_ip_address: ``str``

        :param persistence_profile: Persistence profile
        :type  persistence_profile: :class:`NttCisPersistenceProfile`

        :param fallback_persistence_profile: Fallback persistence profile
        :type  fallback_persistence_profile:
            :class:`NttCisPersistenceProfile`

        :param irule: The iRule to apply
        :type  irule: :class:`NttCisDefaultiRule`

        :param protocol: For STANDARD type, ANY, TCP or UDP
                         for PERFORMANCE_LAYER_4 choice of ANY, TCP, UDP, HTTP
        :type  protocol: ``str``

        :param optimization_profile: For STANDARD type and protocol
                                     TCP an optimization type of TCP,
                                     LAN_OPT, WAN_OPT, MOBILE_OPT,
                                     or TCP_LEGACY is required.
                                     Default is 'TCP'.
        :type  protocol: ``str``

        :param connection_limit: Maximum number
                                of concurrent connections per sec
        :type  connection_limit: ``int``

        :param connection_rate_limit: Maximum number of concurrent sessions
        :type  connection_rate_limit: ``int``

        :param source_port_preservation: Choice of PRESERVE,
                                         PRESERVE_STRICT or CHANGE
        :type  source_port_preservation: ``str``

        :return: Instance of the listener
        :rtype: ``NttCisVirtualListener``
        """
        if (port == 80) or (port == 443):
            listener_type = "PERFORMANCE_LAYER_4"
        else:
            listener_type = "STANDARD"

        if listener_type == "STANDARD" and optimization_profile is None:
            raise ValueError(
                " CONFIGURATION_NOT_SUPPORTED: optimizationProfile is"
                " required for type STANDARD and protocol TCP"
            )

        create_node_elm = ET.Element("createVirtualListener", {"xmlns": TYPES_URN})
        ET.SubElement(create_node_elm, "networkDomainId").text = network_domain_id
        ET.SubElement(create_node_elm, "name").text = name
        ET.SubElement(create_node_elm, "description").text = str(ex_description)
        ET.SubElement(create_node_elm, "type").text = listener_type
        ET.SubElement(create_node_elm, "protocol").text = protocol
        if listener_ip_address is not None:
            ET.SubElement(create_node_elm, "listenerIpAddress").text = str(listener_ip_address)
        if port is not None:
            ET.SubElement(create_node_elm, "port").text = str(port)
        ET.SubElement(create_node_elm, "enabled").text = "true"
        ET.SubElement(create_node_elm, "connectionLimit").text = str(connection_limit)
        ET.SubElement(create_node_elm, "connectionRateLimit").text = str(connection_rate_limit)
        ET.SubElement(create_node_elm, "sourcePortPreservation").text = source_port_preservation
        if pool is not None:
            ET.SubElement(create_node_elm, "poolId").text = pool.id
        if persistence_profile is not None:
            ET.SubElement(create_node_elm, "persistenceProfileId").text = persistence_profile.id
        if optimization_profile is not None:
            ET.SubElement(create_node_elm, "optimizationProfile").text = optimization_profile
        if fallback_persistence_profile is not None:
            ET.SubElement(create_node_elm, "fallbackPersistenceProfileId").text = (
                fallback_persistence_profile.id
            )
        if irule is not None:
            ET.SubElement(create_node_elm, "iruleId").text = irule.id

        response = self.connection.request_with_orgId_api_2(
            action="networkDomainVip/createVirtualListener",
            method="POST",
            data=ET.tostring(create_node_elm),
        ).object

        virtual_listener_id = None
        virtual_listener_ip = None
        for info in findall(response, "info", TYPES_URN):
            if info.get("name") == "virtualListenerId":
                virtual_listener_id = info.get("value")
            if info.get("name") == "listenerIpAddress":
                virtual_listener_ip = info.get("value")

        return NttCisVirtualListener(
            id=virtual_listener_id,
            name=name,
            ip=virtual_listener_ip,
            status=State.RUNNING,
        )

    def ex_import_ssl_domain_certificate(
        self, network_domain_id, name, crt_file, key_file, description=None
    ):
        """
        Import an ssl cert for ssl offloading onto the the load balancer

        :param network_domain_id:  The Network Domain's Id.
        :type network_domain_id: ``str``
        :param name: The name of the ssl certificate
        :type name: ``str``
        :param crt_file: The complete path to the certificate file
        :type crt_file: ``str``
        :param key_file: The complete pathy to the key file
        :type key_file: ``str``
        :param description: (Optional) A description of the certificate
        :type `description: `str``
        :return: ``bool``
        """
        try:
            import OpenSSL
        except ImportError:
            raise ImportError(
                'Missing "OpenSSL" dependency. You can install '
                "it using pip - pip install pyopenssl"
            )

        with open(crt_file) as fp:
            c = OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_PEM, fp.read())

        cert = OpenSSL.crypto.dump_certificate(OpenSSL.crypto.FILETYPE_PEM, c).decode(
            encoding="utf-8"
        )

        with open(key_file) as fp:
            k = OpenSSL.crypto.load_privatekey(OpenSSL.crypto.FILETYPE_PEM, fp.read())

        key = OpenSSL.crypto.dump_privatekey(OpenSSL.crypto.FILETYPE_PEM, k).decode(
            encoding="utf-8"
        )
        cert_elem = ET.Element("importSslDomainCertificate", {"xmlns": TYPES_URN})
        ET.SubElement(cert_elem, "networkDomainId").text = network_domain_id
        ET.SubElement(cert_elem, "name").text = name
        if description is not None:
            ET.SubElement(cert_elem, "description").text = description
        ET.SubElement(cert_elem, "key").text = key
        ET.SubElement(cert_elem, "certificate").text = cert
        result = self.connection.request_with_orgId_api_2(
            "networkDomainVip/importSslDomainCertificate",
            method="POST",
            data=ET.tostring(cert_elem),
        ).object
        response_code = findtext(result, "responseCode", TYPES_URN)
        return response_code in ["IN_PROGRESS", "OK"]

    def ex_delete_ssl_domain_certificate(self, dom_cert_id):
        """
        Deletes an SSL domain certificate

        :param dom_cert_id: Id of certificate to delete
        :type dom_cert_id: ``str``
        :return: ``bool``
        """
        del_dom_cert_elem = ET.Element(
            "deleteSslDomainCertificate", {"id": dom_cert_id, "xmlns": TYPES_URN}
        )
        result = self.connection.request_with_orgId_api_2(
            "networkDomainVip/deleteSslDomainCertificate",
            method="POST",
            data=ET.tostring(del_dom_cert_elem),
        ).object
        response_code = findtext(result, "responseCode", TYPES_URN)
        return response_code in ["IN_PROGRESS", "OK"]

    def ex_import_ssl_cert_chain(self, network_domain_id, name, chain_crt_file, description=None):
        """
        Import an ssl certificate chain for ssl offloading onto
        the the load balancer

        :param network_domain_id:  The Network Domain's Id.
        :type network_domain_id: ``str``
        :param name: The name of the ssl certificate chain
        :type name: ``str``
        :param chain_crt_file: The complete path to the certificate chain file
        :type chain_crt_file: ``str``
        :param description: (Optional) A description of the certificate chain
        :type description: ``str``
        :return: ``bool``
        """
        try:
            import OpenSSL
            from OpenSSL import crypto
        except ImportError:
            raise ImportError(
                'Missing "OpenSSL" dependency. You can install '
                "it using pip - pip install pyopenssl"
            )

        c = crypto.load_certificate(crypto.FILETYPE_PEM, open(chain_crt_file).read())
        cert = OpenSSL.crypto.dump_certificate(crypto.FILETYPE_PEM, c).decode(encoding="utf-8")
        cert_chain_elem = ET.Element("importSslCertificateChain", {"xmlns": TYPES_URN})
        ET.SubElement(cert_chain_elem, "networkDomainId").text = network_domain_id
        ET.SubElement(cert_chain_elem, "name").text = name
        if description is not None:
            ET.SubElement(cert_chain_elem, "description").text = description
        ET.SubElement(cert_chain_elem, "certificateChain").text = cert
        result = self.connection.request_with_orgId_api_2(
            "networkDomainVip/importSslCertificateChain",
            method="POST",
            data=ET.tostring(cert_chain_elem),
        ).object
        response_code = findtext(result, "responseCode", TYPES_URN)
        return response_code in ["IN_PROGRESS", "OK"]

    def ex_delete_ssl_certificate_chain(self, cert_chain_id):
        """
        Deletes a certificate chain

        :param cert_chain_id: Id of certificate chain to delete
        :type cert_chain_id: ``str``
        :return ``bool``
        """
        del_cert_chain_elem = ET.Element(
            "deleteSslCertificateChain", {"id": cert_chain_id, "xmlns": TYPES_URN}
        )
        result = self.connection.request_with_orgId_api_2(
            "networkDomainVip/deleteSslCertificateChain",
            method="POST",
            data=ET.tostring(del_cert_chain_elem),
        ).object
        response_code = findtext(result, "responseCode", TYPES_URN)
        return response_code in ["IN_PROGRESS", "OK"]

    def ex_create_ssl_offload_profile(
        self,
        netowrk_domain_id,
        name,
        ssl_domain_cert_id,
        description=None,
        ciphers=None,
        ssl_cert_chain_id=None,
    ):
        """
        Creates an SSL Offload profile

        :param network_domain_id: The network domain's Id
        :type netowrk_domain_id: ``str``
        :param name: Offload profile's name
        :type name: ``str``
        :param ssl_domain_cert_id: Certificate's Id
        :type ssl_domain_cert_id: ``str``
        :param description: (Optional) Profile's description
        :type description: ``str``
        :param ciphers: (Optional) The default cipher string is:
        "MEDIUM:HIGH:!EXPORT:!ADH:!MD5:!RC4:!SSLv2:!SSLv3:
        !ECDHE+AES-GCM:!ECDHE+AES:!ECDHE+3DES:!ECDHE_ECDSA:
        !ECDH_RSA:!ECDH_ECDSA:@SPEED" It is possible to choose just a subset
        of this string
        :type ciphers: ``str``
        :param ssl_cert_chain_id: (Optional) Bind the certificate
        chain to the profile.
        :type ssl_cert_chain_id: `str``
        :returns: ``bool``
        """
        ssl_offload_elem = ET.Element("createSslOffloadProfile", {"xmlns": TYPES_URN})
        ET.SubElement(ssl_offload_elem, "networkDomainId").text = netowrk_domain_id
        ET.SubElement(ssl_offload_elem, "name").text = name
        if description is not None:
            ET.SubElement(ssl_offload_elem, "description").text = description
        if ciphers is not None:
            ET.SubElement(ssl_offload_elem, "ciphers").text = ciphers
        ET.SubElement(ssl_offload_elem, "sslDomainCertificateId").text = ssl_domain_cert_id
        if ssl_cert_chain_id is not None:
            ET.SubElement(ssl_offload_elem, "sslCertificateChainId").text = ssl_cert_chain_id
        result = self.connection.request_with_orgId_api_2(
            "networkDomainVip/createSslOffloadProfile",
            method="POST",
            data=ET.tostring(ssl_offload_elem),
        ).object
        response_code = findtext(result, "responseCode", TYPES_URN)
        return response_code in ["IN_PROGRESS", "OK"]

    def ex_edit_ssl_offload_profile(
        self,
        profile_id,
        name,
        ssl_domain_cert_id,
        description=None,
        ciphers=None,
        ssl_cert_chain_id=None,
    ):
        """
        The function edits the ssl offload profile

        :param profil_id: The id of the profile to be edited
        :type profile_id: ``str``
        :param name: The name of the profile, new name or previous name
        :type name: ``str``
        :param ssl_domain_cert_id: The certificate id to use, new or current
        :type ssl_domain_cert_id: ``str``
        :param description: (Optional) Profile's description
        :type description: ``str``
        :param ciphers: (Optional) String of acceptable ciphers to use
        :type ciphers: ``str``
        :param ssl_cert_chain_id: If using a certificate chain
        or changing to a new one
        :type: ssl_cert_chain_id: ``str``
        :returns: ``bool``
        """
        ssl_offload_elem = ET.Element(
            "editSslOffloadProfile", {"xmlns": TYPES_URN, "id": profile_id}
        )
        ET.SubElement(ssl_offload_elem, "name").text = name
        if description is not None:
            ET.SubElement(ssl_offload_elem, "description").text = description
        if ciphers is not None:
            ET.SubElement(ssl_offload_elem, "ciphers").text = ciphers
        ET.SubElement(ssl_offload_elem, "sslDomainCertificateId").text = ssl_domain_cert_id
        if ssl_cert_chain_id is not None:
            ET.SubElement(ssl_offload_elem, "sslCertificateChainId").text = ssl_cert_chain_id
        result = self.connection.request_with_orgId_api_2(
            "networkDomainVip/editSslOffloadProfile",
            method="POST",
            data=ET.tostring(ssl_offload_elem),
        ).object
        response_code = findtext(result, "responseCode", TYPES_URN)
        return response_code in ["IN_PROGRESS", "OK"]

    def ex_delete_ssl_offload_profile(self, profile_id):
        """
        Delete an offload profile

        :param profile_id: Id of profile to be deleted
        :type profile_id: ``str``
        :returns: ``bool``
        """
        del_profile_elem = ET.Element(
            "deleteSslOffloadProfile", {"id": profile_id, "xmlns": TYPES_URN}
        )
        result = self.connection.request_with_orgId_api_2(
            "networkDomainVip/deleteSslOffloadProfile",
            method="POST",
            data=ET.tostring(del_profile_elem),
        ).object
        response_code = findtext(result, "responseCode", TYPES_URN)
        return response_code in ["IN_PROGRESS", "OK"]

    def ex_get_pools(self, ex_network_domain_id=None):
        """
        Get all of the pools inside the current geography or
        in given network.

        :param ex_network_domain_id: UUID of Network Domain
               if not None returns only balancers in the given network
               if None then returns all pools for the organization
        :type  ex_network_domain_id: ``str``

        :return: Returns a ``list`` of type ``NttCisPool``
        :rtype: ``list`` of ``NttCisPool``
        """
        params = None

        if ex_network_domain_id is not None:
            params = {"networkDomainId": ex_network_domain_id}

        pools = self.connection.request_with_orgId_api_2(
            "networkDomainVip/pool", params=params
        ).object

        return self._to_pools(pools)

    def ex_get_pool(self, pool_id):
        """
        Get a specific pool inside the current geography

        :param pool_id: The identifier of the pool
        :type  pool_id: ``str``

        :return: Returns an instance of ``NttCisPool``
        :rtype: ``NttCisPool``
        """
        pool = self.connection.request_with_orgId_api_2("networkDomainVip/pool/%s" % pool_id).object
        return self._to_pool(pool)

    def ex_update_pool(self, pool):
        """
        Update the properties of an existing pool
        only method, serviceDownAction and slowRampTime are updated

        :param pool: The instance of ``NttCisPool`` to update
        :type  pool: ``NttCisPool``

        :return: ``True`` for success, ``False`` for failure
        :rtype: ``bool``
        """
        create_node_elm = ET.Element("editPool", {"xmlns": TYPES_URN})
        create_node_elm.set("id", pool.id)
        ET.SubElement(create_node_elm, "loadBalanceMethod").text = str(pool.load_balance_method)
        ET.SubElement(create_node_elm, "healthMonitorId").text = pool.health_monitor_id
        ET.SubElement(create_node_elm, "serviceDownAction").text = pool.service_down_action
        ET.SubElement(create_node_elm, "slowRampTime").text = str(pool.slow_ramp_time)

        response = self.connection.request_with_orgId_api_2(
            action="networkDomainVip/editPool",
            method="POST",
            data=ET.tostring(create_node_elm),
        ).object
        response_code = findtext(response, "responseCode", TYPES_URN)
        return response_code in ["IN_PROGRESS", "OK"]

    def ex_destroy_pool(self, pool):
        """
        Destroy an existing pool

        :param pool: The instance of ``NttCisPool`` to destroy
        :type  pool: ``NttCisPool``

        :return: ``True`` for success, ``False`` for failure
        :rtype: ``bool``
        """
        destroy_request = ET.Element("deletePool", {"xmlns": TYPES_URN, "id": pool.id})

        result = self.connection.request_with_orgId_api_2(
            action="networkDomainVip/deletePool",
            method="POST",
            data=ET.tostring(destroy_request),
        ).object
        response_code = findtext(result, "responseCode", TYPES_URN)
        return response_code in ["IN_PROGRESS", "OK"]

    def ex_get_pool_members(self, pool_id):
        """
        Get the members of a pool

        :param pool: The instance of a pool
        :type  pool: ``NttCisPool``

        :returns: Returns an ``list`` of ``NttCisPoolMember``
        :rtype: ``list`` of ``NttCisPoolMember``
        """
        members = self.connection.request_with_orgId_api_2(
            "networkDomainVip/poolMember?poolId=%s" % pool_id
        ).object
        return self._to_members(members)

    def ex_get_pool_member(self, pool_member_id):
        """
        Get a specific member of a pool

        :param pool: The id of a pool member
        :type  pool: ``str``

        :return: Returns an instance of ``NttCisPoolMember``
        :rtype: ``NttCisPoolMember``
        """
        member = self.connection.request_with_orgId_api_2(
            "networkDomainVip/poolMember/%s" % pool_member_id
        ).object
        return self._to_member(member)

    def ex_set_pool_member_state(self, member, enabled=True):
        request = ET.Element("editPoolMember", {"xmlns": TYPES_URN, "id": member.id})
        state = "ENABLED" if enabled is True else "DISABLED"
        ET.SubElement(request, "status").text = state

        result = self.connection.request_with_orgId_api_2(
            action="networkDomainVip/editPoolMember",
            method="POST",
            data=ET.tostring(request),
        ).object

        response_code = findtext(result, "responseCode", TYPES_URN)
        return response_code in ["IN_PROGRESS", "OK"]

    def ex_destroy_pool_member(self, member, destroy_node=False):
        """
        Destroy a specific member of a pool

        :param pool: The instance of a pool member
        :type  pool: ``NttCisPoolMember``

        :param destroy_node: Also destroy the associated node
        :type  destroy_node: ``bool``

        :return: ``True`` for success, ``False`` for failure
        :rtype: ``bool``
        """
        # remove the pool member
        destroy_request = ET.Element("removePoolMember", {"xmlns": TYPES_URN, "id": member.id})

        result = self.connection.request_with_orgId_api_2(
            action="networkDomainVip/removePoolMember",
            method="POST",
            data=ET.tostring(destroy_request),
        ).object

        if member.node_id is not None and destroy_node is True:
            return self.ex_destroy_node(member.node_id)
        else:
            response_code = findtext(result, "responseCode", TYPES_URN)
            return response_code in ["IN_PROGRESS", "OK"]

    def ex_get_nodes(self, ex_network_domain_id=None):
        """
        Get the nodes within this geography or in given network.

        :param ex_network_domain_id: UUID of Network Domain
               if not None returns only balancers in the given network
               if None then returns all pools for the organization
        :type  ex_network_domain_id: ``str``

        :return: Returns an ``list`` of ``NttCisVIPNode``
        :rtype: ``list`` of ``NttCisVIPNode``
        """
        params = None
        if ex_network_domain_id is not None:
            params = {"networkDomainId": ex_network_domain_id}

        nodes = self.connection.request_with_orgId_api_2(
            "networkDomainVip/node", params=params
        ).object
        return self._to_nodes(nodes)

    def ex_get_node(self, node_id):
        """
        Get the node specified by node_id

        :return: Returns an instance of ``NttCisVIPNode``
        :rtype: Instance of ``NttCisVIPNode``
        """
        nodes = self.connection.request_with_orgId_api_2(
            "networkDomainVip/node/%s" % node_id
        ).object
        return self._to_node(nodes)

    def ex_destroy_node(self, node_id):
        """
        Destroy a specific node

        :param node_id: The ID of of a ``NttCisVIPNode``
        :type  node_id: ``str``

        :return: ``True`` for success, ``False`` for failure
        :rtype: ``bool``
        """
        # Destroy the node
        destroy_request = ET.Element("deleteNode", {"xmlns": TYPES_URN, "id": node_id})

        result = self.connection.request_with_orgId_api_2(
            action="networkDomainVip/deleteNode",
            method="POST",
            data=ET.tostring(destroy_request),
        ).object
        response_code = findtext(result, "responseCode", TYPES_URN)
        return response_code in ["IN_PROGRESS", "OK"]

    def ex_wait_for_state(self, state, func, poll_interval=2, timeout=60, *args, **kwargs):
        """
        Wait for the function which returns a instance
        with field status to match

        Keep polling func until one of the desired states is matched

        :param state: Either the desired state (`str`) or a `list` of states
        :type  state: ``str`` or ``list``

        :param  func: The function to call, e.g. ex_get_vlan
        :type   func: ``function``

        :param  poll_interval: The number of seconds to wait between checks
        :type   poll_interval: `int`

        :param  timeout: The total number of seconds to wait to reach a state
        :type   timeout: `int`

        :param  args: The arguments for func
        :type   args: Positional arguments

        :param  kwargs: The arguments for func
        :type   kwargs: Keyword arguments
        """
        return self.connection.wait_for_state(state, func, poll_interval, timeout, *args, **kwargs)

    def ex_get_default_health_monitors(self, network_domain):
        """
        Get the default health monitors available for a network domain

        :param network_domain_id: The ID of of a ``NttCisNetworkDomain``
        :type  network_domain_id: ``str``

        :rtype: `list` of :class:`NttCisDefaultHealthMonitor`
        """
        result = self.connection.request_with_orgId_api_2(
            action="networkDomainVip/defaultHealthMonitor",
            params={"networkDomainId": network_domain},
            method="GET",
        ).object
        return self._to_health_monitors(result)

    def ex_get_default_persistence_profiles(self, network_domain_id):
        """
        Get the default persistence profiles available for a network domain

        :param network_domain_id: The ID of of a ``NttCisNetworkDomain``
        :type  network_domain_id: ``str``

        :rtype: `list` of :class:`NttCisPersistenceProfile`
        """
        result = self.connection.request_with_orgId_api_2(
            action="networkDomainVip/defaultPersistenceProfile",
            params={"networkDomainId": network_domain_id},
            method="GET",
        ).object
        return self._to_persistence_profiles(result)

    def ex_get_default_irules(self, network_domain_id):
        """
        Get the default iRules available for a network domain

        :param network_domain_id: The ID of of a ``NttCisNetworkDomain``
        :type  network_domain_id: ``str``

        :rtype: `list` of :class:`NttCisDefaultiRule`
        """
        result = self.connection.request_with_orgId_api_2(
            action="networkDomainVip/defaultIrule",
            params={"networkDomainId": network_domain_id},
            method="GET",
        ).object
        return self._to_irules(result)

    @get_params
    def ex_list_ssl_domain_certs(self, params={}):
        """
        Functions takes a named parameter that can be one or none of the
        following

        :param params: A sequence of comma separated keyword arguments
        and a value
            * id=
            * network_domain_id=
            * name=
            * state=
            * create_time=
            * expiry_time=
        :returns: `list` of :class: `NttCisDomaincertificate`
        """
        result = self.connection.request_with_orgId_api_2(
            action="networkDomainVip/sslDomainCertificate", params=params, method="GET"
        ).object
        return self._to_certs(result)

    def ex_get_ssl_domain_cert(self, cert_id):
        """
        Function gets the cert by id. Use this if only if the id
        is already known

        :param cert_id: The id of the specific cert
        :type cert_id: ``str``
        :returns: :class: `NttCisdomaincertificate
        """
        result = self.connection.request_with_orgId_api_2(
            action="networkDomainVip/sslDomainCertificate/%s" % cert_id, method="GET"
        ).object
        return self._to_cert(result)

    @get_params
    def ex_list_ssl_certificate_chains(self, params={}):
        """
        Functions takes a named parameter that can be one or none of the
        following to filter returned items

        :param params: A sequence of comma separated keyword arguments
        and a value
            * id=
            * network_domain_id=
            * name=
            * state=
            * create_time=
            * expiry_time=
        :return: `list` of :class: `NttCissslcertficiatechain`
        """
        result = self.connection.request_with_orgId_api_2(
            action="networkDomainVip/sslCertificateChain", params=params, method="GET"
        ).object
        return self._to_certificate_chains(result)

    def ex_get_ssl_certificate_chain(self, chain_id):
        """
        Function gets the certificate chain by id. Use this if only if the id
        is already known
        :param cert_id: The id of the specific cert
        :return: :class: `NttCiscertificatechain
        """
        result = self.connection.request_with_orgId_api_2(
            action="networkDomainVip/sslCertificateChain/%s" % chain_id, method="GET"
        ).object
        return self._to_certificate_chain(result)

    @get_params
    def ex_list_ssl_offload_profiles(self, params={}):
        """
        Functions takes a named parameter that can be one or none of the
        following to filter returned items

        :param params: A sequence of comma separated keyword arguments
        and a value
            * id=
            * network_domain_id=
            * datacenter_id=
            * name=
            * state=
            * ssl_domain_certificate_id=
            * ssl_domain_certificate_name=
            * ssl_certificate_chain_id=
            * ssl_certificate_chain_name=
            * create_time=
        :return: `list` of :class: `NttCisSslssloffloadprofile`
        """
        result = self.connection.request_with_orgId_api_2(
            action="networkDomainVip/sslOffloadProfile", params=params, method="GET"
        ).object
        return self._to_ssl_profiles(result)

    def ex_get_ssl_offload_profile(self, profile_id):
        result = self.connection.request_with_orgId_api_2(
            action="networkDomainVip/sslOffloadProfile/%s" % profile_id, method="GET"
        ).object
        return self._to_ssl_profile(result)

    def _to_irules(self, object):
        irules = []
        matches = object.findall(fixxpath("defaultIrule", TYPES_URN))
        for element in matches:
            irules.append(self._to_irule(element))
        return irules

    def _to_irule(self, element):
        compatible = []
        matches = element.findall(fixxpath("virtualListenerCompatibility", TYPES_URN))
        for match_element in matches:
            compatible.append(
                NttCisVirtualListenerCompatibility(
                    type=match_element.get("type"),
                    protocol=match_element.get("protocol", None),
                )
            )
        irule_element = element.find(fixxpath("irule", TYPES_URN))
        return NttCisDefaultiRule(
            id=irule_element.get("id"),
            name=irule_element.get("name"),
            compatible_listeners=compatible,
        )

    def _to_persistence_profiles(self, object):
        profiles = []
        matches = object.findall(fixxpath("defaultPersistenceProfile", TYPES_URN))
        for element in matches:
            profiles.append(self._to_persistence_profile(element))
        return profiles

    def _to_persistence_profile(self, element):
        compatible = []
        matches = element.findall(fixxpath("virtualListenerCompatibility", TYPES_URN))
        for match_element in matches:
            compatible.append(
                NttCisVirtualListenerCompatibility(
                    type=match_element.get("type"),
                    protocol=match_element.get("protocol", None),
                )
            )

        return NttCisPersistenceProfile(
            id=element.get("id"),
            fallback_compatible=bool(element.get("fallbackCompatible") == "true"),
            name=findtext(element, "name", TYPES_URN),
            compatible_listeners=compatible,
        )

    def _to_health_monitors(self, object):
        monitors = []
        matches = object.findall(fixxpath("defaultHealthMonitor", TYPES_URN))
        for element in matches:
            monitors.append(self._to_health_monitor(element))
        return monitors

    def _to_health_monitor(self, element):
        return NttCisDefaultHealthMonitor(
            id=element.get("id"),
            name=findtext(element, "name", TYPES_URN),
            node_compatible=bool(findtext(element, "nodeCompatible", TYPES_URN) == "true"),
            pool_compatible=bool(findtext(element, "poolCompatible", TYPES_URN) == "true"),
        )

    def _to_nodes(self, object):
        nodes = []
        for element in object.findall(fixxpath("node", TYPES_URN)):
            nodes.append(self._to_node(element))

        return nodes

    def _to_node(self, element):
        ipaddress = findtext(element, "ipv4Address", TYPES_URN)
        if ipaddress is None:
            ipaddress = findtext(element, "ipv6Address", TYPES_URN)

        name = findtext(element, "name", TYPES_URN)

        try:
            hm = element.find(fixxpath("healthMonitor", TYPES_URN)).get("id")
        except AttributeError:
            hm = None

        node = NttCisVIPNode(
            id=element.get("id"),
            name=name,
            status=self._VALUE_TO_STATE_MAP.get(
                findtext(element, "state", TYPES_URN), State.UNKNOWN
            ),
            health_monitor=hm,
            connection_rate_limit=findtext(element, "connectionRateLimit", TYPES_URN),
            connection_limit=findtext(element, "connectionLimit", TYPES_URN),
            ip=ipaddress,
        )

        return node

    def _to_balancers(self, object):
        loadbalancers = []
        for element in object.findall(fixxpath("virtualListener", TYPES_URN)):
            loadbalancers.append(self._to_balancer(element))

        return loadbalancers

    def _to_balancer(self, element):
        ipaddress = findtext(element, "listenerIpAddress", TYPES_URN)
        name = findtext(element, "name", TYPES_URN)
        port = findtext(element, "port", TYPES_URN)
        extra = {}

        pool_element = element.find(fixxpath("pool", TYPES_URN))
        if pool_element is None:
            extra["pool_id"] = None

        else:
            extra["pool_id"] = pool_element.get("id")

        extra["network_domain_id"] = findtext(element, "networkDomainId", TYPES_URN)

        balancer = LoadBalancer(
            id=element.get("id"),
            name=name,
            state=self._VALUE_TO_STATE_MAP.get(
                findtext(element, "state", TYPES_URN), State.UNKNOWN
            ),
            ip=ipaddress,
            port=port,
            driver=self.connection.driver,
            extra=extra,
        )

        return balancer

    def _to_members(self, object):
        members = []
        for element in object.findall(fixxpath("poolMember", TYPES_URN)):
            members.append(self._to_member(element))

        return members

    def _to_member(self, element):
        port = findtext(element, "port", TYPES_URN)
        if port is not None:
            port = int(port)
        pool_member = NttCisPoolMember(
            id=element.get("id"),
            name=element.find(fixxpath("node", TYPES_URN)).get("name"),
            status=findtext(element, "state", TYPES_URN),
            node_id=element.find(fixxpath("node", TYPES_URN)).get("id"),
            ip=element.find(fixxpath("node", TYPES_URN)).get("ipAddress"),
            port=port,
        )
        return pool_member

    def _to_pools(self, object):
        pools = []
        for element in object.findall(fixxpath("pool", TYPES_URN)):
            pools.append(self._to_pool(element))

        return pools

    def _to_pool(self, element):
        pool = NttCisPool(
            id=element.get("id"),
            name=findtext(element, "name", TYPES_URN),
            status=findtext(element, "state", TYPES_URN),
            description=findtext(element, "description", TYPES_URN),
            load_balance_method=findtext(element, "loadBalanceMethod", TYPES_URN),
            health_monitor_id=findtext(element, "healthMonitorId", TYPES_URN),
            service_down_action=findtext(element, "serviceDownAction", TYPES_URN),
            slow_ramp_time=findtext(element, "slowRampTime", TYPES_URN),
        )
        return pool

    def _to_certs(self, object):
        certs = []
        for element in object.findall(fixxpath("sslDomainCertificate", TYPES_URN)):
            certs.append(self._to_cert(element))
        return certs

    def _to_cert(self, el):
        return process_xml(ET.tostring(el))

    def _to_certificate_chains(self, object):
        cert_chains = []
        for element in object.findall(fixxpath("sslCertificateChain", TYPES_URN)):
            cert_chains.append(self._to_certificate_chain(element))
        return cert_chains

    def _to_certificate_chain(self, el):
        return process_xml(ET.tostring(el))

    def _to_ssl_profiles(self, object):
        profiles = []
        for element in object.findall(fixxpath("sslOffloadProfile", TYPES_URN)):
            profiles.append(self._to_ssl_profile(element))
        return profiles

    def _to_ssl_profile(self, el):
        return process_xml(ET.tostring(el))
