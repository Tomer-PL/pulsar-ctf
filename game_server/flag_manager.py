"""Flag generation, planting, and validation."""

import logging
import subprocess

from .models import (
    AttackPoint,
    Flag,
    FlagSubmission,
    GameState,
    ServiceName,
    TeamName,
)

logger = logging.getLogger(__name__)


class FlagManager:
    """Manages flag lifecycle: generation, planting, and submission validation."""

    def __init__(self, state: GameState):
        self.state = state

    def generate_tick_flags(self) -> list[Flag]:
        """Generate flags for all teams and services for the current tick."""
        flags = []
        for team in self.state.config.teams:
            for service in self.state.config.services:
                flag = Flag.generate(team, service, self.state.current_tick)
                flags.append(flag)
        return flags

    def plant_flags(self, flags: list[Flag]) -> dict[str, bool]:
        """Plant flags into running service containers.

        Returns a dict of flag_value -> success for each flag.
        """
        results = {}
        # Track which nilua containers need restart (flag read at startup only)
        nilua_restart_needed: set[str] = set()

        for flag in flags:
            container = f"attdef-{flag.team.value}-{flag.service.value}"
            success = self._write_flag_to_container(container, flag)
            if success:
                self.state.active_flags[flag.value] = flag
                results[flag.value] = True
                logger.info(
                    "FLAG_PLANTED team=%s service=%s tick=%d flag=%s",
                    flag.team.value,
                    flag.service.value,
                    flag.tick,
                    flag.value[:20] + "...",
                )
                if flag.service == ServiceName.NILUA:
                    nilua_restart_needed.add(container)
            else:
                results[flag.value] = False
                logger.error(
                    "FLAG_PLANT_FAILED team=%s service=%s tick=%d",
                    flag.team.value,
                    flag.service.value,
                    flag.tick,
                )

        # Restart nilua containers so they re-read /flag from disk
        for container in nilua_restart_needed:
            self._restart_container(container)

        return results

    def _write_flag_to_container(self, container_name: str, flag: Flag) -> bool:
        """Write a flag file into a Docker container.

        Runs as root (-u root) to ensure write access regardless of
        the container's default user. Sets the file world-readable
        so the service process (running as unprivileged user) can read it.
        """
        try:
            subprocess.run(
                [
                    "docker", "exec", "-u", "root",
                    container_name,
                    "sh", "-c",
                    f"echo '{flag.value}' > /flag && chmod 644 /flag",
                ],
                capture_output=True,
                timeout=10,
                check=True,
            )
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logger.error(
                "FLAG_WRITE_ERROR container=%s error=%s", container_name, e
            )
            return False

    def _restart_container(self, container_name: str) -> bool:
        """Restart a container so it re-reads /flag.

        Used for services like nilua that only read the flag at startup.
        """
        try:
            subprocess.run(
                ["docker", "restart", container_name],
                capture_output=True,
                timeout=30,
                check=True,
            )
            logger.info("CONTAINER_RESTARTED container=%s", container_name)
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logger.error(
                "CONTAINER_RESTART_FAILED container=%s error=%s",
                container_name, e,
            )
            return False

    def validate_submission(self, submission: FlagSubmission) -> AttackPoint | None:
        """Validate a flag submission and return an AttackPoint if valid."""
        flag = self.state.active_flags.get(submission.flag_value)

        if flag is None:
            logger.info(
                "FLAG_REJECTED reason=unknown team=%s flag=%s",
                submission.submitting_team.value,
                submission.flag_value[:30],
            )
            return None

        # Can't submit your own flag
        if flag.team == submission.submitting_team:
            logger.info(
                "FLAG_REJECTED reason=own_flag team=%s service=%s",
                submission.submitting_team.value,
                flag.service.value,
            )
            return None

        # Check flag is still within lifetime
        tick_age = self.state.current_tick - flag.tick
        if tick_age >= self.state.config.flag_lifetime_ticks:
            logger.info(
                "FLAG_REJECTED reason=expired team=%s age=%d",
                submission.submitting_team.value,
                tick_age,
            )
            return None

        # Check for duplicate submission (same attacker, same flag)
        for existing in self.state.attack_log:
            if (
                existing.attacker == submission.submitting_team
                and existing.flag_value == submission.flag_value
            ):
                logger.info(
                    "FLAG_REJECTED reason=duplicate team=%s",
                    submission.submitting_team.value,
                )
                return None

        # Valid attack!
        attack = AttackPoint(
            attacker=submission.submitting_team,
            victim=flag.team,
            service=flag.service,
            tick=self.state.current_tick,
            flag_value=submission.flag_value,
        )
        self.state.attack_log.append(attack)

        # Track which teams got exploited this tick
        self.state.exploited_this_tick[flag.service.value].add(flag.team.value)

        logger.info(
            "FLAG_ACCEPTED attacker=%s victim=%s service=%s tick=%d",
            submission.submitting_team.value,
            flag.team.value,
            flag.service.value,
            self.state.current_tick,
        )
        return attack

    def expire_old_flags(self) -> int:
        """Remove flags that have exceeded their lifetime. Returns count removed."""
        to_remove = []
        for value, flag in self.state.active_flags.items():
            if self.state.current_tick - flag.tick >= self.state.config.flag_lifetime_ticks:
                to_remove.append(value)

        for value in to_remove:
            del self.state.active_flags[value]

        if to_remove:
            logger.info("FLAGS_EXPIRED count=%d tick=%d", len(to_remove), self.state.current_tick)

        return len(to_remove)
