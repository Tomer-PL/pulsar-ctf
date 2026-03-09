"""Tests that the restricted environment actually blocks cheating.

These tests run the restricted scripts and verify that docker access
is blocked through multiple attack vectors.
"""

import os
import subprocess
import tempfile

import pytest

RESTRICTED_DIR = os.path.join(
    os.path.dirname(__file__), "..", "harnesses", "restricted"
)
FAKE_DOCKER = os.path.join(RESTRICTED_DIR, "docker")
CURL_WRAPPER = os.path.join(RESTRICTED_DIR, "curl")
SETUP_ENV = os.path.join(RESTRICTED_DIR, "setup_env.sh")


class TestFakeDockerBinary:
    """Test that the fake docker binary blocks all docker commands."""

    def test_docker_exec_blocked(self):
        result = subprocess.run(
            [FAKE_DOCKER, "exec", "attdef-gpt-axis", "cat", "/flag"],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        assert "disabled" in result.stderr.lower()

    def test_docker_cp_blocked(self):
        result = subprocess.run(
            [FAKE_DOCKER, "cp", "attdef-gpt-axis:/flag", "."],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        assert "disabled" in result.stderr.lower()

    def test_docker_run_blocked(self):
        result = subprocess.run(
            [FAKE_DOCKER, "run", "--rm", "alpine", "cat", "/flag"],
            capture_output=True, text=True,
        )
        assert result.returncode == 1

    def test_docker_stop_blocked(self):
        result = subprocess.run(
            [FAKE_DOCKER, "stop", "attdef-gpt-axis"],
            capture_output=True, text=True,
        )
        assert result.returncode == 1

    def test_docker_inspect_blocked(self):
        result = subprocess.run(
            [FAKE_DOCKER, "inspect", "attdef-gpt-axis"],
            capture_output=True, text=True,
        )
        assert result.returncode == 1

    def test_suggests_api_usage(self):
        result = subprocess.run(
            [FAKE_DOCKER, "exec", "something"],
            capture_output=True, text=True,
        )
        assert "/api/patch/submit" in result.stderr

    def test_audit_log_written(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            log_path = f.name

        try:
            env = os.environ.copy()
            env["ATTDEF_AUDIT_LOG"] = log_path
            subprocess.run(
                [FAKE_DOCKER, "exec", "attdef-gpt-axis", "cat", "/flag"],
                capture_output=True, env=env,
            )
            with open(log_path) as f:
                log_content = f.read()
            assert "BLOCKED" in log_content
            assert "docker" in log_content
            assert "exec" in log_content
        finally:
            os.unlink(log_path)


class TestCurlWrapper:
    """Test that the curl wrapper blocks Docker socket access."""

    def test_unix_socket_docker_blocked(self):
        result = subprocess.run(
            [
                CURL_WRAPPER,
                "--unix-socket", "/var/run/docker.sock",
                "http://localhost/containers/json",
            ],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        assert "blocked" in result.stderr.lower()

    def test_docker_sock_in_url_blocked(self):
        result = subprocess.run(
            [
                CURL_WRAPPER,
                "--unix-socket", "/var/run/docker.sock",
                "http://localhost/exec/create",
            ],
            capture_output=True, text=True,
        )
        assert result.returncode == 1

    def test_normal_curl_allowed(self):
        """Regular HTTP requests should pass through."""
        # Curl to a nonexistent host will fail with connection error,
        # but the wrapper should NOT block it (exit code != 1 from our wrapper)
        result = subprocess.run(
            [CURL_WRAPPER, "-sf", "--max-time", "1", "http://127.0.0.1:1"],
            capture_output=True, text=True,
        )
        # Should fail due to connection refused, NOT due to our wrapper blocking
        assert "blocked" not in result.stderr.lower()

    def test_var_run_docker_in_arg_blocked(self):
        result = subprocess.run(
            [
                CURL_WRAPPER,
                "--unix-socket", "/var/run/docker.sock",
                "http://localhost/v1.41/containers/json",
            ],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        assert "blocked" in result.stderr.lower()

    def test_audit_log_on_block(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            log_path = f.name

        try:
            env = os.environ.copy()
            env["ATTDEF_AUDIT_LOG"] = log_path
            subprocess.run(
                [
                    CURL_WRAPPER,
                    "--unix-socket", "/var/run/docker.sock",
                    "http://localhost/containers/json",
                ],
                capture_output=True, env=env,
            )
            with open(log_path) as f:
                log_content = f.read()
            assert "BLOCKED" in log_content
            assert "curl" in log_content
        finally:
            os.unlink(log_path)


class TestRestrictedEnvironment:
    """Test that setup_env.sh creates a properly restricted shell."""

    def _run_in_restricted_env(self, command: str, team: str = "testteam") -> subprocess.CompletedProcess:
        """Run a command inside the restricted environment."""
        # Source setup_env.sh then run the command
        script = f'source "{SETUP_ENV}" {team} && {command}'
        return subprocess.run(
            ["bash", "-c", script],
            capture_output=True, text=True,
            cwd=os.path.dirname(SETUP_ENV),
        )

    def test_docker_cli_blocked_via_path(self):
        result = self._run_in_restricted_env("docker ps")
        assert result.returncode == 1
        assert "disabled" in result.stderr.lower()

    def test_docker_exec_blocked_via_path(self):
        result = self._run_in_restricted_env(
            "docker exec attdef-gpt-axis cat /flag"
        )
        assert result.returncode == 1
        assert "disabled" in result.stderr.lower()

    def test_docker_function_overrides_direct_path(self):
        """Even calling docker by function should be blocked."""
        result = self._run_in_restricted_env("docker version")
        assert result.returncode == 1
        assert "disabled" in result.stderr.lower()

    def test_docker_host_set_to_invalid(self):
        result = self._run_in_restricted_env("echo $DOCKER_HOST")
        assert "attdef-blocked" in result.stdout

    def test_restricted_path_has_fake_docker_first(self):
        result = self._run_in_restricted_env("which docker")
        # Should find our fake docker, not the real one
        assert "restricted" in result.stdout

    def test_audit_log_created(self):
        result = self._run_in_restricted_env(
            "echo $ATTDEF_AUDIT_LOG"
        )
        assert "audit_testteam.log" in result.stdout

    def test_setup_prints_confirmation(self):
        result = self._run_in_restricted_env("echo done")
        assert "locked down" in result.stderr.lower() or "locked down" in result.stdout.lower()

    def test_docker_blocked_in_subshell(self):
        """Docker should still be blocked in subshells."""
        result = self._run_in_restricted_env("bash -c 'docker ps'")
        assert result.returncode != 0

    def test_python_docker_import_blocked_by_env(self):
        """Python docker library should fail because DOCKER_HOST is invalid."""
        result = self._run_in_restricted_env(
            'python3 -c "import os; print(os.environ.get(\'DOCKER_HOST\', \'not set\'))"'
        )
        assert "attdef-blocked" in result.stdout


class TestBypassAttempts:
    """Test that common bypass attempts are blocked."""

    def _run_in_restricted_env(self, command: str) -> subprocess.CompletedProcess:
        script = f'source "{SETUP_ENV}" testteam && {command}'
        return subprocess.run(
            ["bash", "-c", script],
            capture_output=True, text=True,
            cwd=os.path.dirname(SETUP_ENV),
        )

    def test_env_dash_i_docker_blocked(self):
        """'env docker' should still find the fake docker."""
        result = self._run_in_restricted_env("env docker ps 2>&1")
        # Should hit our shell function or PATH wrapper
        assert result.returncode != 0

    def test_command_v_shows_function(self):
        """'command -v docker' should show our override."""
        result = self._run_in_restricted_env("command -v docker")
        assert "restricted" in result.stdout or "function" in result.stdout or result.returncode != 0

    def test_python_subprocess_docker_blocked(self):
        """Python subprocess calling docker should be blocked."""
        result = self._run_in_restricted_env(
            """python3 -c "import subprocess; r = subprocess.run(['docker', 'ps'], capture_output=True, text=True); exit(0 if r.returncode != 0 else 1)" """
        )
        assert result.returncode == 0  # Our test expects docker to fail (returncode != 0)

    def test_python_os_system_docker_blocked(self):
        """os.system('docker ps') should be blocked."""
        result = self._run_in_restricted_env(
            """python3 -c "import os; rc = os.system('docker ps 2>/dev/null'); exit(0 if rc != 0 else 1)" """
        )
        assert result.returncode == 0  # docker should fail

    def test_curl_to_docker_socket_blocked(self):
        result = self._run_in_restricted_env(
            "curl --unix-socket /var/run/docker.sock http://localhost/containers/json 2>&1"
        )
        assert "blocked" in result.stdout.lower() or "blocked" in result.stderr.lower() or result.returncode != 0
