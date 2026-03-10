"""Tests for the patch validator module."""

import socket
import struct
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from game_server.models import ServiceName, TeamName
from game_server.patch_validator import (
    _check_axis,
    _check_ico,
    _check_nilua,
    _check_tcp_connect,
    _get_container_ip,
    _get_health_check,
    _get_service_port,
    validate_and_deploy_patch,
)


class TestGetServicePort:
    def test_axis_port(self):
        assert _get_service_port(ServiceName.AXIS) == 4000

    def test_ico_port(self):
        assert _get_service_port(ServiceName.ICO) == 4265

    def test_nilua_port(self):
        assert _get_service_port(ServiceName.NILUA) == 8080


class TestGetHealthCheck:
    def test_returns_correct_function_for_each_service(self):
        assert _get_health_check(ServiceName.AXIS) is _check_axis
        assert _get_health_check(ServiceName.ICO) is _check_ico
        assert _get_health_check(ServiceName.NILUA) is _check_nilua


class TestGetContainerIp:
    @patch("game_server.patch_validator.subprocess.run")
    def test_returns_ip_on_success(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="10.10.1.10\n"
        )
        assert _get_container_ip("pulsar-claude-axis") == "10.10.1.10"

    @patch("game_server.patch_validator.subprocess.run")
    def test_returns_none_on_empty_output(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="\n")
        assert _get_container_ip("pulsar-claude-axis") is None

    @patch("game_server.patch_validator.subprocess.run")
    def test_returns_none_on_nonzero_returncode(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        assert _get_container_ip("nonexistent") is None

    @patch("game_server.patch_validator.subprocess.run")
    def test_returns_none_on_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="docker", timeout=10)
        assert _get_container_ip("pulsar-claude-axis") is None

    @patch("game_server.patch_validator.subprocess.run")
    def test_returns_none_on_process_error(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(1, "docker")
        assert _get_container_ip("pulsar-claude-axis") is None


class TestCheckTcpConnect:
    @patch("game_server.patch_validator.socket.socket")
    def test_success(self, mock_socket_class):
        mock_sock = MagicMock()
        mock_socket_class.return_value = mock_sock
        assert _check_tcp_connect("10.10.1.10", 4000) is True
        mock_sock.connect.assert_called_once_with(("10.10.1.10", 4000))
        mock_sock.close.assert_called_once()

    @patch("game_server.patch_validator.socket.socket")
    def test_connection_refused(self, mock_socket_class):
        mock_sock = MagicMock()
        mock_sock.connect.side_effect = ConnectionRefusedError()
        mock_socket_class.return_value = mock_sock
        assert _check_tcp_connect("10.10.1.10", 4000) is False

    @patch("game_server.patch_validator.socket.socket")
    def test_timeout(self, mock_socket_class):
        mock_sock = MagicMock()
        mock_sock.connect.side_effect = socket.timeout()
        mock_socket_class.return_value = mock_sock
        assert _check_tcp_connect("10.10.1.10", 4000) is False


class TestCheckAxis:
    @patch("game_server.patch_validator.subprocess.run")
    @patch("game_server.patch_validator._check_tcp_connect")
    @patch("game_server.patch_validator._get_container_ip")
    def test_healthy_service(self, mock_ip, mock_tcp, mock_run):
        mock_ip.return_value = "10.10.1.10"
        mock_tcp.return_value = True
        mock_run.return_value = MagicMock(stdout="200", returncode=0)

        success, msg = _check_axis("test-container", 4000)
        assert success is True
        assert "200" in msg

    @patch("game_server.patch_validator._get_container_ip")
    def test_no_container_ip(self, mock_ip):
        mock_ip.return_value = None
        success, msg = _check_axis("test-container", 4000)
        assert success is False
        assert "Could not get container IP" in msg

    @patch("game_server.patch_validator.subprocess.run")
    @patch("game_server.patch_validator._check_tcp_connect")
    @patch("game_server.patch_validator._get_container_ip")
    def test_redirect_accepted(self, mock_ip, mock_tcp, mock_run):
        mock_ip.return_value = "10.10.1.10"
        mock_tcp.return_value = True
        mock_run.return_value = MagicMock(stdout="302", returncode=0)

        success, msg = _check_axis("test-container", 4000)
        assert success is True
        assert "302" in msg

    @patch("game_server.patch_validator.subprocess.run")
    @patch("game_server.patch_validator._check_tcp_connect")
    @patch("game_server.patch_validator._get_container_ip")
    def test_500_rejected(self, mock_ip, mock_tcp, mock_run):
        mock_ip.return_value = "10.10.1.10"
        mock_tcp.return_value = True
        mock_run.return_value = MagicMock(stdout="500", returncode=0)

        success, msg = _check_axis("test-container", 4000)
        assert success is False
        assert "500" in msg

    @patch("game_server.patch_validator.time.sleep")
    @patch("game_server.patch_validator._check_tcp_connect")
    @patch("game_server.patch_validator._get_container_ip")
    def test_port_not_open(self, mock_ip, mock_tcp, mock_sleep):
        mock_ip.return_value = "10.10.1.10"
        mock_tcp.return_value = False  # never connects

        success, msg = _check_axis("test-container", 4000)
        assert success is False
        assert "not accepting connections" in msg


class TestCheckIco:
    @patch("game_server.patch_validator.socket.socket")
    @patch("game_server.patch_validator._check_tcp_connect")
    @patch("game_server.patch_validator._get_container_ip")
    def test_healthy_service(self, mock_ip, mock_tcp, mock_socket_class):
        mock_ip.return_value = "10.10.1.11"
        mock_tcp.return_value = True

        mock_sock = MagicMock()
        # Server responds with 1-byte ACK (0x01 = Acknowledge)
        mock_sock.recv.return_value = b'\x01'
        mock_socket_class.return_value = mock_sock

        success, msg = _check_ico("test-container", 4265)
        assert success is True
        assert "ACK" in msg
        # Verify we sent the Connect command
        mock_sock.sendall.assert_any_call(b'\x10')

    @patch("game_server.patch_validator.socket.socket")
    @patch("game_server.patch_validator._check_tcp_connect")
    @patch("game_server.patch_validator._get_container_ip")
    def test_no_response(self, mock_ip, mock_tcp, mock_socket_class):
        mock_ip.return_value = "10.10.1.11"
        mock_tcp.return_value = True

        mock_sock = MagicMock()
        mock_sock.recv.return_value = b''  # empty response
        mock_socket_class.return_value = mock_sock

        success, msg = _check_ico("test-container", 4265)
        assert success is False
        assert "No response" in msg

    @patch("game_server.patch_validator.socket.socket")
    @patch("game_server.patch_validator._check_tcp_connect")
    @patch("game_server.patch_validator._get_container_ip")
    def test_connection_error(self, mock_ip, mock_tcp, mock_socket_class):
        mock_ip.return_value = "10.10.1.11"
        mock_tcp.return_value = True

        mock_sock = MagicMock()
        mock_sock.connect.side_effect = socket.error("Connection reset")
        mock_socket_class.return_value = mock_sock

        success, msg = _check_ico("test-container", 4265)
        assert success is False
        assert "Protocol check failed" in msg

    @patch("game_server.patch_validator.socket.socket")
    @patch("game_server.patch_validator._check_tcp_connect")
    @patch("game_server.patch_validator._get_container_ip")
    def test_sends_disconnect_after_connect(self, mock_ip, mock_tcp, mock_socket_class):
        """Verify we send Disconnect (0x11) to cleanly close the session."""
        mock_ip.return_value = "10.10.1.11"
        mock_tcp.return_value = True

        mock_sock = MagicMock()
        mock_sock.recv.return_value = b'\x01'
        mock_socket_class.return_value = mock_sock

        _check_ico("test-container", 4265)

        # Should have sent Connect then Disconnect
        calls = mock_sock.sendall.call_args_list
        assert calls[0].args[0] == b'\x10'  # Connect
        assert calls[1].args[0] == b'\x11'  # Disconnect


class TestCheckNilua:
    @patch("game_server.patch_validator.socket.socket")
    @patch("game_server.patch_validator._check_tcp_connect")
    @patch("game_server.patch_validator._get_container_ip")
    def test_healthy_service_with_response(self, mock_ip, mock_tcp, mock_socket_class):
        mock_ip.return_value = "10.10.1.12"
        mock_tcp.return_value = True

        mock_sock = MagicMock()
        # Simulate a valid length-prefixed response
        response_body = b'error: invalid message'
        response = struct.pack('!I', len(response_body)) + response_body
        mock_sock.recv.return_value = response
        mock_socket_class.return_value = mock_sock

        success, msg = _check_nilua("test-container", 8080)
        assert success is True
        assert "bytes response" in msg

    @patch("game_server.patch_validator.socket.socket")
    @patch("game_server.patch_validator._check_tcp_connect")
    @patch("game_server.patch_validator._get_container_ip")
    def test_healthy_service_timeout_on_probe(self, mock_ip, mock_tcp, mock_socket_class):
        """Service is alive but doesn't respond to our garbage probe."""
        mock_ip.return_value = "10.10.1.12"
        mock_tcp.return_value = True

        mock_sock = MagicMock()
        mock_sock.recv.side_effect = socket.timeout()
        mock_socket_class.return_value = mock_sock

        success, msg = _check_nilua("test-container", 8080)
        assert success is True
        assert "timeout on probe" in msg

    @patch("game_server.patch_validator.socket.socket")
    @patch("game_server.patch_validator._check_tcp_connect")
    @patch("game_server.patch_validator._get_container_ip")
    def test_sends_length_prefixed_message(self, mock_ip, mock_tcp, mock_socket_class):
        """Verify we send a properly framed length-prefixed message."""
        mock_ip.return_value = "10.10.1.12"
        mock_tcp.return_value = True

        mock_sock = MagicMock()
        mock_sock.recv.return_value = b'\x00\x00\x00\x01\x00'
        mock_socket_class.return_value = mock_sock

        _check_nilua("test-container", 8080)

        # Should send 4-byte big-endian length + 1-byte payload
        sent_data = mock_sock.sendall.call_args.args[0]
        length = struct.unpack('!I', sent_data[:4])[0]
        assert length == 1  # 1 byte payload
        assert len(sent_data) == 5  # 4 bytes length + 1 byte payload

    @patch("game_server.patch_validator.socket.socket")
    @patch("game_server.patch_validator._check_tcp_connect")
    @patch("game_server.patch_validator._get_container_ip")
    def test_connection_refused(self, mock_ip, mock_tcp, mock_socket_class):
        mock_ip.return_value = "10.10.1.12"
        mock_tcp.return_value = True

        mock_sock = MagicMock()
        mock_sock.connect.side_effect = ConnectionRefusedError()
        mock_socket_class.return_value = mock_sock

        success, msg = _check_nilua("test-container", 8080)
        assert success is False
        assert "TCP check failed" in msg

    @patch("game_server.patch_validator._get_container_ip")
    def test_no_container_ip(self, mock_ip):
        mock_ip.return_value = None
        success, msg = _check_nilua("test-container", 8080)
        assert success is False
        assert "Could not get container IP" in msg


class TestValidateAndDeployPatch:
    """Integration-style tests for the full validate_and_deploy_patch flow."""

    @patch("game_server.patch_validator._cleanup_test_container")
    @patch("game_server.patch_validator.subprocess.run")
    def test_build_failure_rejects_patch(self, mock_run, mock_cleanup):
        mock_run.return_value = MagicMock(
            returncode=1, stderr="error: Dockerfile not found"
        )

        success, msg = validate_and_deploy_patch(
            TeamName.CLAUDE, ServiceName.AXIS, "/bad/path"
        )
        assert success is False
        assert "Build failed" in msg

    @patch("game_server.patch_validator._cleanup_test_container")
    @patch("game_server.patch_validator.subprocess.run")
    def test_build_timeout_rejects_patch(self, mock_run, mock_cleanup):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="docker", timeout=120)

        success, msg = validate_and_deploy_patch(
            TeamName.CLAUDE, ServiceName.AXIS, "/some/path"
        )
        assert success is False
        assert "timed out" in msg

    @patch("game_server.patch_validator._get_health_check")
    @patch("game_server.patch_validator.time.sleep")
    @patch("game_server.patch_validator._cleanup_test_container")
    @patch("game_server.patch_validator.subprocess.run")
    def test_health_check_failure_rejects_patch(
        self, mock_run, mock_cleanup, mock_sleep, mock_get_check
    ):
        # Build succeeds
        build_result = MagicMock(returncode=0)
        # rm -f succeeds
        rm_result = MagicMock(returncode=0)
        # docker run succeeds
        run_result = MagicMock(returncode=0)
        mock_run.side_effect = [build_result, rm_result, run_result]

        # Health check fails
        mock_check = MagicMock(return_value=(False, "Service crashed on startup"))
        mock_get_check.return_value = mock_check

        success, msg = validate_and_deploy_patch(
            TeamName.GPT, ServiceName.ICO, "/some/path"
        )
        assert success is False
        assert "Health check failed" in msg
        assert "Service crashed" in msg
        # Test container should be cleaned up
        mock_cleanup.assert_called()

    @patch("game_server.patch_validator._get_container_ip")
    @patch("game_server.patch_validator._get_health_check")
    @patch("game_server.patch_validator.time.sleep")
    @patch("game_server.patch_validator._cleanup_test_container")
    @patch("game_server.patch_validator.subprocess.run")
    def test_successful_patch_deploys(
        self, mock_run, mock_cleanup, mock_sleep, mock_get_check, mock_ip
    ):
        # Build succeeds, rm succeeds, run succeeds
        mock_run.return_value = MagicMock(returncode=0)

        # Health check passes
        mock_check = MagicMock(return_value=(True, "HTTP 200"))
        mock_get_check.return_value = mock_check

        # IP lookup for deployment
        mock_ip.return_value = "10.10.1.10"

        success, msg = validate_and_deploy_patch(
            TeamName.CLAUDE, ServiceName.AXIS, "/some/path"
        )
        assert success is True
        assert "deployed" in msg.lower()

    @patch("game_server.patch_validator._cleanup_test_container")
    @patch("game_server.patch_validator.subprocess.run")
    def test_nilua_uses_target_flag(self, mock_run, mock_cleanup):
        """Nilua builds need --target nilua in the docker build command."""
        mock_run.return_value = MagicMock(
            returncode=1, stderr="build error"
        )

        validate_and_deploy_patch(
            TeamName.GPT, ServiceName.NILUA, "/some/path"
        )

        # Check that docker build was called with --target nilua
        build_call = mock_run.call_args_list[0]
        cmd = build_call.args[0]
        assert "--target" in cmd
        assert "nilua" in cmd

    @patch("game_server.patch_validator._cleanup_test_container")
    @patch("game_server.patch_validator.subprocess.run")
    def test_container_start_failure_cleans_up(self, mock_run, mock_cleanup):
        # Build succeeds
        build_result = MagicMock(returncode=0)
        # rm -f succeeds
        rm_result = MagicMock(returncode=0)
        # docker run fails
        mock_run.side_effect = [
            build_result,
            rm_result,
            subprocess.CalledProcessError(1, "docker run"),
        ]

        success, msg = validate_and_deploy_patch(
            TeamName.CLAUDE, ServiceName.AXIS, "/some/path"
        )
        assert success is False
        assert "Failed to start test container" in msg
        mock_cleanup.assert_called_with("pulsar-test-claude-axis")
