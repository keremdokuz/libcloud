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


import re
import sys
import datetime
import unittest
import traceback
from unittest.mock import patch, mock_open

from libcloud.test import MockHttp
from libcloud.utils.py3 import ET, PY2, b, httplib, assertRaisesRegex
from libcloud.compute.base import Node, NodeImage
from libcloud.test.compute import TestCaseMixin
from libcloud.test.secrets import VCLOUD_PARAMS
from libcloud.compute.types import NodeState
from libcloud.utils.iso8601 import UTC
from libcloud.test.file_fixtures import ComputeFileFixtures
from libcloud.compute.drivers.vcloud import (
    Vdc,
    Lease,
    Subject,
    ControlAccess,
    TerremarkDriver,
    VCloudNodeDriver,
    VCloud_1_5_NodeDriver,
    VCloud_5_1_NodeDriver,
    VCloud_5_5_NodeDriver,
    Instantiate_1_5_VAppXML,
    fixxpath,
    get_url_path,
)

BUILTINS = "__builtin__" if PY2 else "builtins"


def print_parameterized_failure(names_values):
    """
    Print failure information for a failed, parameterized test.
    This includes a traceback and parameter values.

    :param names_values: Name, value pairs for parameters of test at failure
    :type names_values: ``list`` of (``str``,  ``Any``)

    :return: None
    :rtype: ``None``
    """
    formatted_names_values = (
        "    {name}={value}".format(name=name, value=value) for name, value in names_values
    )
    traceback.print_exc()
    print(
        "Data values:\n{values}\n".format(values="\n".join(formatted_names_values)),
        file=sys.stderr,
    )


class CallException(Exception):
    """
    For halting method execution with mocking
    """

    pass


class TerremarkTests(unittest.TestCase, TestCaseMixin):
    def setUp(self):
        VCloudNodeDriver.connectionCls.host = "test"
        VCloudNodeDriver.connectionCls.conn_class = TerremarkMockHttp
        TerremarkMockHttp.type = None
        self.driver = TerremarkDriver(*VCLOUD_PARAMS)

    def test_list_images(self):
        ret = self.driver.list_images()
        self.assertEqual(
            ret[0].id,
            "https://services.vcloudexpress.terremark.com/api/v0.8/vAppTemplate/5",
        )

    def test_list_sizes(self):
        ret = self.driver.list_sizes()
        self.assertEqual(ret[0].ram, 512)

    def test_create_node(self):
        image = self.driver.list_images()[0]
        size = self.driver.list_sizes()[0]
        node = self.driver.create_node(
            name="testerpart2",
            image=image,
            size=size,
            ex_vdc="https://services.vcloudexpress.terremark.com/api/v0.8/vdc/224",
            ex_network="https://services.vcloudexpress.terremark.com/api/v0.8/network/725",
            ex_cpus=2,
        )
        self.assertTrue(isinstance(node, Node))
        self.assertEqual(
            node.id, "https://services.vcloudexpress.terremark.com/api/v0.8/vapp/14031"
        )
        self.assertEqual(node.name, "testerpart2")

    def test_list_nodes(self):
        ret = self.driver.list_nodes()
        node = ret[0]
        self.assertEqual(
            node.id, "https://services.vcloudexpress.terremark.com/api/v0.8/vapp/14031"
        )
        self.assertEqual(node.name, "testerpart2")
        self.assertEqual(node.state, NodeState.RUNNING)
        self.assertEqual(node.public_ips, [])
        self.assertEqual(node.private_ips, ["10.112.78.69"])

    def test_reboot_node(self):
        node = self.driver.list_nodes()[0]
        ret = self.driver.reboot_node(node)
        self.assertTrue(ret)

    def test_destroy_node(self):
        node = self.driver.list_nodes()[0]
        ret = self.driver.destroy_node(node)
        self.assertTrue(ret)


