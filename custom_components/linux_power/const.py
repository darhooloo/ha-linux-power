"""Constants for the Linux Power integration."""

from homeassistant.const import Platform

DOMAIN = "linux_power"

CONF_HOST = "host"
CONF_MAC = "mac"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_SSH_PORT = "ssh_port"
CONF_SSH_KEY = "ssh_key"
CONF_SHUTDOWN_COMMAND = "shutdown_command"
CONF_PING_TIMEOUT = "ping_timeout"

DEFAULT_SSH_PORT = 22
DEFAULT_SHUTDOWN_COMMAND = "sudo shutdown -h now"
DEFAULT_PING_TIMEOUT = 2

PLATFORMS = [Platform.SWITCH]
