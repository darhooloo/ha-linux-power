# Linux Power Control for Home Assistant

Power on and off Linux machines on your LAN from Home Assistant:
**Wake-on-LAN** to boot, **SSH** to shut down, **ping polling** for live state.

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
![hassfest](https://github.com/darhooloo/ha-linux-power/workflows/Hassfest/badge.svg)
![hacs](https://github.com/darhooloo/ha-linux-power/workflows/HACS/badge.svg)

## Features

- 🖥️ One controllable switch per Linux host (entity + device in the UI)
- ⚡ Wake-on-LAN magic packet to power on (WOL must be enabled on the NIC)
- 🔌 Configurable shutdown command over SSH (asyncssh, with system-`ssh` fallback)
- 📡 Ping-based state polling every 30 s; boot/shutdown confirmed by background polling
- 🔐 Password stored as a secret field (masked); private-key auth supported
- 🛠️ Shutdown command and ping timeout editable via Options

## Installation

### HACS / Marketplace (recommended)

1. Open **HACS → Integrations → ⋮ → Custom repositories** and add
   `https://github.com/darhooloo/ha-linux-power`, category **Integration**
   (or use the My link once the repo is public).
2. Search for **Linux Power Control** and install.
3. Restart Home Assistant.

### Manual

Copy `custom_components/linux_power/` into `<config>/custom_components/` and restart.

## Configuration

1. **Settings → Devices & Services → Add Integration → Linux Power Control**
2. Fill in:

   | Field | Description |
   |---|---|
   | Host / IP | Address used for ping and SSH |
   | MAC address | For the Wake-on-LAN packet (`AA:BB:CC:DD:EE:FF`) |
   | SSH username | User used for the shutdown command |
   | SSH password | Optional if you use a private key |
   | SSH key path | Absolute path on the **Home Assistant host** |
   | Shutdown command | Default `sudo shutdown -h now` |
   | Ping timeout | Seconds per ping reply, default 2 |

3. A device page is created with a single **Power** switch.

### Passwordless `sudo shutdown`

The shutdown user usually needs sudo without a password. On the target host,
run `visudo -f /etc/sudoers.d/linux-power` and add:

```
youruser ALL=(ALL) NOPASSWD: /sbin/shutdown
```

Or avoid sudo entirely with a rootless sleep command, e.g.
`systemctl suspend` (if allowed) or a user-level helper.

### Enable Wake-on-LAN

```bash
sudo ethtool -s eth0 wol g      # until next boot
# persist via NetworkManager:
nmcli connection modify "Wired 1" 802-3-ethernet.wake-on-lan magic
```

## Security notes

- SSH credentials are stored in Home Assistant's config-entry data; treat your
  HA instance as a secret store. Prefer key-based auth.
- Host key checking is disabled for automation convenience — acceptable on a
  trusted LAN, not across untrusted networks.
- The password is passed to `ssh` through a mode-`0700` askpass helper and an
  environment variable, never on the command line.

## Development

```
custom_components/linux_power/
├── __init__.py       # integration setup / unload
├── config_flow.py    # UI config + options flow
├── const.py          # keys and defaults
├── manifest.json     # HA metadata
├── strings.json      # UI strings
└── switch.py         # WoL / SSH / ping logic
```

CI: `hacs.yml` (HACS validation) and `hassfest.yml` (manifest checks).
Both must pass before submitting to the HACS/Marketplace catalog.

## License

MIT