class VCloud_1_5_Tests(unittest.TestCase, TestCaseMixin):
    def setUp(self):
        VCloudNodeDriver.connectionCls.host = "test"
        VCloudNodeDriver.connectionCls.conn_class = VCloud_1_5_MockHttp
        VCloud_1_5_MockHttp.type = None
        self.driver = VCloud_1_5_NodeDriver(*VCLOUD_PARAMS)

    def test_list_images(self):
        ret = self.driver.list_images()
        self.assertEqual(
            "https://vm-vcloud/api/vAppTemplate/vappTemplate-ac1bc027-bf8c-4050-8643-4971f691c158",
            ret[0].id,
        )

    def test_list_sizes(self):
        ret = self.driver.list_sizes()
        self.assertEqual(ret[0].ram, 512)

    def test_networks(self):
        ret = self.driver.networks
        self.assertEqual(
            ret[0].get("href"),
            "https://vm-vcloud/api/network/dca8b667-6c8f-4c3e-be57-7a9425dba4f4",
        )

    def test_create_node(self):
        image = self.driver.list_images()[0]
        size = self.driver.list_sizes()[0]
        node = self.driver.create_node(
            name="testNode",
            image=image,
            size=size,
            ex_vdc="MyVdc",
            ex_network="vCloud - Default",
            cpus=2,
        )
        self.assertTrue(isinstance(node, Node))
        self.assertEqual(
            "https://vm-vcloud/api/vApp/vapp-8c57a5b6-e61b-48ca-8a78-3b70ee65ef6a",
            node.id,
        )
        self.assertEqual("testNode", node.name)

    def test_create_node_clone(self):
        image = self.driver.list_nodes()[0]
        node = self.driver.create_node(name="testNode", image=image)
        self.assertTrue(isinstance(node, Node))
        self.assertEqual(
            "https://vm-vcloud/api/vApp/vapp-8c57a5b6-e61b-48ca-8a78-3b70ee65ef6a",
            node.id,
        )
        self.assertEqual("testNode", node.name)

    def test_list_nodes(self):
        ret = self.driver.list_nodes()
        node = ret[0]
        self.assertEqual(
            node.id,
            "https://vm-vcloud/api/vApp/vapp-8c57a5b6-e61b-48ca-8a78-3b70ee65ef6a",
        )
        self.assertEqual(node.name, "testNode")
        self.assertEqual(node.state, NodeState.RUNNING)
        self.assertEqual(node.public_ips, ["65.41.67.2"])
        self.assertEqual(node.private_ips, ["65.41.67.2"])
        self.assertEqual(
            node.extra,
            {
                "description": None,
                "lease_settings": Lease(
                    "https://vm-vcloud/api/vApp/vapp-8c57a5b6-e61b-48ca-8a78-3b70ee65ef6a/leaseSettingsSection/",
                    deployment_lease=0,
                    storage_lease=0,
                ),
                "vdc": "MyVdc",
                "vms": [
                    {
                        "id": "https://vm-vcloud/api/vApp/vm-dd75d1d3-5b7b-48f0-aff3-69622ab7e045",
                        "name": "testVm",
                        "state": NodeState.RUNNING,
                        "public_ips": ["65.41.67.2"],
                        "private_ips": ["65.41.67.2"],
                        "os_type": "rhel5_64Guest",
                    }
                ],
            },
        )
        node = ret[1]
        self.assertEqual(
            node.id,
            "https://vm-vcloud/api/vApp/vapp-8c57a5b6-e61b-48ca-8a78-3b70ee65ef6b",
        )
        self.assertEqual(node.name, "testNode2")
        self.assertEqual(node.state, NodeState.RUNNING)
        self.assertEqual(node.public_ips, ["192.168.0.103"])
        self.assertEqual(node.private_ips, ["192.168.0.100"])
        self.assertEqual(
            node.extra,
            {
                "description": None,
                "lease_settings": Lease(
                    "https://vm-vcloud/api/vApp/vapp-8c57a5b6-e61b-48ca-8a78-3b70ee65ef6b/leaseSettingsSection/",
                    deployment_lease=0,
                    storage_lease=0,
                ),
                "vdc": "MyVdc",
                "vms": [
                    {
                        "id": "https://vm-vcloud/api/vApp/vm-dd75d1d3-5b7b-48f0-aff3-69622ab7e046",
                        "name": "testVm2",
                        "state": NodeState.RUNNING,
                        "public_ips": ["192.168.0.103"],
                        "private_ips": ["192.168.0.100"],
                        "os_type": "rhel5_64Guest",
                    }
                ],
            },
        )

    def test_reboot_node(self):
        node = self.driver.list_nodes()[0]
        ret = self.driver.reboot_node(node)
        self.assertTrue(ret)

    def test_destroy_node(self):
        node = self.driver.list_nodes()[0]
        ret = self.driver.destroy_node(node)
        self.assertTrue(ret)

    def test_validate_vm_names(self):
        # valid inputs
        self.driver._validate_vm_names(["host-n-ame-name"])
        self.driver._validate_vm_names(["tc-mybuild-b1"])
        self.driver._validate_vm_names(None)
        # invalid inputs
        self.assertRaises(ValueError, self.driver._validate_vm_names, ["invalid.host"])
        self.assertRaises(ValueError, self.driver._validate_vm_names, ["inv-alid.host"])
        self.assertRaises(ValueError, self.driver._validate_vm_names, ["hostnametoooolong"])
        self.assertRaises(ValueError, self.driver._validate_vm_names, ["host$name"])

    def test_change_vm_names(self):
        self.driver._change_vm_names(
            "/api/vApp/vapp-8c57a5b6-e61b-48ca-8a78-3b70ee65ef6a",
            ["changed1", "changed2"],
        )

    def test_change_vm_admin_password(self):
        self.driver.ex_change_vm_admin_password(
            "/api/vApp/vapp-8c57a5b6-e61b-48ca-8a78-3b70ee65ef6a", "12345678"
        )

    def test_is_node(self):
        self.assertTrue(
            self.driver._is_node(
                Node(
                    "testId",
                    "testNode",
                    state=0,
                    public_ips=[],
                    private_ips=[],
                    driver=self.driver,
                )
            )
        )
        self.assertFalse(self.driver._is_node(NodeImage("testId", "testNode", driver=self.driver)))

    def test_ex_deploy(self):
        node = self.driver.ex_deploy_node(
            Node(
                "/api/vApp/vapp-8c57a5b6-e61b-48ca-8a78-3b70ee65ef6a",
                "testNode",
                state=0,
                public_ips=[],
                private_ips=[],
                driver=self.driver,
            ),
            ex_force_customization=False,
        )
        self.assertEqual(node.state, NodeState.RUNNING)

    def test_ex_undeploy(self):
        node = self.driver.ex_undeploy_node(
            Node(
                "https://test/api/vApp/undeployTest",
                "testNode",
                state=0,
                public_ips=[],
                private_ips=[],
                driver=self.driver,
            )
        )
        self.assertEqual(node.state, NodeState.STOPPED)

    def test_ex_undeploy_with_error(self):
        node = self.driver.ex_undeploy_node(
            Node(
                "https://test/api/vApp/undeployErrorTest",
                "testNode",
                state=0,
                public_ips=[],
                private_ips=[],
                driver=self.driver,
            )
        )
        self.assertEqual(node.state, NodeState.STOPPED)

    def test_ex_undeploy_power_off(self):
        node = self.driver.ex_undeploy_node(
            Node(
                "https://test/api/vApp/undeployPowerOffTest",
                "testNode",
                state=0,
                public_ips=[],
                private_ips=[],
                driver=self.driver,
            ),
            shutdown=False,
        )
        self.assertEqual(node.state, NodeState.STOPPED)

    def test_ex_find_node(self):
        node = self.driver.ex_find_node("testNode")
        self.assertEqual(node.name, "testNode")
        node = self.driver.ex_find_node("testNode", self.driver.vdcs[0])
        self.assertEqual(node.name, "testNode")
        node = self.driver.ex_find_node("testNonExisting", self.driver.vdcs[0])
        self.assertIsNone(node)

    def test_ex_add_vm_disk__with_invalid_values(self):
        self.assertRaises(ValueError, self.driver.ex_add_vm_disk, "dummy", "invalid value")
        self.assertRaises(ValueError, self.driver.ex_add_vm_disk, "dummy", "-1")

    def test_ex_add_vm_disk(self):
        self.driver.ex_add_vm_disk("https://test/api/vApp/vm-test", "20")

    def test_ex_set_vm_cpu__with_invalid_values(self):
        self.assertRaises(ValueError, self.driver.ex_set_vm_cpu, "dummy", 50)
        self.assertRaises(ValueError, self.driver.ex_set_vm_cpu, "dummy", -1)

    def test_ex_set_vm_cpu(self):
        self.driver.ex_set_vm_cpu("https://test/api/vApp/vm-test", 4)

    def test_ex_set_vm_memory__with_invalid_values(self):
        self.assertRaises(ValueError, self.driver.ex_set_vm_memory, "dummy", 777)
        self.assertRaises(ValueError, self.driver.ex_set_vm_memory, "dummy", -1024)

    def test_ex_set_vm_memory(self):
        self.driver.ex_set_vm_memory("https://test/api/vApp/vm-test", 1024)

    def test_vdcs(self):
        vdcs = self.driver.vdcs
        self.assertEqual(len(vdcs), 1)
        self.assertEqual(
            vdcs[0].id, "https://vm-vcloud/api/vdc/3d9ae28c-1de9-4307-8107-9356ff8ba6d0"
        )
        self.assertEqual(vdcs[0].name, "MyVdc")
        self.assertEqual(vdcs[0].allocation_model, "AllocationPool")
        self.assertEqual(vdcs[0].storage.limit, 5120000)
        self.assertEqual(vdcs[0].storage.used, 1984512)
        self.assertEqual(vdcs[0].storage.units, "MB")
        self.assertEqual(vdcs[0].cpu.limit, 160000)
        self.assertEqual(vdcs[0].cpu.used, 0)
        self.assertEqual(vdcs[0].cpu.units, "MHz")
        self.assertEqual(vdcs[0].memory.limit, 527360)
        self.assertEqual(vdcs[0].memory.used, 130752)
        self.assertEqual(vdcs[0].memory.units, "MB")

    def test_ex_list_nodes(self):
        self.assertEqual(len(self.driver.ex_list_nodes()), len(self.driver.list_nodes()))

    def test_ex_list_nodes__masked_exception(self):
        """
        Test that we don't mask other exceptions.
        """
        brokenVdc = Vdc("/api/vdc/brokenVdc", "brokenVdc", self.driver)
        self.assertRaises(AnotherError, self.driver.ex_list_nodes, (brokenVdc))

    def test_ex_power_off(self):
        node = Node(
            "https://vm-vcloud/api/vApp/vapp-8c57a5b6-e61b-48ca-8a78-3b70ee65ef6b",
            "testNode",
            NodeState.RUNNING,
            [],
            [],
            self.driver,
        )
        self.driver.ex_power_off_node(node)

    def test_ex_query(self):
        results = self.driver.ex_query(
            "user", filter="name==jrambo", page=2, page_size=30, sort_desc="startDate"
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["type"], "UserRecord")
        self.assertEqual(results[0]["name"], "jrambo")
        self.assertEqual(results[0]["isLdapUser"], "true")

    def test_ex_get_control_access(self):
        node = Node(
            "https://vm-vcloud/api/vApp/vapp-8c57a5b6-e61b-48ca-8a78-3b70ee65ef6b",
            "testNode",
            NodeState.RUNNING,
            [],
            [],
            self.driver,
        )
        control_access = self.driver.ex_get_control_access(node)
        self.assertEqual(control_access.everyone_access_level, ControlAccess.AccessLevel.READ_ONLY)
        self.assertEqual(len(control_access.subjects), 1)
        self.assertEqual(control_access.subjects[0].type, "group")
        self.assertEqual(control_access.subjects[0].name, "MyGroup")
        self.assertEqual(
            control_access.subjects[0].id,
            "https://vm-vcloud/api/admin/group/b8202c48-7151-4e61-9a6c-155474c7d413",
        )
        self.assertEqual(
            control_access.subjects[0].access_level,
            ControlAccess.AccessLevel.FULL_CONTROL,
        )

    def test_ex_set_control_access(self):
        node = Node(
            "https://vm-vcloud/api/vApp/vapp-8c57a5b6-e61b-48ca-8a78-3b70ee65ef6b",
            "testNode",
            NodeState.RUNNING,
            [],
            [],
            self.driver,
        )
        control_access = ControlAccess(
            node,
            None,
            [
                Subject(
                    name="MyGroup",
                    type="group",
                    access_level=ControlAccess.AccessLevel.FULL_CONTROL,
                )
            ],
        )
        self.driver.ex_set_control_access(node, control_access)

    def test_ex_get_metadata(self):
        node = Node(
            "https://vm-vcloud/api/vApp/vapp-8c57a5b6-e61b-48ca-8a78-3b70ee65ef6b",
            "testNode",
            NodeState.RUNNING,
            [],
            [],
            self.driver,
        )
        metadata = self.driver.ex_get_metadata(node)
        self.assertEqual(metadata, {"owners": "msamia@netsuite.com"})

    def test_ex_set_metadata_entry(self):
        node = Node(
            "https://vm-vcloud/api/vApp/vapp-8c57a5b6-e61b-48ca-8a78-3b70ee65ef6b",
            "testNode",
            NodeState.RUNNING,
            [],
            [],
            self.driver,
        )
        self.driver.ex_set_metadata_entry(node, "foo", "bar")

    def test_ex_find_vm_nodes(self):
        nodes = self.driver.ex_find_vm_nodes("testVm2")
        self.assertEqual(len(nodes), 1)
        self.assertEqual(
            nodes[0].id,
            "https://vm-vcloud/api/vApp/vapp-8c57a5b6-e61b-48ca-8a78-3b70ee65ef6b",
        )

    def test_get_node(self):
        node = self.driver._ex_get_node(
            "https://vm-vcloud/api/vApp/vapp-8c57a5b6-e61b-48ca-8a78-3b70ee65ef6a"
        )
        self.assertEqual(node.name, "testNode")

    def test_get_node_forbidden(self):
        self.assertRaises(
            Exception,
            self.driver._ex_get_node,
            "https://vm-vcloud/api/vApp/vapp-access-to-resource-forbidden",
        )

    def test_to_node_description(self):
        node = self.driver._ex_get_node(
            "https://vm-vcloud/api/vApp/vapp-8c57a5b6-e61b-48ca-8a78-3b70ee65ef6a"
        )
        self.assertIsNone(node.extra["description"])
        node = self.driver._ex_get_node(
            "https://vm-vcloud/api/vApp/vapp-8c57a5b6-e61b-48ca-8a78-3b70ee65ef6d"
        )
        self.assertEqual(node.extra["description"], "Test Description")

    def test_to_node_lease_settings(self):
        node = self.driver._ex_get_node(
            "https://vm-vcloud/api/vApp/vapp-8c57a5b6-e61b-48ca-8a78-3b70ee65ef6a"
        )
        lease = Lease(
            "https://vm-vcloud/api/vApp/vapp-8c57a5b6-e61b-48ca-8a78-3b70ee65ef6a/leaseSettingsSection/",
            deployment_lease=0,
            storage_lease=0,
        )
        self.assertEqual(node.extra["lease_settings"], lease)
        node = self.driver._ex_get_node(
            "https://vm-vcloud/api/vApp/vapp-8c57a5b6-e61b-48ca-8a78-3b70ee65ef6d"
        )
        # 2019-10-07T14:06:29.980725
        lease = Lease(
            "https://vm-vcloud/api/vApp/vapp-8c57a5b6-e61b-48ca-8a78-3b70ee65ef6d/leaseSettingsSection/",
            deployment_lease=86400,
            storage_lease=172800,
            deployment_lease_expiration=datetime.datetime(
                year=2019,
                month=10,
                day=7,
                hour=14,
                minute=6,
                second=29,
                microsecond=980725,
                tzinfo=UTC,
            ),
            storage_lease_expiration=datetime.datetime(
                year=2019,
                month=10,
                day=8,
                hour=14,
                minute=6,
                second=29,
                microsecond=980725,
                tzinfo=UTC,
            ),
        )
        self.assertEqual(node.extra["lease_settings"], lease)

    def test_remove_admin_password(self):
        pass_enabled_xml = "<AdminPasswordEnabled>{text}</AdminPasswordEnabled>"
        pass_enabled_true = pass_enabled_xml.format(text="true")
        pass_enabled_false = pass_enabled_xml.format(text="false")
        pass_auto_xml = "<AdminPasswordAuto>{text}</AdminPasswordAuto>"
        pass_auto_true = pass_auto_xml.format(text="true")
        pass_auto_false = pass_auto_xml.format(text="false")
        passwd = "<AdminPassword>testpassword</AdminPassword>"
        assertion_error = False

        for admin_pass_enabled, admin_pass_auto, admin_pass, pass_exists in (
            (pass_enabled_true, pass_auto_true, passwd, False),
            (pass_enabled_true, pass_auto_true, "", False),
            (pass_enabled_true, pass_auto_false, passwd, True),
            (pass_enabled_true, pass_auto_false, "", False),
            (pass_enabled_true, "", passwd, False),
            (pass_enabled_true, "", "", False),
            (pass_enabled_false, pass_auto_true, passwd, False),
            (pass_enabled_false, pass_auto_true, "", False),
            (pass_enabled_false, pass_auto_false, passwd, False),
            (pass_enabled_false, pass_auto_false, "", False),
            (pass_enabled_false, "", passwd, False),
            (pass_enabled_false, "", "", False),
            ("", pass_auto_true, passwd, False),
            ("", pass_auto_true, "", False),
            ("", pass_auto_false, passwd, False),
            ("", pass_auto_false, "", False),
            ("", "", passwd, False),
            ("", "", "", False),
        ):
            try:
                guest_customization_section = ET.fromstring(
                    '<GuestCustomizationSection xmlns="http://www.vmware.com/vcloud/v1.5">'
                    + admin_pass_enabled
                    + admin_pass_auto
                    + admin_pass
                    + "</GuestCustomizationSection>"
                )
                self.driver._remove_admin_password(guest_customization_section)
                admin_pass_element = guest_customization_section.find(
                    fixxpath(guest_customization_section, "AdminPassword")
                )
                if pass_exists:
                    self.assertIsNotNone(admin_pass_element)
                else:
                    self.assertIsNone(admin_pass_element)
            except AssertionError:
                assertion_error = True
                print_parameterized_failure(
                    [
                        ("admin_pass_enabled", admin_pass_enabled),
                        ("admin_pass_auto", admin_pass_auto),
                        ("admin_pass", admin_pass),
                        ("pass_exists", pass_exists),
                    ]
                )

        if assertion_error:
            self.fail(msg="Assertion error(s) encountered. Details above.")

    @patch(
        "libcloud.compute.drivers.vcloud.VCloud_1_5_NodeDriver._get_vm_elements",
        side_effect=CallException("Called"),
    )
    def test_change_vm_script_text_and_file_logic(self, _):
        assertion_error = False

        for (
            vm_script_file,
            vm_script_text,
            open_succeeds,
            open_call_count,
            returned_early,
        ) in (
            (None, None, True, 0, True),
            (None, None, False, 0, True),
            (None, "script text", True, 0, False),
            (None, "script text", False, 0, False),
            ("file.sh", None, True, 1, False),
            ("file.sh", None, False, 1, True),
            ("file.sh", "script text", True, 0, False),
            ("file.sh", "script text", False, 0, False),
        ):
            try:
                if open_succeeds:
                    open_mock = patch(BUILTINS + ".open", mock_open(read_data="script text"))
                else:
                    open_mock = patch(BUILTINS + ".open", side_effect=Exception())
                with open_mock as mocked_open:
                    try:
                        self.driver._change_vm_script(
                            "https://vm-vcloud/api/vApp/vapp-8c57a5b6-e61b-48ca-8a78-3b70ee65ef6d",
                            vm_script=vm_script_file,
                            vm_script_text=vm_script_text,
                        )
                        returned_early_res = True
                    except CallException:
                        returned_early_res = False
                    self.assertEqual(mocked_open.call_count, open_call_count)
                    self.assertEqual(returned_early_res, returned_early)
            except AssertionError:
                assertion_error = True
                print_parameterized_failure(
                    [
                        ("vm_script_file", vm_script_file),
                        ("vm_script_text", vm_script_text),
                        ("open_succeeds", open_succeeds),
                        ("open_call_count", open_call_count),
                        ("returned_early", returned_early),
                    ]
                )

        if assertion_error:
            self.fail(msg="Assertion error(s) encountered. Details above.")

    def test_build_xmltree_description(self):
        instantiate_xml = Instantiate_1_5_VAppXML(
            name="testNode",
            template="https://vm-vcloud/api/vAppTemplate/vappTemplate-ac1bc027-bf8c-4050-8643-4971f691c158",
            network=None,
            vm_network=None,
            vm_fence=None,
            description=None,
        )
        self.assertIsNone(instantiate_xml.description)
        self.assertIsNone(instantiate_xml.root.find("Description"))

        test_description = "Test Description"
        instantiate_xml = Instantiate_1_5_VAppXML(
            name="testNode",
            template="https://vm-vcloud/api/vAppTemplate/vappTemplate-ac1bc027-bf8c-4050-8643-4971f691c158",
            network=None,
            vm_network=None,
            vm_fence=None,
            description=test_description,
        )
        self.assertEqual(instantiate_xml.description, test_description)
        description_elem = instantiate_xml.root.find("Description")
        self.assertIsNotNone(description_elem)
        self.assertEqual(description_elem.text, test_description)

    def test_to_lease(self):
        res = self.driver.connection.request(
            get_url_path("https://vm-vcloud/api/vApp/vapp-8c57a5b6-e61b-48ca-8a78-3b70ee65ef6d"),
            headers={"Content-Type": "application/vnd.vmware.vcloud.vApp+xml"},
        )
        lease_settings_section = res.object.find(fixxpath(res.object, "LeaseSettingsSection"))
        lease = Lease.to_lease(lease_element=lease_settings_section)

        self.assertEqual(lease.deployment_lease, 86400)
        self.assertEqual(
            lease.deployment_lease_expiration,
            datetime.datetime(
                year=2019,
                month=10,
                day=7,
                hour=14,
                minute=6,
                second=29,
                microsecond=980725,
                tzinfo=UTC,
            ),
        )
        self.assertEqual(lease.storage_lease, 172800)
        self.assertEqual(
            lease.storage_lease_expiration,
            datetime.datetime(
                year=2019,
                month=10,
                day=8,
                hour=14,
                minute=6,
                second=29,
                microsecond=980725,
                tzinfo=UTC,
            ),
        )

    def test_lease_get_time_deployed(self):
        deployment_datetime = datetime.datetime(
            year=2019,
            month=10,
            day=6,
            hour=14,
            minute=6,
            second=29,
            microsecond=980725,
            tzinfo=UTC,
        )
        deployment_lease_exp_actual = datetime.datetime(
            year=2019,
            month=10,
            day=7,
            hour=14,
            minute=6,
            second=29,
            microsecond=980725,
            tzinfo=UTC,
        )
        storage_lease_exp_actual = datetime.datetime(
            year=2019,
            month=10,
            day=8,
            hour=14,
            minute=6,
            second=29,
            microsecond=980725,
            tzinfo=UTC,
        )
        assertion_error = False

        for (
            deployment_lease,
            storage_lease,
            deployment_lease_exp,
            storage_lease_exp,
            exception,
            res,
        ) in (
            (None, None, None, None, True, None),
            (None, None, None, storage_lease_exp_actual, True, None),
            (None, None, deployment_lease_exp_actual, None, True, None),
            (
                None,
                None,
                deployment_lease_exp_actual,
                storage_lease_exp_actual,
                True,
                None,
            ),
            (None, 172800, None, None, True, None),
            (None, 172800, None, storage_lease_exp_actual, False, deployment_datetime),
            (
                None,
                172800,
                deployment_lease_exp_actual,
                None,
                True,
                deployment_datetime,
            ),
            (
                None,
                172800,
                deployment_lease_exp_actual,
                storage_lease_exp_actual,
                False,
                deployment_datetime,
            ),
            (86400, None, None, None, True, None),
            (86400, None, None, storage_lease_exp_actual, True, None),
            (
                86400,
                None,
                deployment_lease_exp_actual,
                None,
                False,
                deployment_datetime,
            ),
            (
                86400,
                None,
                deployment_lease_exp_actual,
                storage_lease_exp_actual,
                False,
                deployment_datetime,
            ),
            (86400, 172800, None, None, True, None),
            (86400, 172800, None, storage_lease_exp_actual, False, deployment_datetime),
            (
                86400,
                172800,
                deployment_lease_exp_actual,
                None,
                False,
                deployment_datetime,
            ),
            (
                86400,
                172800,
                deployment_lease_exp_actual,
                storage_lease_exp_actual,
                False,
                deployment_datetime,
            ),
        ):
            try:
                lease = Lease(
                    "https://vm-vcloud/api/vApp/vapp-8c57a5b6-e61b-48ca-8a78-3b70ee65ef6a/leaseSettingsSection/",
                    deployment_lease=deployment_lease,
                    storage_lease=storage_lease,
                    deployment_lease_expiration=deployment_lease_exp,
                    storage_lease_expiration=storage_lease_exp,
                )

                if exception:
                    with assertRaisesRegex(
                        self,
                        Exception,
                        re.escape(
                            "Cannot get time deployed. Missing complete lease and expiration information."
                        ),
                    ):
                        lease.get_deployment_time()
                else:
                    self.assertEqual(lease.get_deployment_time(), res)
            except AssertionError:
                assertion_error = True
                print_parameterized_failure(
                    [
                        ("deployment_lease", deployment_lease),
                        ("storage_lease", storage_lease),
                        ("deployment_lease_exp", deployment_lease_exp),
                        ("storage_lease_exp", storage_lease_exp),
                        ("exception", exception),
                        ("res", res),
                    ]
                )

        if assertion_error:
            self.fail(msg="Assertion error(s) encountered. Details above.")


