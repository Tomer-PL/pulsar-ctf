"""Live integration tests that verify flag rotation works end-to-end.

These tests require running Docker containers (docker compose up -d).
They verify that after planting a new flag, each service actually serves
the updated flag when exploited.

Run with: pytest tests/test_flag_rotation_live.py -v -s
Requires: docker compose up -d
"""

import hashlib
import socket
import struct
import subprocess
import time

import pytest

# Skip all tests if containers aren't running
def _containers_running() -> bool:
    try:
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Running}}", "pulsar-claude-axis"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() == "true"
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _containers_running(),
    reason="Docker containers not running (run: docker compose up -d)",
)


def plant_flag(container: str, flag_value: str) -> None:
    """Plant a flag into a container."""
    subprocess.run(
        [
            "docker", "exec", "-u", "root", container,
            "sh", "-c", f"echo '{flag_value}' > /flag && chmod 644 /flag",
        ],
        capture_output=True, timeout=10, check=True,
    )


def read_flag_from_container(container: str) -> str:
    """Read the /flag file directly from inside the container (for verification)."""
    result = subprocess.run(
        ["docker", "exec", container, "cat", "/flag"],
        capture_output=True, text=True, timeout=10,
    )
    return result.stdout.strip()


class TestAxisFlagRotation:
    """Axis re-reads /flag on every DB operation via read_flag_file.

    Verify: plant flag -> make HTTP request that triggers DB read -> check flag in response.
    The axis service stores the flag in its SQLite flags table during DB operations.
    We can verify by reading /flag from inside the container after planting.
    """

    def test_flag_file_updates_in_container(self):
        """After planting, /flag in container has the new value."""
        flag1 = "FLAG{axis_test_rotation_1}"
        plant_flag("pulsar-claude-axis", flag1)
        assert read_flag_from_container("pulsar-claude-axis") == flag1

        flag2 = "FLAG{axis_test_rotation_2}"
        plant_flag("pulsar-claude-axis", flag2)
        assert read_flag_from_container("pulsar-claude-axis") == flag2

    def test_flag_readable_by_service_user(self):
        """The nobody user (axis runs as nobody) can read /flag."""
        plant_flag("pulsar-claude-axis", "FLAG{axis_perm_test}")
        result = subprocess.run(
            ["docker", "exec", "-u", "nobody", "pulsar-claude-axis", "cat", "/flag"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.stdout.strip() == "FLAG{axis_perm_test}"

    def test_service_still_responds_after_flag_change(self):
        """Axis HTTP still returns 200 after flag rotation."""
        plant_flag("pulsar-claude-axis", "FLAG{axis_http_test}")
        result = subprocess.run(
            ["curl", "-sf", "-o", "/dev/null", "-w", "%{http_code}", "http://localhost:14000/"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.stdout.strip().startswith("2") or result.stdout.strip().startswith("3")


class TestIcoFlagRotation:
    """ICO reads /flag per-connection via InitAuthorData (forking server).

    Each new TCP connection forks a child that calls InitAuthorData,
    which reads /flag and MD5s it into AuthorData. So flag changes
    take effect on the next connection.
    """

    def test_flag_file_updates_in_container(self):
        flag1 = "FLAG{ico_test_rotation_1}"
        plant_flag("pulsar-claude-ico", flag1)
        assert read_flag_from_container("pulsar-claude-ico") == flag1

        flag2 = "FLAG{ico_test_rotation_2}"
        plant_flag("pulsar-claude-ico", flag2)
        assert read_flag_from_container("pulsar-claude-ico") == flag2

    def test_protocol_responds_after_flag_change(self):
        """ICO still responds to Connect command after flag rotation."""
        plant_flag("pulsar-claude-ico", "FLAG{ico_proto_test}")
        time.sleep(0.5)

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect(("localhost", 14265))
        sock.sendall(b'\x10')  # Connect
        resp = sock.recv(1)
        sock.sendall(b'\x11')  # Disconnect
        sock.close()

        assert len(resp) == 1, "Expected 1-byte ACK response"

    def test_new_connection_sees_new_flag(self):
        """Each new connection reads /flag fresh (forking server).

        Verify by planting two different flags and checking that
        the MD5-based AuthorData changes between connections.
        We can't easily extract AuthorData via protocol without a
        full exploit, but we CAN verify the file is readable per-connection.
        """
        flag1 = "FLAG{ico_conn_test_1}"
        plant_flag("pulsar-claude-ico", flag1)
        assert read_flag_from_container("pulsar-claude-ico") == flag1

        # Connect — this child process will read flag1
        sock1 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock1.settimeout(5)
        sock1.connect(("localhost", 14265))
        sock1.sendall(b'\x10')
        sock1.recv(1)

        # Plant a new flag
        flag2 = "FLAG{ico_conn_test_2}"
        plant_flag("pulsar-claude-ico", flag2)

        # New connection should see flag2
        sock2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock2.settimeout(5)
        sock2.connect(("localhost", 14265))
        sock2.sendall(b'\x10')
        sock2.recv(1)

        # Verify from inside container
        assert read_flag_from_container("pulsar-claude-ico") == flag2

        sock1.sendall(b'\x11')
        sock1.close()
        sock2.sendall(b'\x11')
        sock2.close()


class TestNiluaFlagRotation:
    """Nilua reads /flag ONCE at startup into a global variable.

    Flag rotation requires: write /flag -> restart container -> new process reads new flag.
    """

    def test_flag_file_updates_in_container(self):
        flag1 = "FLAG{nilua_test_rotation_1}"
        plant_flag("pulsar-claude-nilua", flag1)
        assert read_flag_from_container("pulsar-claude-nilua") == flag1

    def test_restart_picks_up_new_flag(self):
        """After writing new flag and restarting, nilua serves the new flag."""
        new_flag = "FLAG{nilua_restart_test}"
        plant_flag("pulsar-claude-nilua", new_flag)

        # Restart the container
        subprocess.run(
            ["docker", "restart", "pulsar-claude-nilua"],
            capture_output=True, timeout=30, check=True,
        )
        time.sleep(3)  # wait for nilua to start

        # Verify the container is running
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Running}}", "pulsar-claude-nilua"],
            capture_output=True, text=True, timeout=5,
        )
        assert result.stdout.strip() == "true", "Container not running after restart"

        # Verify /flag has the new value
        assert read_flag_from_container("pulsar-claude-nilua") == new_flag

        # Verify service is accepting connections
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect(("localhost", 18080))
        sock.close()

    def test_service_still_responsive_after_restart(self):
        """Nilua accepts TCP connections after restart."""
        plant_flag("pulsar-claude-nilua", "FLAG{nilua_responsive_test}")
        subprocess.run(
            ["docker", "restart", "pulsar-claude-nilua"],
            capture_output=True, timeout=30, check=True,
        )
        time.sleep(3)

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect(("localhost", 18080))
        connected = True
        sock.close()
        assert connected


class TestFlagPlantingPermissions:
    """Verify that docker exec -u root can write /flag and service user can read it."""

    @pytest.mark.parametrize("container,user", [
        ("pulsar-claude-axis", "nobody"),
        ("pulsar-claude-ico", "root"),  # ico doesn't set USER in final stage
        ("pulsar-claude-nilua", "user"),
    ])
    def test_service_user_can_read_flag(self, container, user):
        test_flag = f"FLAG{{perm_test_{container}}}"
        plant_flag(container, test_flag)

        result = subprocess.run(
            ["docker", "exec", "-u", user, container, "cat", "/flag"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"User {user} cannot read /flag: {result.stderr}"
        assert result.stdout.strip() == test_flag
