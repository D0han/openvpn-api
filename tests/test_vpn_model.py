import unittest
import datetime
import socket
import netaddr
from unittest.mock import patch, PropertyMock, ANY
import openvpn_status
import openvpn_api.util.errors as errors
from openvpn_api.vpn import VPN, VPNType


def gen_mock_values(values):
    """Generator to return the next value in a list of values on every call.

    >>> vals = gen_mock_values([1, 2, 3])
    >>> mocked_func.side_effect = lambda: next(vals)
    >>> mocked_func()
        1
    >>> mocked_func()
        2
    """
    for value in values:
        yield value


class TestVPNModel(unittest.TestCase):
    """Test the config file parser monitor.util.config_parser.ConfigParser
    """

    def test_host_port_socket(self):
        with self.assertRaises(errors.VPNError) as ctx:
            VPN(host="localhost", port=1234, socket="file.sock")
        self.assertEqual("Must specify either socket or host and port", str(ctx.exception))

    def test_host_port(self):
        vpn = VPN(host="localhost", port=1234)
        self.assertEqual(vpn._mgmt_host, "localhost")
        self.assertEqual(vpn._mgmt_port, 1234)
        self.assertIsNone(vpn._mgmt_socket)
        self.assertEqual(vpn.type, VPNType.IP)
        self.assertEqual(vpn.mgmt_address, "localhost:1234")

    def test_socket(self):
        vpn = VPN(socket="file.sock")
        self.assertEqual(vpn._mgmt_socket, "file.sock")
        self.assertIsNone(vpn._mgmt_host)
        self.assertIsNone(vpn._mgmt_port)
        self.assertEqual(vpn.type, VPNType.UNIX_SOCKET)
        self.assertEqual(vpn.mgmt_address, "file.sock")

    @patch("openvpn_api.vpn.socket.create_connection")
    def test_connect_ip_failure(self, mock_create_connection):
        vpn = VPN(host="localhost", port=1234)
        mock_create_connection.side_effect = socket.error()
        with self.assertRaises(errors.ConnectError):
            vpn.connect()
        mock_create_connection.side_effect = socket.timeout()
        with self.assertRaises(errors.ConnectError):
            vpn.connect()

    @patch("openvpn_api.vpn.VPN.connect")
    @patch("openvpn_api.vpn.VPN.disconnect")
    def test_connection_manager(self, mock_disconnect, mock_connect):
        vpn = VPN(host="localhost", port=1234)
        with vpn.connection():
            mock_connect.assert_called_once()
            mock_disconnect.assert_not_called()
            mock_connect.reset_mock()
        mock_connect.assert_not_called()
        mock_disconnect.assert_called_once()

    def test_send_command_disconnected(self):
        vpn = VPN(host="localhost", port=1234)
        with self.assertRaises(errors.NotConnectedError):
            vpn.send_command("asd")

    @patch("openvpn_api.vpn.VPN._socket_recv")
    @patch("openvpn_api.vpn.VPN._socket_send")
    @patch("openvpn_api.vpn.socket.create_connection")
    def test_send_command(self, mock_create_connection, mock_socket_send, mock_socket_recv):
        vpn = VPN(host="localhost", port=1234)
        vpn.connect()
        mock_create_connection.assert_called_once_with(("localhost", 1234), timeout=ANY)
        mock_socket_recv.assert_called_once()
        mock_socket_recv.reset_mock()
        vals = gen_mock_values(["asd\n", "END\n"])
        mock_socket_recv.side_effect = lambda: next(vals)
        a = vpn.send_command("help")
        mock_socket_send.assert_called_once_with("help\n")
        self.assertEqual(2, mock_socket_recv.call_count)
        self.assertEqual(a, "asd\nEND\n")

    @patch("openvpn_api.vpn.VPN._socket_recv")
    @patch("openvpn_api.vpn.VPN._socket_send")
    @patch("openvpn_api.vpn.socket.create_connection")
    def test_send_command_kill(self, mock_create_connection, mock_socket_send, mock_socket_recv):
        vpn = VPN(host="localhost", port=1234)
        vpn.connect()
        mock_create_connection.assert_called_once_with(("localhost", 1234), timeout=ANY)
        mock_socket_recv.assert_called_once()
        mock_socket_recv.reset_mock()
        self.assertIsNone(vpn.send_command("kill"))
        mock_socket_send.assert_called_once_with("kill\n")
        mock_socket_recv.assert_not_called()
        mock_socket_send.reset_mock()
        self.assertIsNone(vpn.send_command("client-kill"))
        mock_socket_send.assert_called_once_with("client-kill\n")
        mock_socket_recv.assert_not_called()

    @patch("openvpn_api.vpn.VPN._socket_recv")
    @patch("openvpn_api.vpn.VPN._socket_send")
    @patch("openvpn_api.vpn.socket.create_connection")
    def test_send_sigterm(self, mock_create_connection, mock_socket_send, mock_socket_recv):
        vpn = VPN(host="localhost", port=1234)
        vpn.connect()
        mock_create_connection.assert_called_once_with(("localhost", 1234), timeout=ANY)
        mock_socket_recv.assert_called_once()
        mock_socket_recv.reset_mock()
        mock_socket_recv.return_value = "SUCCESS: signal SIGTERM thrown"
        vpn.send_sigterm()
        mock_socket_send.assert_called_once_with("signal SIGTERM\n")
        mock_socket_recv.assert_called_once()

    @patch("openvpn_api.vpn.VPN.send_command")
    def test__get_version(self, mock_send_command):
        vpn = VPN(host="localhost", port=1234)
        mock_send_command.return_value = """
OpenVPN Version: OpenVPN 2.4.4 x86_64-pc-linux-gnu [SSL (OpenSSL)] [LZO] [LZ4] [EPOLL] [PKCS11] [MH/PKTINFO] [AEAD] built on Sep  5 2018
Management Version: 1
END
        """
        self.assertEqual(
            vpn._get_version(),
            "OpenVPN 2.4.4 x86_64-pc-linux-gnu [SSL (OpenSSL)] [LZO] [LZ4] [EPOLL] [PKCS11] [MH/PKTINFO] [AEAD] built on Sep  5 2018",
        )
        mock_send_command.assert_called_once_with("version")
        mock_send_command.reset_mock()
        mock_send_command.return_value = ""
        with self.assertRaises(errors.ParseError) as ctx:
            vpn._get_version()
        self.assertEqual("Unable to get OpenVPN version, no matches found in socket response.", str(ctx.exception))
        mock_send_command.assert_called_once_with("version")
        mock_send_command.reset_mock()
        mock_send_command.return_value = """
Management Version: 1
END
        """
        with self.assertRaises(errors.ParseError) as ctx:
            vpn._get_version()
        self.assertEqual("Unable to get OpenVPN version, no matches found in socket response.", str(ctx.exception))
        mock_send_command.assert_called_once_with("version")
        mock_send_command.reset_mock()

    @patch("openvpn_api.vpn.VPN._get_version")
    def test_release(self, mock_get_version):
        vpn = VPN(host="localhost", port=1234)
        self.assertIsNone(vpn._release)
        release_string = "OpenVPN 2.4.4 x86_64-pc-linux-gnu [SSL (OpenSSL)] [LZO] [LZ4] [EPOLL] [PKCS11] [MH/PKTINFO] [AEAD] built on Sep  5 2018"
        mock_get_version.return_value = release_string
        self.assertEqual(vpn.release, release_string)
        self.assertEqual(vpn._release, release_string)
        mock_get_version.assert_called_once_with()
        mock_get_version.reset_mock()
        vpn._release = "asd"
        self.assertEqual(vpn.release, "asd")
        mock_get_version.assert_not_called()

    @patch("openvpn_api.vpn.VPN._get_version")
    def test_version(self, mock_get_version):
        vpn = VPN(host="localhost", port=1234)
        vpn._release = "OpenVPN 2.4.4 x86_64-pc-linux-gnu [SSL (OpenSSL)] [LZO] [LZ4] [EPOLL] [PKCS11] [MH/PKTINFO] [AEAD] built on Sep  5 2018"
        self.assertEqual(vpn.version, "2.4.4")
        vpn._release = "OpenVPN 1.2.3 x86_64-pc-linux-gnu [SSL (OpenSSL)] [LZO] [LZ4] [EPOLL] [PKCS11] [MH/PKTINFO] [AEAD] built on Sep  5 2018"
        self.assertEqual(vpn.version, "1.2.3")
        vpn._release = "OpenVPN 11.22.33 x86_64-pc-linux-gnu [SSL (OpenSSL)] [LZO] [LZ4] [EPOLL] [PKCS11] [MH/PKTINFO] [AEAD] built on Sep  5 2018"
        self.assertEqual(vpn.version, "11.22.33")
        vpn._release = None
        mock_get_version.assert_not_called()  # Check mock hasn't been triggered up to this point
        mock_get_version.return_value = None
        self.assertIsNone(vpn.version)
        mock_get_version.assert_called_once()
        mock_get_version.reset_mock()
        vpn._release = "asd"
        with self.assertRaises(errors.ParseError) as ctx:
            vpn.version()
        self.assertEqual("Unable to parse version from release string.", str(ctx.exception))
        mock_get_version.assert_not_called()

    @patch("openvpn_api.vpn.VPN.send_command")
    def test_server_state(self, mock):
        vpn = VPN(host="localhost", port=1234)
        mock.return_value = """1560719601,CONNECTED,SUCCESS,10.0.0.1,,,1.2.3.4,1194
END"""
        self.assertIsNone(vpn._state)
        state = vpn.state
        mock.assert_called_once()
        self.assertEqual(datetime.datetime(2019, 6, 16, 21, 13, 21), state.up_since)
        self.assertEqual("CONNECTED", state.state_name)
        self.assertEqual("SUCCESS", state.desc_string)
        self.assertEqual(netaddr.IPAddress("10.0.0.1"), state.local_virtual_v4_addr)
        self.assertIsNone(state.remote_addr)
        self.assertIsNone(state.remote_port)
        self.assertEqual("1.2.3.4", state.local_addr)
        self.assertEqual(1194, state.local_port)
        mock.reset_mock()
        _ = vpn.state
        mock.assert_not_called()

    @patch("openvpn_api.vpn.VPN.release", new_callable=PropertyMock)
    @patch("openvpn_api.vpn.VPN.state", new_callable=PropertyMock)
    def test_cache(self, release_mock, state_mock):
        """Test caching VPN metadata works and clears correctly.
        """
        vpn = VPN(host="localhost", port=1234)
        vpn.cache_data()
        release_mock.assert_called_once()
        state_mock.assert_called_once()
        vpn._release = "asd"
        vpn._state = "qwe"
        vpn.clear_cache()
        self.assertIsNone(vpn._release)
        self.assertIsNone(vpn._state)

    @patch("openvpn_api.vpn.VPN.send_command")
    def test_get_stats(self, mock):
        # Normal response from send_command
        vpn = VPN(host="localhost", port=1234)
        mock.return_value = "SUCCESS: nclients=3,bytesin=129822996,bytesout=126946564\n"
        stats = vpn.get_stats()
        mock.assert_called_once()
        self.assertEqual(3, stats.client_count)
        self.assertEqual(129822996, stats.bytes_in)
        self.assertEqual(126946564, stats.bytes_out)
        mock.reset_mock()
        # Blank response from send_command
        mock.return_value = ""
        with self.assertRaises(errors.ParseError) as ctx:
            vpn.get_stats()
        self.assertEqual("Did not get expected response from load-stats.", str(ctx.exception))
        mock.assert_called_once()
        mock.reset_mock()
        # Bad response from send_command
        mock.return_value = "SUCCESS: nclients=3\n"
        with self.assertRaises(errors.ParseError) as ctx:
            vpn.get_stats()
        self.assertEqual("Unable to parse stats from load-stats response.", str(ctx.exception))
        mock.assert_called_once()

    @patch("openvpn_api.vpn.VPN.send_command")
    def test_get_status(self, mock):
        vpn = VPN(host="localhost", port=1234)
        mock.return_value = """OpenVPN CLIENT LIST
Updated,Thu Jul 18 20:47:42 2019
Common Name,Real Address,Bytes Received,Bytes Sent,Connected Since
testclient,1.2.3.4:12345,123456789,123456789,Tue Jun 11 21:22:02 2019
ROUTING TABLE
Virtual Address,Common Name,Real Address,Last Ref
10.0.0.2,testclient,1.2.3.4:12345,Wed Jun 12 21:55:04 2019
GLOBAL STATS
Max bcast/mcast queue length,2
END
"""
        status = vpn.get_status()
        mock.assert_called_once()
        self.assertIsInstance(status, openvpn_status.models.Status)
        self.assertEqual(len(status.client_list), 1)
        self.assertEqual(list(status.client_list.keys()), ["1.2.3.4:12345"])
