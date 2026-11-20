"""Switch platform for Linux Power."""

from __future__ import annotations

import asyncio
import datetime
import logging
import os
import shutil
import socket
import tempfile

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import (
    CONNECTION_NETWORK_MAC,
    DeviceEntryType,
    DeviceInfo,
)
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

try:
    import asyncssh
except ImportError:  # pragma: no cover - optional at runtime, declared in manifest
    asyncssh = None

from .const import (
    CONF_HOST,
    CONF_MAC,
    CONF_PASSWORD,
    CONF_PING_TIMEOUT,
    CONF_SHUTDOWN_COMMAND,
    CONF_SSH_KEY,
    CONF_SSH_PORT,
    CONF_USERNAME,
    DEFAULT_SSH_PORT,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL_SECONDS = 30
POWER_ON_POLL_ATTEMPTS = 30
POWER_OFF_POLL_ATTEMPTS = 15
POLL_INTERVAL_SECONDS = 2

# A shutdown command tears down its own SSH connection, so a dropped or
# reset connection right after issuing it is a success, not a failure.
_DROP_MARKERS = (
    "connection reset",
    "broken pipe",
    "connection closed",
    "connection terminated",
    "eof",
)
_SHUTDOWN_MARKERS = ("system is going down", "shutdown scheduled")
_AUTH_MARKERS = ("authentication", "permission denied")


def _mac_to_bytes(mac: str) -> bytes:
    cleaned = mac.replace(":", "").replace("-", "").strip()
    if len(cleaned) != 12:
        raise ValueError(f"Invalid MAC address: {mac}")
    return bytes.fromhex(cleaned)


def send_wol(mac: str, broadcast: str = "255.255.255.255", port: int = 9) -> None:
    """Send a Wake-on-LAN magic packet."""
    magic = b"\xff" * 6 + _mac_to_bytes(mac) * 16
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        sock.sendto(magic, (broadcast, port))
    finally:
        sock.close()


async def async_ping(host: str, timeout: int) -> bool:
    """Ping a host once; return True if reachable."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ping",
            "-c",
            "1",
            "-W",
            str(timeout),
            host,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=timeout + 2)
        return proc.returncode == 0
    except (OSError, asyncio.TimeoutError) as exc:
        _LOGGER.debug("Ping failed for %s: %s", host, exc)
        return False


def _looks_like_drop(text: str) -> bool:
    return any(marker in text for marker in _DROP_MARKERS)


async def _ssh_shutdown_asyncssh(
    host: str,
    username: str,
    password: str | None,
    ssh_key: str | None,
    ssh_port: int,
    command: str,
) -> bool | None:
    """Run the shutdown command via asyncssh.

    Returns True/False for a decided outcome, or None to fall back to
    the system ssh binary.
    """
    if asyncssh is None:
        return None

    connect_kwargs: dict = {
        "host": host,
        "port": ssh_port,
        "username": username,
        "known_hosts": None,
    }
    if ssh_key:
        connect_kwargs["client_keys"] = [ssh_key]
    if password and not ssh_key:
        connect_kwargs["password"] = password

    try:
        async with asyncssh.connect(**connect_kwargs) as conn:
            result = await conn.run(command, check=False)
    except (asyncssh.Error, OSError) as exc:
        msg = str(exc).lower()
        _LOGGER.debug("asyncssh raised: %s", msg)
        if any(marker in msg for marker in _AUTH_MARKERS):
            _LOGGER.error("SSH authentication failed: %s", exc)
            return False
        if _looks_like_drop(msg):
            # Connection dropped during shutdown is an expected success.
            return True
        return None

    out = str(getattr(result, "stdout", "") or "")
    err = str(getattr(result, "stderr", "") or "")
    rc = getattr(result, "exit_status", 0)
    _LOGGER.info(
        "asyncssh rc=%s stdout=%s stderr=%s", rc, out.strip(), err.strip()
    )
    low = f"{err} {out}".lower()
    return (
        rc == 0
        or any(marker in low for marker in _SHUTDOWN_MARKERS)
    )


async def _ssh_shutdown_system(
    host: str,
    username: str,
    password: str | None,
    ssh_key: str | None,
    ssh_port: int,
    command: str,
) -> bool:
    """Run the shutdown command with the system ssh binary.

    Password auth goes through SSH_ASKPASS; no secret is ever placed on
    the command line.
    """
    ssh_bin = shutil.which("ssh") or "/usr/bin/ssh"
    env = dict(os.environ)
    ssh_opts = [
        ssh_bin,
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "ConnectTimeout=10",
        "-p",
        str(ssh_port),
    ]
    if ssh_key:
        ssh_opts += ["-i", ssh_key]

    askpass_path = None
    if password and not ssh_key:
        fd, askpass_path = tempfile.mkstemp(prefix="linux_power_askpass_")
        with os.fdopen(fd, "w") as askpass_file:
            askpass_file.write("#!/bin/sh\necho \"$LINUX_POWER_SSH_PASSWORD\"\n")
        os.chmod(askpass_path, 0o700)
        env["SSH_ASKPASS"] = askpass_path
        env["SSH_ASKPASS_REQUIRE"] = "force"
        env["LINUX_POWER_SSH_PASSWORD"] = password

    try:
        proc = await asyncio.create_subprocess_exec(
            *(ssh_opts + [f"{username}@{host}", command]),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        except asyncio.TimeoutError:
            _LOGGER.info(
                "SSH timed out (connection dropped by shutdown) - success"
            )
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            return True

        out = (stdout or b"").decode(errors="ignore")
        err = (stderr or b"").decode(errors="ignore")
        _LOGGER.info(
            "system ssh rc=%s stdout=%s stderr=%s",
            proc.returncode,
            out.strip(),
            err.strip(),
        )
        low = f"{err} {out}".lower()
        if proc.returncode == 0:
            return True
        if any(marker in low for marker in _SHUTDOWN_MARKERS):
            return True
        if _looks_like_drop(low):
            return True
        _LOGGER.error("SSH shutdown failed: %s", err.strip() or out.strip())
        return False
    except OSError as exc:
        _LOGGER.error("Failed to run system ssh: %s", exc)
        return False
    finally:
        if askpass_path:
            try:
                os.remove(askpass_path)
            except OSError:
                pass


async def async_ssh_shutdown(
    host: str,
    username: str,
    password: str | None,
    ssh_key: str | None,
    ssh_port: int,
    command: str,
) -> bool:
    """Shut a host down over SSH, preferring asyncssh."""
    _LOGGER.info("Shutting down %s via SSH: %s", host, command)
    decided = await _ssh_shutdown_asyncssh(
        host, username, password, ssh_key, ssh_port, command
    )
    if decided is not None:
        return decided
    return await _ssh_shutdown_system(
        host, username, password, ssh_key, ssh_port, command
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Linux Power switch platform."""
    coordinator = LinuxPowerCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    async_add_entities([LinuxPowerSwitch(coordinator, entry)])


class LinuxPowerCoordinator(DataUpdateCoordinator[bool]):
    """Poll the host with ping to track its power state."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise the coordinator."""
        self.entry = entry
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{entry.data.get(CONF_HOST)}",
            update_interval=datetime.timedelta(seconds=SCAN_INTERVAL_SECONDS),
        )

    @property
    def host(self) -> str:
        return self.entry.data[CONF_HOST]

    @property
    def ping_timeout(self) -> int:
        return self.entry.options.get(
            CONF_PING_TIMEOUT, self.entry.data.get(CONF_PING_TIMEOUT, 2)
        )

    async def _async_update_data(self) -> bool:
        try:
            return await async_ping(self.host, self.ping_timeout)
        except (OSError, asyncio.TimeoutError) as exc:
            raise UpdateFailed(str(exc)) from exc


