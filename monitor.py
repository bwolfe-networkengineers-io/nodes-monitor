"""
Log into device and monitor connectivity to nodes for interested interfaces until canceled.
"""
from getpass import getpass
from netmiko import ConnectHandler
from tabulate import tabulate
from datetime import datetime
import re
import os
import socket

from config import DEVICE_NAME, DEVICE_IP, DEVICE_TYPE, INTERFACES

USERNAME = input("Username: ")
PASSWORD = getpass("Password: ")

class Device:
    """ The Cisco device to manage """
    def __init__(self, ip, name, username, password, device_type):
        self.ip = ip
        self.name = name
        self.username = username
        self.password = password
        self.device_type = device_type
        self.ssh = None
        self.nodes = []

    def __str__(self):
        return self.name

    def connect(self):
        """ Log into the device """
        cisco_router = {
            'device_type': self.device_type,
            'host': self.ip,
            'username': self.username,
            'password': self.password
        }
        self.ssh = ConnectHandler(**cisco_router)

    def disconnect(self):
        """ Log out of the device """
        self.ssh.disconnect()
        self.ssh = None

    def create_attached_nodes(self, interface):
        """ Gets the MAC Addresses connected to the interface.
        Args:
            interface:
                A str, the name identifying which interface to get the mac-address table of.
        Returns:
            A list of str.
        """
        def get_vlan_and_mac_addresses(interface):
            # * 4        0050.569f.0c60    dynamic     ~~~      F    F  Po6
            match_line = re.compile(r"^\*\s(?P<vlan>\d+)\s+(?P<mac_address>[0-9a-f\.]{14})")

            output = self.ssh.send_command(f"show mac address-table interface {interface}")

            vlan_and_mac_addresses = []

            for line in output.split("\n"):
                match = match_line.match(line)

                if match:
                    groups = match.groupdict()
                    vlan = groups['vlan']
                    mac_address = groups['mac_address']
                    vlan_and_mac_addresses.append((vlan, mac_address))

            return vlan_and_mac_addresses

        def get_ip_address(mac_address):
            # 10.25.5.37      00:08:31  0050.569f.0c60  Vlan4
            match_line = re.compile(r"^(?P<ip_address>\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s+(?P<age>\d{2}:\d{2}:\d{2})\s+")

            output = self.ssh.send_command(f"show ip arp | include {mac_address}")
            
            match = match_line.match(output)

            if match:
                groups = match.groupdict()
                ip_address = groups['ip_address']
                
                return ip_address

        vlan_and_mac_addresses = get_vlan_and_mac_addresses(interface)
        
        for vlan, mac_address in vlan_and_mac_addresses:
            ip_address = get_ip_address(mac_address)
            node = Node(mac_address, ip_address, interface, vlan)
            print(f"{node.interface}\t{node.vlan}\t{node.mac_address}\t{node.ip_address}")
            self.nodes.append(node)


class Node:
    """ The end device attached to the port """
    def __init__(self, mac_address, ip_address, interface, vlan):
        self.mac_address = mac_address
        self.ip_address = ip_address
        self.interface = interface
        self.vlan = vlan
        self.name = None
        self.last_ping_successful = False
        self.successful_pings = 0
        self.failed_pings = 0

    def __str__(self):
        if self.name != None:
            return self.name
        else:
            return self.ip_address

    def ping(self):
        """ Pings the IP address """
        command = f"ping -n 1 -w 2 {self.ip_address} >> output.txt"

        response = os.system(command)
        if response == 0:
            self.last_ping_successful = True
            self.successful_pings += 1
        else:
            self.last_ping_successful = False
            self.failed_pings += 1

    def nslookup(self):
        """ Sets the DNS name for the node """
        try:
            self.name = socket.gethostbyaddr(self.ip_address)[0]
        except:
            self.name = None

    @property
    def response_rate(self):
        if self.successful_pings == 0:
            return "0%"
        else:      
            return f"{round(self.successful_pings / (self.successful_pings + self.failed_pings) * 100, 1)}%"

    
class Table:
    """ Table for monitored node information. """
    def __init__(self):
        self.headers = ["Interface", "VLAN", "MAC Address", "IP Address", "Name", "Response Rate"]
        self.rows = []

    def pre_populate_table(self, nodes):
        """ Adds node information to table's rows before monitoring. 
        Args:
            nodes:
                An list, containing the node objects.
        """
        for node in nodes:
            self.rows.append([
                node.interface, 
                node.vlan, 
                node.mac_address, 
                node.ip_address, 
                node.name, 
                node.response_rate
            ])

    def update_row(self, node, index):
        """ Updates the row in the table with the node's current information. 
        Args:
            node:
                An object, the node being monitored.
            index:
                An int, the node index for the table's rows and for the device's node list.
        """
        self.rows[index] = [
            node.interface, 
            node.vlan, 
            node.mac_address, 
            node.ip_address, 
            node.name, 
            node.response_rate
        ]

    def save(self, start, end):
        """ Saves the table to a text file. 
        Args:
            start:
                A datetime object, when monitoring started.
            end:
                A datetime object, when monitoring finished.
        """
        with open("output_table.txt", "w") as f:
            f.writelines(f"{start} - {end}")
            f.writelines("\n\n")
            f.writelines(tabulate(self.rows, self.headers))


if __name__ == '__main__':
    # Log in and get information of nodes connected to the device's interfaces.
    device = Device(DEVICE_IP, DEVICE_NAME, USERNAME, PASSWORD, DEVICE_TYPE)
    
    print(f"\n-----Connecting to device-----------------------------------------------------------------------------------------\n")
    device.connect()
    print(f"\n-----Connected to device------------------------------------------------------------------------------------------\n")
    
    print(f"\n-----Collecting MAC and IP Address for attached nodes-------------------------------------------------------------\n")
    for interface in INTERFACES:
        device.create_attached_nodes(interface)
    
    print(f"\n-----Disconnecting from device------------------------------------------------------------------------------------\n")
    device.disconnect()
    print(f"\n-----Disconnected from device-------------------------------------------------------------------------------------\n")
    
    for node in device.nodes:
        if node.ip_address != None:
            print(f"Resolving DNS name for {node.ip_address}")
            node.nslookup()

    # Monitoring and output
    table = Table()
    table.pre_populate_table(device.nodes)
    
    start = datetime.now()
    while True:
        index = 0
        for node in device.nodes:
            if node.ip_address is None:
                index += 1
                continue

            node.ping()

            table.update_row(node, index)
            table.save(start, datetime.now())

            # Print monitor data to terminal
            print(f"{node.interface}\t{node.vlan}\t{node.mac_address}\t{node.ip_address}\t{node.last_ping_successful}\t{node.response_rate}\t{node.name}")

            index += 1