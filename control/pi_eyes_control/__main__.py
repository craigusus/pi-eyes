"""Entry point for the pi-eyes-control service."""

import argparse
import logging
import signal
import sys
import threading
import time
import tomllib

from waitress import serve

from .mqtt import MqttBridge
from .styles import StyleStore
from .web import create_app

log = logging.getLogger("pi_eyes_control")

SYNC_INTERVAL = 1.0


def sync_forever(bridge):
    while True:
        try:
            bridge.sync()
        except Exception:
            log.exception("MQTT sync failed")
        time.sleep(SYNC_INTERVAL)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="/etc/pi-eyes/control.toml")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(name)s: %(levelname)s: %(message)s")

    with open(args.config, "rb") as file:
        config = tomllib.load(file)
    store = StyleStore(config.get("state", {}).get("dir", "/var/lib/pi-eyes"))

    bridge = None
    mqtt_config = config.get("mqtt", {})
    if mqtt_config.get("host"):
        bridge = MqttBridge(store, mqtt_config)
        bridge.start()
        threading.Thread(target=sync_forever, args=(bridge,), daemon=True).start()
    else:
        log.info("No MQTT host configured; running without Home Assistant")

    # Unwinds through the finally below, so HA sees a clean offline.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    web = config.get("web", {})
    try:
        serve(create_app(store), host=web.get("host", "0.0.0.0"),
              port=web.get("port", 8080), threads=4)
    finally:
        if bridge:
            bridge.stop()


if __name__ == "__main__":
    main()
