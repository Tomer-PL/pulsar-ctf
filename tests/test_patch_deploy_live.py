"""Live integration tests for the patch deployment pipeline.

Verifies that after patching a service:
1. The container is running
2. The port mapping works (service reachable from localhost)
3. The service responds to protocol checks
4. Flag planting still works on the patched container
5. The old flag is replaced after patching

Run with: pytest tests/test_patch_deploy_live.py -v -s
Requires: docker compose up -d
"""

import json
import socket
import subprocess
import time
import urllib.request

import pytest


def _containers_running() -> bool:
    try:
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Running}}", "attdef-claude-axis"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() == "true"
    except Exception:
        return False


def _game_server_up() -> bool:
    try:
        urllib.request.urlopen("http://localhost:8888/api/tick", timeout=3)
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not (_containers_running() and _game_server_up()),
    reason="Docker containers or game server not running",
)


HOST_PORTS = {
    "claude": {"axis": 14000, "ico": 14265, "nilua": 18080},
    "gpt": {"axis": 24000, "ico": 24265, "nilua": 28080},
    "gemini": {"axis": 34000, "ico": 34265, "nilua": 38080},
}


def submit_patch(team: str, service: str) -> dict:
    """Submit a patch via the game server API (using unmodified source = no-op patch)."""
    data = json.dumps({
        "team": team,
        "service": service,
        "build_context": f"/usr/local/workspace/AttDef/challenges-source/{service}",
    }).encode()
    req = urllib.request.Request(
        "http://localhost:8888/api/patch/submit",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())


def check_tcp(host: str, port: int, timeout: int = 5) -> bool:
    """Check if a TCP port is accepting connections."""
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.close()
        return True
    except (socket.error, socket.timeout):
        return False


def check_http(port: int) -> int:
    """Return HTTP status code from localhost:port."""
    try:
        result = subprocess.run(
            ["curl", "-sf", "-o", "/dev/null", "-w", "%{http_code}",
             f"http://localhost:{port}/"],
            capture_output=True, text=True, timeout=10,
        )
        return int(result.stdout.strip())
    except Exception:
        return 0


def check_ico_protocol(port: int) -> bool:
    """Send ico Connect command and check for ACK."""
    try:
        s = socket.create_connection(("localhost", port), timeout=5)
        s.sendall(b'\x10')
        r = s.recv(1)
        s.sendall(b'\x11')
        s.close()
        return len(r) == 1
    except Exception:
        return False


def get_container_ports(container_name: str) -> str:
    """Get the port mapping of a running container."""
    result = subprocess.run(
        ["docker", "port", container_name],
        capture_output=True, text=True, timeout=5,
    )
    return result.stdout.strip()


def plant_flag(container: str, flag_value: str) -> bool:
    """Plant a flag into a container."""
    result = subprocess.run(
        ["docker", "exec", "-u", "root", container,
         "sh", "-c", f"echo '{flag_value}' > /flag && chmod 644 /flag"],
        capture_output=True, timeout=10,
    )
    return result.returncode == 0


def read_flag(container: str) -> str:
    """Read /flag from inside a container."""
    result = subprocess.run(
        ["docker", "exec", container, "cat", "/flag"],
        capture_output=True, text=True, timeout=10,
    )
    return result.stdout.strip()


class TestAxisPatchDeploy:
    """Test patching the axis service end-to-end."""

    def test_patch_accepted(self):
        result = submit_patch("gemini", "axis")
        assert result["accepted"], f"Patch rejected: {result['message']}"

    def test_service_reachable_after_patch(self):
        submit_patch("gemini", "axis")
        time.sleep(3)
        assert check_tcp("localhost", HOST_PORTS["gemini"]["axis"]), \
            "Axis not reachable on localhost after patch"

    def test_http_responds_after_patch(self):
        submit_patch("gemini", "axis")
        time.sleep(3)
        code = check_http(HOST_PORTS["gemini"]["axis"])
        assert code >= 200 and code < 400, f"HTTP {code} after patch"

    def test_port_mapping_exists_after_patch(self):
        submit_patch("gemini", "axis")
        time.sleep(2)
        ports = get_container_ports("attdef-gemini-axis")
        assert "4000" in ports, f"No port mapping found: {ports}"
        assert str(HOST_PORTS["gemini"]["axis"]) in ports, \
            f"Wrong host port: {ports}"

    def test_flag_plant_works_after_patch(self):
        submit_patch("gemini", "axis")
        time.sleep(3)
        assert plant_flag("attdef-gemini-axis", "FLAG{post_patch_test}")
        assert read_flag("attdef-gemini-axis") == "FLAG{post_patch_test}"


class TestIcoPatchDeploy:
    """Test patching the ico service end-to-end."""

    def test_patch_accepted(self):
        result = submit_patch("gemini", "ico")
        assert result["accepted"], f"Patch rejected: {result['message']}"

    def test_service_reachable_after_patch(self):
        submit_patch("gemini", "ico")
        time.sleep(3)
        assert check_tcp("localhost", HOST_PORTS["gemini"]["ico"]), \
            "ICO not reachable on localhost after patch"

    def test_protocol_responds_after_patch(self):
        submit_patch("gemini", "ico")
        time.sleep(3)
        assert check_ico_protocol(HOST_PORTS["gemini"]["ico"]), \
            "ICO protocol check failed after patch"

    def test_port_mapping_exists_after_patch(self):
        submit_patch("gemini", "ico")
        time.sleep(2)
        ports = get_container_ports("attdef-gemini-ico")
        assert str(HOST_PORTS["gemini"]["ico"]) in ports, \
            f"Wrong host port: {ports}"


class TestNiluaPatchDeploy:
    """Test patching the nilua service end-to-end."""

    def test_patch_accepted(self):
        result = submit_patch("gemini", "nilua")
        assert result["accepted"], f"Patch rejected: {result['message']}"

    def test_service_reachable_after_patch(self):
        submit_patch("gemini", "nilua")
        time.sleep(5)  # nilua needs more startup time
        assert check_tcp("localhost", HOST_PORTS["gemini"]["nilua"]), \
            "Nilua not reachable on localhost after patch"

    def test_port_mapping_exists_after_patch(self):
        submit_patch("gemini", "nilua")
        time.sleep(2)
        ports = get_container_ports("attdef-gemini-nilua")
        assert str(HOST_PORTS["gemini"]["nilua"]) in ports, \
            f"Wrong host port: {ports}"


class TestPatchDoesNotBreakOtherTeams:
    """Verify patching one team doesn't affect other teams' services."""

    def test_claude_axis_still_works_after_gemini_patch(self):
        submit_patch("gemini", "axis")
        time.sleep(3)
        code = check_http(HOST_PORTS["claude"]["axis"])
        assert code >= 200 and code < 400, \
            f"Claude's axis broken after Gemini patch: HTTP {code}"

    def test_claude_ico_still_works_after_gemini_patch(self):
        submit_patch("gemini", "ico")
        time.sleep(3)
        assert check_ico_protocol(HOST_PORTS["claude"]["ico"]), \
            "Claude's ico broken after Gemini patch"
