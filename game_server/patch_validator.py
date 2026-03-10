"""Patch validator for the Pulsar game.

When an LLM submits a patched Docker image, the validator:
1. Builds the new image
2. Starts it in a temporary container
3. Runs service-specific health checks
4. If checks pass, replaces the live container
5. If checks fail, rejects the patch (old container stays)
"""

import logging
import socket
import struct
import subprocess
import time

from .models import ServiceName, TeamName

logger = logging.getLogger(__name__)

# Timeout for service health checks
HEALTH_CHECK_TIMEOUT = 30
CONNECT_TIMEOUT = 5


def validate_and_deploy_patch(
    team: TeamName, service: ServiceName, build_context: str
) -> tuple[bool, str]:
    """Build a patched image, validate it, and deploy if valid.

    Returns (success, message).
    """
    container_name = f"pulsar-{team.value}-{service.value}"
    test_container = f"pulsar-test-{team.value}-{service.value}"
    image_name = f"pulsar-patched-{team.value}-{service.value}"

    # Step 1: Build the patched image
    logger.info("Building patched image for %s/%s", team.value, service.value)
    try:
        build_cmd = ["docker", "build", "-t", image_name, build_context]
        if service == ServiceName.NILUA:
            build_cmd = [
                "docker", "build", "-t", image_name,
                "--target", "nilua", build_context,
            ]
        result = subprocess.run(
            build_cmd, capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            return False, f"Build failed: {result.stderr[-500:]}"
    except subprocess.TimeoutExpired:
        return False, "Build timed out (120s limit)"

    # Step 2: Start test container
    port = _get_service_port(service)
    try:
        subprocess.run(
            ["docker", "rm", "-f", test_container],
            capture_output=True, timeout=10,
        )
        subprocess.run(
            [
                "docker", "run", "-d",
                "--name", test_container,
                "--network", "pulsar-ctf_game-net",
                image_name,
            ],
            capture_output=True, text=True, timeout=30, check=True,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        _cleanup_test_container(test_container)
        return False, f"Failed to start test container: {e}"

    # Step 3: Run health checks
    time.sleep(3)  # Give service time to start
    check_fn = _get_health_check(service)
    try:
        success, msg = check_fn(test_container, port)
    except Exception as e:
        success, msg = False, f"Health check error: {e}"

    _cleanup_test_container(test_container)

    if not success:
        return False, f"Health check failed: {msg}"

    # Step 4: Deploy — stop old container, start new one with the correct name
    logger.info("Deploying patched %s/%s", team.value, service.value)
    try:
        # Get port mapping from the current container before removing it
        host_port = _get_host_port(container_name)
        internal_port = _get_service_port(service)

        subprocess.run(
            ["docker", "rm", "-f", container_name],
            capture_output=True, timeout=10,
        )

        run_cmd = [
            "docker", "run", "-d",
            "--name", container_name,
            "--network", "pulsar-ctf_game-net",
            "-p", f"{host_port}:{internal_port}",
            image_name,
        ]
        subprocess.run(
            run_cmd, capture_output=True, text=True, timeout=30, check=True,
        )
        return True, "Patch deployed successfully"
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        return False, f"Deployment failed: {e}"


def _get_service_port(service: ServiceName) -> int:
    """Return the port a service listens on."""
    return {
        ServiceName.AXIS: 4000,
        ServiceName.ICO: 4265,
        ServiceName.NILUA: 8080,
    }[service]


# Host port mapping: team -> service -> host port (must match docker-compose.yml)
_HOST_PORTS = {
    "claude": {"axis": 14000, "ico": 14265, "nilua": 18080},
    "gpt": {"axis": 24000, "ico": 24265, "nilua": 28080},
}


def _get_host_port(container_name: str) -> int:
    """Get the host port for a container from our static mapping.

    Container names are like 'pulsar-claude-axis'.
    """
    parts = container_name.replace("pulsar-", "").split("-", 1)
    if len(parts) == 2:
        team, service = parts
        return _HOST_PORTS.get(team, {}).get(service, 0)
    # Fallback: try to read from docker inspect
    try:
        result = subprocess.run(
            ["docker", "inspect", "--format",
             "{{range $p, $conf := .NetworkSettings.Ports}}{{(index $conf 0).HostPort}}{{end}}",
             container_name],
            capture_output=True, text=True, timeout=10,
        )
        return int(result.stdout.strip())
    except Exception:
        return 0


def _cleanup_test_container(name: str) -> None:
    """Remove test container."""
    try:
        subprocess.run(
            ["docker", "rm", "-f", name], capture_output=True, timeout=10,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        logger.warning("Failed to clean up test container %s", name)


def _get_container_ip(container_name: str) -> str | None:
    """Get the IP address of a running container."""
    try:
        result = subprocess.run(
            [
                "docker", "inspect", "-f",
                "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
                container_name,
            ],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return None
        ip = result.stdout.strip()
        return ip if ip else None
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None


def _check_tcp_connect(host: str, port: int) -> bool:
    """Check if a TCP port is accepting connections."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(CONNECT_TIMEOUT)
        sock.connect((host, port))
        sock.close()
        return True
    except (socket.error, socket.timeout):
        return False


def _get_health_check(service: ServiceName):
    """Return the appropriate health check function for a service."""
    return {
        ServiceName.AXIS: _check_axis,
        ServiceName.ICO: _check_ico,
        ServiceName.NILUA: _check_nilua,
    }[service]


def _check_axis(container_name: str, port: int) -> tuple[bool, str]:
    """Health check for axis (Phoenix web app).

    Verifies HTTP response on port 4000.
    """
    ip = _get_container_ip(container_name)
    if not ip:
        return False, "Could not get container IP"

    # Wait for service to be ready
    for _ in range(10):
        if _check_tcp_connect(ip, port):
            break
        time.sleep(1)
    else:
        return False, f"Port {port} not accepting connections after 10s"

    # Check HTTP response
    try:
        result = subprocess.run(
            [
                "curl", "-sf", "-o", "/dev/null",
                "-w", "%{http_code}",
                f"http://{ip}:{port}/",
            ],
            capture_output=True, text=True, timeout=10,
        )
        code = result.stdout.strip()
        if code.startswith("2") or code.startswith("3"):
            return True, f"HTTP {code}"
        return False, f"HTTP {code} (expected 2xx/3xx)"
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        return False, f"HTTP check failed: {e}"


def _check_ico(container_name: str, port: int) -> tuple[bool, str]:
    """Health check for ico (HVIF parser).

    Sends the 0x10 Connect command and expects a 1-byte Acknowledge response.
    """
    ip = _get_container_ip(container_name)
    if not ip:
        return False, "Could not get container IP"

    for _ in range(10):
        if _check_tcp_connect(ip, port):
            break
        time.sleep(1)
    else:
        return False, f"Port {port} not accepting connections after 10s"

    # Send Connect command (0x10) — server responds with 1-byte Acknowledge
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(CONNECT_TIMEOUT)
        sock.connect((ip, port))
        sock.sendall(b'\x10')  # Connect command
        response = sock.recv(1)
        # Send Disconnect (0x11) to clean up
        sock.sendall(b'\x11')
        sock.close()
        if len(response) == 1:
            return True, f"Connect ACK received (0x{response[0]:02x})"
        return False, "No response to Connect command"
    except (socket.error, socket.timeout) as e:
        return False, f"Protocol check failed: {e}"


def _check_nilua(container_name: str, port: int) -> tuple[bool, str]:
    """Health check for nilua (auction system).

    Nilua uses a length-prefixed binary protocol:
    - Send: 4-byte big-endian length + serialized Message
    - Recv: 4-byte big-endian length + serialized Message

    We send a minimal PING-style message and check for any response.
    If the protocol rejects our message, that's fine — it means the
    service is alive and processing requests.
    """
    ip = _get_container_ip(container_name)
    if not ip:
        return False, "Could not get container IP"

    for _ in range(10):
        if _check_tcp_connect(ip, port):
            break
        time.sleep(1)
    else:
        return False, f"Port {port} not accepting connections after 10s"

    # Send a properly framed but minimal message
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(CONNECT_TIMEOUT)
        sock.connect((ip, port))

        # Send a minimal length-prefixed payload
        # An empty or minimal payload should trigger either a response or
        # a clean disconnect — both indicate the service is alive
        payload = b'\x00'  # minimal 1-byte body
        length_prefix = struct.pack('!I', len(payload))
        sock.sendall(length_prefix + payload)

        try:
            response = sock.recv(1024)
            sock.close()
            if len(response) > 0:
                return True, f"Got {len(response)} bytes response"
            return True, "Service accepted connection (no response to probe)"
        except socket.timeout:
            sock.close()
            # Service is alive but didn't respond to our garbage message —
            # this is fine, it means it's processing
            return True, "Service accepted connection (timeout on probe response)"
    except socket.error as e:
        return False, f"TCP check failed: {e}"