class VCloud_5_1_Tests(unittest.TestCase, TestCaseMixin):
    def setUp(self):
        VCloudNodeDriver.connectionCls.host = "test"
        VCloudNodeDriver.connectionCls.conn_class = VCloud_1_5_MockHttp
        VCloud_1_5_MockHttp.type = None
        self.driver = VCloudNodeDriver(*VCLOUD_PARAMS, **{"api_version": "5.1"})

        self.assertTrue(isinstance(self.driver, VCloud_5_1_NodeDriver))

    def _test_create_node_valid_ex_vm_memory(self):
        # TODO: Hook up the fixture
        values = [4, 1024, 4096]

        image = self.driver.list_images()[0]
        size = self.driver.list_sizes()[0]

        for value in values:
            self.driver.create_node(
                name="testerpart2",
                image=image,
                size=size,
                vdc="https://services.vcloudexpress.terremark.com/api/v0.8/vdc/224",
                network="https://services.vcloudexpress.terremark.com/api/v0.8/network/725",
                cpus=2,
                ex_vm_memory=value,
            )

    def test_create_node_invalid_ex_vm_memory(self):
        values = [1, 3, 7]

        image = self.driver.list_images()[0]
        size = self.driver.list_sizes()[0]

        for value in values:
            try:
                self.driver.create_node(
                    name="testerpart2",
                    image=image,
                    size=size,
                    vdc="https://services.vcloudexpress.terremark.com/api/v0.8/vdc/224",
                    network="https://services.vcloudexpress.terremark.com/api/v0.8/network/725",
                    cpus=2,
                    ex_vm_memory=value,
                )
            except ValueError:
                pass
            else:
                self.fail("Exception was not thrown")

    def test_list_images(self):
        ret = self.driver.list_images()
        self.assertEqual(
            "https://vm-vcloud/api/vAppTemplate/vappTemplate-ac1bc027-bf8c-4050-8643-4971f691c158",
            ret[0].id,
        )


