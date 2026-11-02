# Pi Eyes

Change the style of [Adafruit's Animated Eyes Bonnet](https://www.adafruit.com/product/3813) from a webpage or Home Assistant, on a Raspberry Pi 3.

Adafruit's `eyes.py` can't change style while running, so this adds:

- **A supervisor** that runs the unmodified `eyes.py` from the selected style's folder, and restarts it when the style changes. A style that fails at startup falls back to the last good one.
- **A control service** with a web UI, REST API and Home Assistant entity (MQTT discovery).

## Hardware

You need the bonnet, two [1.44" 128x128 TFT displays](https://www.adafruit.com/product/2088) (ST7735R), jumper wires, a Pi 3B or 3B+, a microSD card, a Pi 3 power supply (5V 2.5A) and a soldering kit.

1. Solder the bonnet and display headers, following [Adafruit's assembly guide](https://learn.adafruit.com/animated-snake-eyes-bonnet-for-raspberry-pi/hardware-assembly).
2. Seat the bonnet on the Pi with the power off.
3. Wire each display to the **lower "TFT" rows**. Each has 11 pins, mapped one-to-one with no crossed wires. Trace each wire end to end, because the colours repeat.
4. Mount the displays with the **breakout pins along the top edge**. Other rotations aren't handled.
5. Keep the wires short, and peel the film off the displays when finished.

## Install Adafruit's software

The installer is one-way, so give it a dedicated SD card.

1. Flash **Raspberry Pi OS Trixie Desktop** with Raspberry Pi Imager (Lite isn't supported). In Imager, set the hostname to `pi-eyes` and turn on SSH and Wi-Fi.
2. Over SSH:

   ```sh
   sudo apt update && sudo apt full-upgrade -y && sudo reboot
   ```

3. Reconnect, then:

   ```sh
   sudo apt install -y python3-venv wget git
   python -m venv env --system-site-packages
   source env/bin/activate
   pip3 install adafruit-python-shell
   wget https://github.com/adafruit/Raspberry-Pi-Installer-Scripts/raw/main/pi-eyes.py
   sudo -E env PATH=$PATH python3 pi-eyes.py
   ```

4. Answer the prompts:

   | Prompt | Answer | Notes |
   |---|---|---|
   | Screen type | `TFT 128x128 (ST7735)` | |
   | GPIO-halt utility | `n` | If you add a shutdown button, don't use the suggested GPIO 21: the left eye uses GPIO 19-21 |
   | Bonnet ADC support | `n` | Only for a joystick or light sensor |
   | USB Ethernet gadget | `n` | Pi Zero only |
   | Proceed | `y` | Takes 10-15 minutes, then reboots |

**Check both eyes animate before continuing.** For snow, tearing or inverted colours, lower the bitrate by adding `-b` to `ExecStart` with `sudo systemctl edit --full pi-eyes-fbx2` (the TFT default is 12000000, so try `-t -b 10000000`). Ignore the guide's `rc.local` and `/boot/Pi_Eyes` instructions, which predate the current installer.

## Install style control

```sh
git clone https://github.com/craigusus/pi-eyes.git
cd pi-eyes
sudo bash deploy/install.sh
```

Then open `http://pi-eyes.local:8080`.

To update later, run `git pull` and the install script again.

## Home Assistant

1. Install the Mosquitto broker add-on and the MQTT integration if you don't have them, and create a user for the Pi.
2. Fill in the `[mqtt]` section of `/etc/pi-eyes/control.toml`:

   ```toml
   [mqtt]
   host = "homeassistant.local"
   port = 1883
   username = "pi-eyes"
   password = "your-password"
   ```

3. Run `sudo systemctl restart pi-eyes-control`.

A **Pi Eyes** device appears with a `select.pi_eyes_style` entity. Add it to a dashboard, or use it in automations:

```yaml
action: select.select_option
target:
  entity_id: select.pi_eyes_style
data:
  option: dragon
```

The entity shows the style actually running. If a style fails and the eyes fall back, it shows the fallback.

## Security

The web UI and API have **no login**. Anyone on your network can change the eyes and upload or delete styles, so don't expose port 8080 to the internet. Requests from other websites are refused, and uploads are re-encoded before use.

## Styles

Built in: `default` and `dragon` from Adafruit, plus `blue`, `green` and `red` recoloured from `default`.

### Adding a style from the webpage

Upload a square JPEG or PNG iris, and optionally a sclera. Eye shape comes from a built-in style you choose.

The iris is an **unwrapped texture, not a picture of an eye**. The top edge meets the pupil, the bottom edge is the outside of the iris, and left to right runs once around the eye. A normal photo comes out swirled, so start by editing Adafruit's `graphics/iris.jpg`.

The left eye's texture is offset by half its width, so the two eyes don't look identical.

### Adding a style over SSH

For a custom shape, create `/var/lib/pi-eyes/styles/<name>/graphics/` with these four files, using a name made of lowercase letters, digits and hyphens:

| File | Contents |
|---|---|
| `eye.svg` | Shapes. Keep the path IDs from Adafruit's file |
| `iris.jpg` | Iris texture, square |
| `sclera.png` | Sclera texture, square, keeping its transparency |
| `lid.png` | Eyelid texture. Copy it from `default` |

Make the folder readable by the `pi-eyes` user. It appears in the web UI and Home Assistant within a few seconds. To let the web UI delete it later, also create an empty file called `uploaded` in the style's folder.

## REST API

| Request | Purpose |
|---|---|
| `GET /api/styles` | List styles |
| `GET /api/style` | Requested and active style |
| `PUT /api/style` with `{"style": "dragon"}` | Change style |
| `POST /api/styles` | Add a style. Multipart fields: `name`, `iris`, optional `sclera`, optional `shape` |
| `DELETE /api/styles/<name>` | Delete an uploaded style |
| `GET /api/styles/<name>/preview` | Preview image |

## Troubleshooting

```sh
systemctl status pi-eyes pi-eyes-fbx2 pi-eyes-control
journalctl -u pi-eyes -b            # Supervisor and eyes.py
journalctl -u pi-eyes-control -b    # Web and MQTT
```

If `requested` and `active` differ for more than a short while, the requested style failed. The `pi-eyes` log shows why. Select it again to retry after fixing it.

The Pi needs a proper shutdown before power-off: run `sudo poweroff` over SSH.

## Development

```sh
python -m venv .venv
.venv/Scripts/activate     # Windows; on Linux: source .venv/bin/activate
pip install -r requirements.txt pytest
pytest
```

## How it fits together

```
Web UI / REST ─┐
               ├─> pi-eyes-control ──writes──> /var/lib/pi-eyes/current-style
HA <─MQTT──────┘         ^                              │ watched by
                         │ reads active-style           v
                         └───────────────────── eyes_supervisor.py (inside xinit)
                                                        │ starts, in the style's folder
                                                        v
                                               /opt/Pi_Eyes/eyes.py ──X11──> fbx2 ──> displays
```
