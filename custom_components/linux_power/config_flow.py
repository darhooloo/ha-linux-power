"""Config flow for Linux Power."""

from __future__ import annotations

import re
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    SecretTextSelector,
    TextSelector,
)

from .const import (
    CONF_HOST,
    CONF_MAC,
    CONF_PASSWORD,
    CONF_PING_TIMEOUT,
    CONF_SHUTDOWN_COMMAND,
    CONF_SSH_KEY,
    CONF_SSH_PORT,
    CONF_USERNAME,
    DEFAULT_PING_TIMEOUT,
    DEFAULT_SHUTDOWN_COMMAND,
    DEFAULT_SSH_PORT,
    DOMAIN,
)

MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$")


class LinuxPowerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Linux Power."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if not MAC_RE.match(user_input[CONF_MAC]):
                errors[CONF_MAC] = "invalid_mac"
            else:
                await self.async_set_unique_id(user_input[CONF_HOST].lower())
                self._abort_if_unique_id_configured()
                user_input[CONF_MAC] = user_input[CONF_MAC].upper().replace("-", ":")
                return self.async_create_entry(title=user_input[CONF_HOST], data=user_input)

        data_schema = vol.Schema(
            {
                vol.Required(CONF_HOST): TextSelector(),
                vol.Required(CONF_MAC): TextSelector(),
                vol.Required(CONF_USERNAME): TextSelector(),
                vol.Optional(CONF_PASSWORD): SecretTextSelector(),
                vol.Optional(CONF_SSH_PORT, default=DEFAULT_SSH_PORT): NumberSelector(
                    NumberSelectorConfig(min=1, max=65535, step=1)
                ),
                vol.Optional(CONF_SSH_KEY): TextSelector(),
                vol.Optional(
                    CONF_SHUTDOWN_COMMAND, default=DEFAULT_SHUTDOWN_COMMAND
                ): TextSelector(),
                vol.Optional(
                    CONF_PING_TIMEOUT, default=DEFAULT_PING_TIMEOUT
                ): NumberSelector(NumberSelectorConfig(min=1, max=30, step=1)),
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> LinuxPowerOptionsFlow:
        return LinuxPowerOptionsFlow(config_entry)


class LinuxPowerOptionsFlow(OptionsFlow):
    """Handle Linux Power options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        data_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SHUTDOWN_COMMAND,
                    default=self.config_entry.options.get(
                        CONF_SHUTDOWN_COMMAND,
                        self.config_entry.data.get(
                            CONF_SHUTDOWN_COMMAND, DEFAULT_SHUTDOWN_COMMAND
                        ),
                    ),
                ): TextSelector(),
                vol.Optional(
                    CONF_PING_TIMEOUT,
                    default=self.config_entry.options.get(
                        CONF_PING_TIMEOUT,
                        self.config_entry.data.get(
                            CONF_PING_TIMEOUT, DEFAULT_PING_TIMEOUT
                        ),
                    ),
                ): NumberSelector(NumberSelectorConfig(min=1, max=30, step=1)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=data_schema)