class VCloud_5_5_Tests(unittest.TestCase, TestCaseMixin):
    def setUp(self):
        VCloudNodeDriver.connectionCls.host = "test"
        VCloudNodeDriver.connectionCls.conn_class = VCloud_5_5_MockHttp
        VCloud_5_5_MockHttp.type = None
        self.driver = VCloudNodeDriver(*VCLOUD_PARAMS, **{"api_version": "5.5"})

        self.assertTrue(isinstance(self.driver, VCloud_5_5_NodeDriver))

    def test_ex_create_snapshot(self):
        node = Node(
            "https://vm-vcloud/api/vApp/vapp-8c57a5b6-e61b-48ca-8a78-3b70ee65ef6b",
            "testNode",
            NodeState.RUNNING,
            [],
            [],
            self.driver,
        )
        self.driver.ex_create_snapshot(node)

    def test_ex_remove_snapshots(self):
        node = Node(
            "https://vm-vcloud/api/vApp/vapp-8c57a5b6-e61b-48ca-8a78-3b70ee65ef6b",
            "testNode",
            NodeState.RUNNING,
            [],
            [],
            self.driver,
        )
        self.driver.ex_remove_snapshots(node)

    def test_ex_revert_to_snapshot(self):
        node = Node(
            "https://vm-vcloud/api/vApp/vapp-8c57a5b6-e61b-48ca-8a78-3b70ee65ef6b",
            "testNode",
            NodeState.RUNNING,
            [],
            [],
            self.driver,
        )
        self.driver.ex_revert_to_snapshot(node)

    def test_ex_acquire_mks_ticket(self):
        node = self.driver.ex_find_node("testNode")
        self.driver.ex_acquire_mks_ticket(node.id)

    def test_get_auth_headers(self):
        headers = self.driver.connection._get_auth_headers()
        self.assertEqual(headers["Accept"], "application/*+xml;version=5.5")