class LinuxPowerSwitch(CoordinatorEntity[LinuxPowerCoordinator], SwitchEntity):
    """A switch that powers a Linux host on (WoL) and off (SSH)."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_translation_key = "power"

    def __init__(
        self, coordinator: LinuxPowerCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialise the switch."""
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = entry.entry_id
        host = entry.data[CONF_HOST]
        mac = entry.data[CONF_MAC]
        self._attr_device_info = DeviceInfo(
            connections={(CONNECTION_NETWORK_MAC, mac.lower())},
            name=host,
            manufacturer="Linux",
            model="Power control (WoL / SSH)",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data)

    async def _wait_for_state(self, want_up: bool) -> None:
        host = self._entry.data[CONF_HOST]
        timeout = self.coordinator.ping_timeout
        attempts = (
            POWER_ON_POLL_ATTEMPTS if want_up else POWER_OFF_POLL_ATTEMPTS
        )
        for _ in range(attempts):
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            if await async_ping(host, timeout) is want_up:
                break
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs) -> None:
        """Wake the host and keep polling in the background."""
        mac = self._entry.data[CONF_MAC]
        try:
            await self.hass.async_add_executor_job(send_wol, mac)
        except (ValueError, OSError) as exc:
            raise HomeAssistantError(
                f"Failed to send Wake-on-LAN packet to {mac}: {exc}"
            ) from exc
        self.hass.async_create_background_task(
            self._wait_for_state(True),
            f"{DOMAIN}_boot_{self._entry.entry_id}",
        )

    async def async_turn_off(self, **kwargs) -> None:
        """Shut the host down over SSH."""
        data = self._entry.data
        command = self._entry.options.get(
            CONF_SHUTDOWN_COMMAND,
            data.get(CONF_SHUTDOWN_COMMAND, "sudo shutdown -h now"),
        )
        ok = await async_ssh_shutdown(
            host=data[CONF_HOST],
            username=data[CONF_USERNAME],
            password=data.get(CONF_PASSWORD),
            ssh_key=data.get(CONF_SSH_KEY),
            ssh_port=data.get(CONF_SSH_PORT, DEFAULT_SSH_PORT),
            command=command,
        )
        if not ok:
            raise HomeAssistantError(
                f"Failed to shut down {data[CONF_HOST]} via SSH"
            )
        self.hass.async_create_background_task(
            self._wait_for_state(False),
            f"{DOMAIN}_shutdown_{self._entry.entry_id}",
        )
