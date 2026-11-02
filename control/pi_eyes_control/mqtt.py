"""Home Assistant link: publishes a select entity through MQTT discovery."""

import json
import logging

import paho.mqtt.client as mqtt

from .styles import StyleError

log = logging.getLogger(__name__)

AVAILABILITY_TOPIC = "pi_eyes/status"
STATE_TOPIC = "pi_eyes/style/state"
COMMAND_TOPIC = "pi_eyes/style/set"
PUBLISH_TIMEOUT = 2.0


def make_client():
    return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="pi-eyes-control")


class MqttBridge:
    def __init__(self, store, config, client=None):
        self.store = store
        self.config = config
        self.client = client or make_client()
        self.prefix = config.get("discovery_prefix", "homeassistant")
        self.connected = False
        self.sent_options = None
        self.sent_state = None

    @property
    def discovery_topic(self):
        return f"{self.prefix}/select/pi_eyes/style/config"

    def discovery_payload(self):
        return {
            "name": "Style",
            "unique_id": "pi_eyes_style",
            "icon": "mdi:eye",
            "options": self.store.names(),
            "state_topic": STATE_TOPIC,
            "command_topic": COMMAND_TOPIC,
            "availability_topic": AVAILABILITY_TOPIC,
            "device": {
                "identifiers": ["pi_eyes"],
                "name": "Pi Eyes",
                "manufacturer": "Adafruit",
                "model": "Animated Eyes Bonnet",
            },
        }

    def start(self):
        client = self.client
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        if self.config.get("username"):
            client.username_pw_set(self.config["username"],
                                   self.config.get("password") or None)
        client.will_set(AVAILABILITY_TOPIC, "offline", qos=1, retain=True)
        # Async, so a broker that's down at boot doesn't stop the web UI. The
        # network loop keeps retrying.
        client.connect_async(self.config["host"], self.config.get("port", 1883))
        client.loop_start()

    def stop(self):
        if self.connected:
            self.client.publish(AVAILABILITY_TOPIC, "offline", qos=1,
                                retain=True).wait_for_publish(PUBLISH_TIMEOUT)
        self.client.disconnect()
        self.client.loop_stop()

    def sync(self):
        """Publishes anything that changed. Run regularly: the supervisor and
        web UI change the state without going through here."""
        if not self.connected:
            return
        options = self.store.names()
        if options != self.sent_options:
            self._publish_discovery(options)
        active = self.store.active()
        if active is not None and active != self.sent_state:
            self.client.publish(STATE_TOPIC, active, qos=1, retain=True)
            self.sent_state = active

    def _publish_discovery(self, options):
        self.client.publish(self.discovery_topic,
                            json.dumps(self.discovery_payload()),
                            qos=1, retain=True)
        self.sent_options = options

    def _on_connect(self, client, _userdata, _flags, reason_code, _properties):
        if reason_code.is_failure:
            log.error("MQTT connection refused: %s", reason_code)
            return
        log.info("Connected to MQTT broker")
        self.connected = True
        # Sent afresh, because the broker may have lost its retained messages.
        self.sent_options = None
        self.sent_state = None
        client.subscribe(COMMAND_TOPIC, qos=1)
        self.sync()
        client.publish(AVAILABILITY_TOPIC, "online", qos=1, retain=True)

    def _on_disconnect(self, _client, _userdata, _flags, reason_code, _properties):
        self.connected = False
        log.warning("Disconnected from MQTT broker: %s", reason_code)

    def _on_message(self, _client, _userdata, message):
        try:
            self.store.select(message.payload.decode())
        except (StyleError, UnicodeDecodeError) as err:
            log.warning("Ignoring MQTT style command: %s", err)