class TerremarkMockHttp(MockHttp):
    fixtures = ComputeFileFixtures("terremark")

    def _api_v0_8_login(self, method, url, body, headers):
        headers["set-cookie"] = "vcloud-token=testtoken"
        body = self.fixtures.load("api_v0_8_login.xml")
        return (httplib.OK, body, headers, httplib.responses[httplib.OK])

    def _api_v0_8_org_240(self, method, url, body, headers):
        body = self.fixtures.load("api_v0_8_org_240.xml")
        return (httplib.OK, body, headers, httplib.responses[httplib.OK])

    def _api_v0_8_vdc_224(self, method, url, body, headers):
        body = self.fixtures.load("api_v0_8_vdc_224.xml")
        return (httplib.OK, body, headers, httplib.responses[httplib.OK])

    def _api_v0_8_vdc_224_catalog(self, method, url, body, headers):
        body = self.fixtures.load("api_v0_8_vdc_224_catalog.xml")
        return (httplib.OK, body, headers, httplib.responses[httplib.OK])

    def _api_v0_8_catalogItem_5(self, method, url, body, headers):
        body = self.fixtures.load("api_v0_8_catalogItem_5.xml")
        return (httplib.OK, body, headers, httplib.responses[httplib.OK])

    def _api_v0_8_vdc_224_action_instantiateVAppTemplate(self, method, url, body, headers):
        body = self.fixtures.load("api_v0_8_vdc_224_action_instantiateVAppTemplate.xml")
        return (httplib.OK, body, headers, httplib.responses[httplib.OK])

    def _api_v0_8_vapp_14031_action_deploy(self, method, url, body, headers):
        body = self.fixtures.load("api_v0_8_vapp_14031_action_deploy.xml")
        return (httplib.ACCEPTED, body, headers, httplib.responses[httplib.ACCEPTED])

    def _api_v0_8_task_10496(self, method, url, body, headers):
        body = self.fixtures.load("api_v0_8_task_10496.xml")
        return (httplib.ACCEPTED, body, headers, httplib.responses[httplib.ACCEPTED])

    def _api_v0_8_vapp_14031_power_action_powerOn(self, method, url, body, headers):
        body = self.fixtures.load("api_v0_8_vapp_14031_power_action_powerOn.xml")
        return (httplib.ACCEPTED, body, headers, httplib.responses[httplib.ACCEPTED])

    def _api_v0_8_vapp_14031(self, method, url, body, headers):
        if method == "GET":
            body = self.fixtures.load("api_v0_8_vapp_14031_get.xml")
        elif method == "DELETE":
            body = ""
        return (httplib.ACCEPTED, body, headers, httplib.responses[httplib.ACCEPTED])

    def _api_v0_8_vapp_14031_power_action_reset(self, method, url, body, headers):
        body = self.fixtures.load("api_v0_8_vapp_14031_power_action_reset.xml")
        return (httplib.ACCEPTED, body, headers, httplib.responses[httplib.ACCEPTED])

    def _api_v0_8_vapp_14031_power_action_poweroff(self, method, url, body, headers):
        body = self.fixtures.load("api_v0_8_vapp_14031_power_action_poweroff.xml")
        return (httplib.ACCEPTED, body, headers, httplib.responses[httplib.ACCEPTED])

    def _api_v0_8_task_11001(self, method, url, body, headers):
        body = self.fixtures.load("api_v0_8_task_11001.xml")
        return (httplib.ACCEPTED, body, headers, httplib.responses[httplib.ACCEPTED])


class AnotherErrorMember(Exception):
    """
    helper class for the synthetic exception
    """

    def __init__(self):
        self.tag = "Error"

    def get(self, foo):
        return "ACCESS_TO_RESOURCE_IS_FORBIDDEN_1"


class AnotherError(Exception):
    pass


class VCloud_1_5_MockHttp(MockHttp, unittest.TestCase):
    fixtures = ComputeFileFixtures("vcloud_1_5")

    def request(self, method, url, body=None, headers=None, raw=False, stream=False):
        self.assertTrue(
            url.startswith("/api/"),
            (
                '"%s" is invalid. Needs to '
                'start with "/api". The passed URL should be just '
                "the path, not full URL.",
                url,
            ),
        )
        super().request(method, url, body, headers, raw)

    def _api_sessions(self, method, url, body, headers):
        headers["x-vcloud-authorization"] = "testtoken"
        body = self.fixtures.load("api_sessions.xml")
        return httplib.OK, body, headers, httplib.responses[httplib.OK]

    def _api_org(self, method, url, body, headers):
        body = self.fixtures.load("api_org.xml")
        return httplib.OK, body, headers, httplib.responses[httplib.OK]

    def _api_org_96726c78_4ae3_402f_b08b_7a78c6903d2a(self, method, url, body, headers):
        body = self.fixtures.load("api_org_96726c78_4ae3_402f_b08b_7a78c6903d2a.xml")
        return httplib.OK, body, headers, httplib.responses[httplib.OK]

    def _api_network_dca8b667_6c8f_4c3e_be57_7a9425dba4f4(self, method, url, body, headers):
        body = self.fixtures.load("api_network_dca8b667_6c8f_4c3e_be57_7a9425dba4f4.xml")
        return httplib.OK, body, headers, httplib.responses[httplib.OK]

    def _api_vdc_3d9ae28c_1de9_4307_8107_9356ff8ba6d0(self, method, url, body, headers):
        body = self.fixtures.load("api_vdc_3d9ae28c_1de9_4307_8107_9356ff8ba6d0.xml")
        return httplib.OK, body, headers, httplib.responses[httplib.OK]

    def _api_vdc_brokenVdc(self, method, url, body, headers):
        body = self.fixtures.load("api_vdc_brokenVdc.xml")
        return httplib.OK, body, headers, httplib.responses[httplib.OK]

    def _api_vApp_vapp_errorRaiser(self, method, url, body, headers):
        m = AnotherErrorMember()
        raise AnotherError(m)

    def _api_vdc_3d9ae28c_1de9_4307_8107_9356ff8ba6d0_action_instantiateVAppTemplate(
        self, method, url, body, headers
    ):
        body = self.fixtures.load(
            "api_vdc_3d9ae28c_1de9_4307_8107_9356ff8ba6d0_action_instantiateVAppTemplate.xml"
        )
        return httplib.ACCEPTED, body, headers, httplib.responses[httplib.ACCEPTED]

    def _api_vApp_vapp_8c57a5b6_e61b_48ca_8a78_3b70ee65ef6a_power_action_powerOn(
        self, method, url, body, headers
    ):
        return self._api_vApp_vapp_8c57a5b6_e61b_48ca_8a78_3b70ee65ef6b_power_action_all(
            method, url, body, headers
        )

    # Clone
    def _api_vdc_3d9ae28c_1de9_4307_8107_9356ff8ba6d0_action_cloneVApp(
        self, method, url, body, headers
    ):
        body = self.fixtures.load(
            "api_vdc_3d9ae28c_1de9_4307_8107_9356ff8ba6d0_action_cloneVApp.xml"
        )
        return httplib.ACCEPTED, body, headers, httplib.responses[httplib.ACCEPTED]

    def _api_vApp_vm_dd75d1d3_5b7b_48f0_aff3_69622ab7e045_networkConnectionSection(
        self, method, url, body, headers
    ):
        body = self.fixtures.load("api_task_b034df55_fe81_4798_bc81_1f0fd0ead450.xml")
        return httplib.ACCEPTED, body, headers, httplib.responses[httplib.ACCEPTED]

    def _api_vApp_vapp_8c57a5b6_e61b_48ca_8a78_3b70ee65ef6a(self, method, url, body, headers):
        status = httplib.OK
        if method == "GET":
            body = self.fixtures.load("api_vApp_vapp_8c57a5b6_e61b_48ca_8a78_3b70ee65ef6a.xml")
            status = httplib.OK
        elif method == "DELETE":
            body = self.fixtures.load("api_task_b034df55_fe81_4798_bc81_1f0fd0ead450.xml")
            status = httplib.ACCEPTED
        return status, body, headers, httplib.responses[status]

    def _api_vApp_vapp_8c57a5b6_e61b_48ca_8a78_3b70ee65ef6b(self, method, url, body, headers):
        body = self.fixtures.load("api_vApp_vapp_8c57a5b6_e61b_48ca_8a78_3b70ee65ef6b.xml")
        return httplib.OK, body, headers, httplib.responses[httplib.OK]

    def _api_vApp_vapp_8c57a5b6_e61b_48ca_8a78_3b70ee65ef6c(self, method, url, body, headers):
        body = self.fixtures.load("api_vApp_vapp_8c57a5b6_e61b_48ca_8a78_3b70ee65ef6c.xml")
        return httplib.OK, body, headers, httplib.responses[httplib.OK]

    def _api_vApp_vm_dd75d1d3_5b7b_48f0_aff3_69622ab7e045(self, method, url, body, headers):
        body = self.fixtures.load(
            "put_api_vApp_vm_dd75d1d3_5b7b_48f0_aff3_69622ab7e045_guestCustomizationSection.xml"
        )
        return httplib.ACCEPTED, body, headers, httplib.responses[httplib.ACCEPTED]

    def _api_vApp_vm_dd75d1d3_5b7b_48f0_aff3_69622ab7e045_guestCustomizationSection(
        self, method, url, body, headers
    ):
        if method == "GET":
            body = self.fixtures.load(
                "get_api_vApp_vm_dd75d1d3_5b7b_48f0_aff3_69622ab7e045_guestCustomizationSection.xml"
            )
            status = httplib.OK
        else:
            body = self.fixtures.load(
                "put_api_vApp_vm_dd75d1d3_5b7b_48f0_aff3_69622ab7e045_guestCustomizationSection.xml"
            )
            status = httplib.ACCEPTED
        return status, body, headers, httplib.responses[status]

    def _api_vApp_vapp_8c57a5b6_e61b_48ca_8a78_3b70ee65ef6a_power_action_reset(
        self, method, url, body, headers
    ):
        return self._api_vApp_vapp_8c57a5b6_e61b_48ca_8a78_3b70ee65ef6b_power_action_all(
            method, url, body, headers
        )

    def _api_task_b034df55_fe81_4798_bc81_1f0fd0ead450(self, method, url, body, headers):
        body = self.fixtures.load("api_task_b034df55_fe81_4798_bc81_1f0fd0ead450.xml")
        return httplib.OK, body, headers, httplib.responses[httplib.OK]

    def _api_catalog_cddb3cb2_3394_4b14_b831_11fbc4028da4(self, method, url, body, headers):
        body = self.fixtures.load("api_catalog_cddb3cb2_3394_4b14_b831_11fbc4028da4.xml")
        return httplib.OK, body, headers, httplib.responses[httplib.OK]

    def _api_catalogItem_3132e037_759b_4627_9056_ca66466fa607(self, method, url, body, headers):
        body = self.fixtures.load("api_catalogItem_3132e037_759b_4627_9056_ca66466fa607.xml")
        return httplib.OK, body, headers, httplib.responses[httplib.OK]

    def _api_vApp_deployTest(self, method, url, body, headers):
        body = self.fixtures.load("api_task_deploy.xml")
        return httplib.OK, body, headers, httplib.responses[httplib.OK]

    def _api_vApp_vapp_8c57a5b6_e61b_48ca_8a78_3b70ee65ef6a_action_deploy(
        self, method, url, body, headers
    ):
        body = self.fixtures.load("api_task_deploy.xml")
        return httplib.ACCEPTED, body, headers, httplib.responses[httplib.ACCEPTED]

    def _api_task_deploy(self, method, url, body, headers):
        body = self.fixtures.load("api_task_deploy.xml")
        return httplib.ACCEPTED, body, headers, httplib.responses[httplib.ACCEPTED]

    def _api_vApp_undeployTest(self, method, url, body, headers):
        body = self.fixtures.load("api_vApp_undeployTest.xml")
        return httplib.OK, body, headers, httplib.responses[httplib.OK]

    def _api_vApp_undeployTest_action_undeploy(self, method, url, body, headers):
        body = self.fixtures.load("api_task_undeploy.xml")
        return httplib.ACCEPTED, body, headers, httplib.responses[httplib.ACCEPTED]

    def _api_task_undeploy(self, method, url, body, headers):
        body = self.fixtures.load("api_task_undeploy.xml")
        return httplib.OK, body, headers, httplib.responses[httplib.OK]

    def _api_vApp_undeployErrorTest(self, method, url, body, headers):
        body = self.fixtures.load("api_vApp_undeployTest.xml")
        return httplib.OK, body, headers, httplib.responses[httplib.OK]

    def _api_vApp_undeployErrorTest_action_undeploy(self, method, url, body, headers):
        if b("shutdown") in b(body):
            body = self.fixtures.load("api_task_undeploy_error.xml")
        else:
            body = self.fixtures.load("api_task_undeploy.xml")
        return httplib.ACCEPTED, body, headers, httplib.responses[httplib.ACCEPTED]

    def _api_task_undeployError(self, method, url, body, headers):
        body = self.fixtures.load("api_task_undeploy_error.xml")
        return httplib.OK, body, headers, httplib.responses[httplib.OK]

    def _api_vApp_undeployPowerOffTest(self, method, url, body, headers):
        return self._api_vApp_undeployTest(method, url, body, headers)

    def _api_vApp_undeployPowerOffTest_action_undeploy(self, method, url, body, headers):
        self.assertIn(b("powerOff"), b(body))
        return self._api_vApp_undeployTest_action_undeploy(method, url, body, headers)

    def _api_vApp_vapp_access_to_resource_forbidden(self, method, url, body, headers):
        raise Exception(
            ET.fromstring(self.fixtures.load("api_vApp_vapp_access_to_resource_forbidden.xml"))
        )

    def _api_vApp_vm_test(self, method, url, body, headers):
        body = self.fixtures.load("api_vApp_vm_test.xml")
        return httplib.OK, body, headers, httplib.responses[httplib.OK]

    def _api_vApp_vm_test_virtualHardwareSection_disks(self, method, url, body, headers):
        if method == "GET":
            body = self.fixtures.load("get_api_vApp_vm_test_virtualHardwareSection_disks.xml")
            status = httplib.OK
        else:
            body = self.fixtures.load("put_api_vApp_vm_test_virtualHardwareSection_disks.xml")
            status = httplib.ACCEPTED
        return status, body, headers, httplib.responses[status]

    def _api_vApp_vm_test_virtualHardwareSection_cpu(self, method, url, body, headers):
        if method == "GET":
            body = self.fixtures.load("get_api_vApp_vm_test_virtualHardwareSection_cpu.xml")
            status = httplib.OK
        else:
            body = self.fixtures.load("put_api_vApp_vm_test_virtualHardwareSection_cpu.xml")
            status = httplib.ACCEPTED
        return status, body, headers, httplib.responses[status]

    def _api_vApp_vm_test_virtualHardwareSection_memory(self, method, url, body, headers):
        if method == "GET":
            body = self.fixtures.load("get_api_vApp_vm_test_virtualHardwareSection_memory.xml")
            status = httplib.OK
        else:
            body = self.fixtures.load("put_api_vApp_vm_test_virtualHardwareSection_memory.xml")
            status = httplib.ACCEPTED
        return status, body, headers, httplib.responses[status]

    def _api_vApp_vapp_8c57a5b6_e61b_48ca_8a78_3b70ee65ef6b_power_action_powerOff(
        self, method, url, body, headers
    ):
        return self._api_vApp_vapp_8c57a5b6_e61b_48ca_8a78_3b70ee65ef6b_power_action_all(
            method, url, body, headers
        )

    def _api_vApp_vapp_8c57a5b6_e61b_48ca_8a78_3b70ee65ef6b_power_action_all(
        self, method, url, body, headers
    ):
        assert method == "POST"
        body = self.fixtures.load(
            "api_vApp_vapp_8c57a5b6_e61b_48ca_8a78_3b70ee65ef6a_power_action_all.xml"
        )
        return httplib.ACCEPTED, body, headers, httplib.responses[httplib.ACCEPTED]

    def _api_query(self, method, url, body, headers):
        assert method == "GET"
        if "type=user" in url:
            self.assertTrue("page=2" in url)
            self.assertTrue("filter=(name==jrambo)" in url)
            self.assertTrue("sortDesc=startDate")
            body = self.fixtures.load("api_query_user.xml")
        elif "type=group" in url:
            body = self.fixtures.load("api_query_group.xml")
        elif "type=vm" in url and "filter=(name==testVm2)" in url:
            body = self.fixtures.load("api_query_vm.xml")
        else:
            raise AssertionError("Unexpected query type")
        return httplib.OK, body, headers, httplib.responses[httplib.OK]

    def _api_vApp_vapp_8c57a5b6_e61b_48ca_8a78_3b70ee65ef6b_metadata(
        self, method, url, body, headers
    ):
        if method == "POST":
            body = self.fixtures.load("api_vapp_post_metadata.xml")
            return httplib.ACCEPTED, body, headers, httplib.responses[httplib.ACCEPTED]
        else:
            body = self.fixtures.load("api_vapp_get_metadata.xml")
            return httplib.OK, body, headers, httplib.responses[httplib.OK]

    def _api_vApp_vapp_8c57a5b6_e61b_48ca_8a78_3b70ee65ef6b_controlAccess(
        self, method, url, body, headers
    ):
        body = self.fixtures.load(
            "api_vApp_vapp_8c57a5b6_e61b_48ca_8a78_3b70ee65ef6a_controlAccess.xml"
        )
        return httplib.OK, body, headers, httplib.responses[httplib.OK]

    def _api_vApp_vapp_8c57a5b6_e61b_48ca_8a78_3b70ee65ef6b_action_controlAccess(
        self, method, url, body, headers
    ):
        body = str(body)
        self.assertTrue(method == "POST")
        self.assertTrue("<IsSharedToEveryone>false</IsSharedToEveryone>" in body)
        self.assertTrue(
            '<Subject href="https://vm-vcloud/api/admin/group/b8202c48-7151-4e61-9a6c-155474c7d413" />'
            in body
        )
        self.assertTrue("<AccessLevel>FullControl</AccessLevel>" in body)
        body = self.fixtures.load(
            "api_vApp_vapp_8c57a5b6_e61b_48ca_8a78_3b70ee65ef6a_controlAccess.xml"
        )
        return httplib.OK, body, headers, httplib.responses[httplib.OK]

    def _api_admin_group_b8202c48_7151_4e61_9a6c_155474c7d413(self, method, url, body, headers):
        body = self.fixtures.load("api_admin_group_b8202c48_7151_4e61_9a6c_155474c7d413.xml")
        return httplib.OK, body, headers, httplib.responses[httplib.OK]

    def _api_vApp_vapp_8c57a5b6_e61b_48ca_8a78_3b70ee65ef6d(self, method, url, body, headers):
        body = self.fixtures.load("api_vApp_vapp_8c57a5b6_e61b_48ca_8a78_3b70ee65ef6d.xml")
        return httplib.OK, body, headers, httplib.responses[httplib.OK]


class VCloud_5_5_MockHttp(VCloud_1_5_MockHttp):
    # TODO: Move 5.5 fixtures to their own folder

    def _api_vApp_vapp_8c57a5b6_e61b_48ca_8a78_3b70ee65ef6b_action_createSnapshot(
        self, method, url, body, headers
    ):
        assert method == "POST"
        body = self.fixtures.load(
            "api_vApp_vapp_8c57a5b6_e61b_48ca_8a78_3b70ee65ef6b_create_snapshot.xml"
        )
        return httplib.OK, body, headers, httplib.responses[httplib.OK]

    def _api_task_fab4b26f_4f2e_4d49_ad01_ae9324bbfe48(self, method, url, body, headers):
        body = self.fixtures.load("api_task_b034df55_fe81_4798_bc81_1f0fd0ead450.xml")
        return httplib.OK, body, headers, httplib.responses[httplib.OK]

    def _api_vApp_vapp_8c57a5b6_e61b_48ca_8a78_3b70ee65ef6b_action_removeAllSnapshots(
        self, method, url, body, headers
    ):
        assert method == "POST"
        body = self.fixtures.load(
            "api_vApp_vapp_8c57a5b6_e61b_48ca_8a78_3b70ee65ef6b_remove_snapshots.xml"
        )
        return httplib.OK, body, headers, httplib.responses[httplib.OK]

    def _api_task_2518935e_b315_4d8e_9e99_9275f751877c(self, method, url, body, headers):
        body = self.fixtures.load("api_task_2518935e_b315_4d8e_9e99_9275f751877c.xml")
        return httplib.OK, body, headers, httplib.responses[httplib.OK]

    def _api_vApp_vapp_8c57a5b6_e61b_48ca_8a78_3b70ee65ef6b_action_revertToCurrentSnapshot(
        self, method, url, body, headers
    ):
        assert method == "POST"
        body = self.fixtures.load(
            "api_vApp_vapp_8c57a5b6_e61b_48ca_8a78_3b70ee65ef6b_revert_snapshot.xml"
        )
        return httplib.OK, body, headers, httplib.responses[httplib.OK]

    def _api_task_fe75d3af_f5a3_44a5_b016_ae0bdadfc32b(self, method, url, body, headers):
        body = self.fixtures.load("api_task_fe75d3af_f5a3_44a5_b016_ae0bdadfc32b.xml")
        return httplib.OK, body, headers, httplib.responses[httplib.OK]


if __name__ == "__main__":
    sys.exit(unittest.main())
