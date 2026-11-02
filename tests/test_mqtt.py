import json
from types import SimpleNamespace

import pytest

from conftest import image_bytes
from pi_eyes_control.mqtt import (AVAILABILITY_TOPIC, COMMAND_TOPIC, STATE_TOPIC,
                                  MqttBridge)

DISCOVERY_TOPIC = "homeassistant/select/pi_eyes/style/config"


class FakeClient:
    def __init__(self):
        self.published = []
        self.subscribed = []
        self.will = None
        self.credentials = None
        self.target = None
        self.looping = False

    def username_pw_set(self, username, password):
        self.credentials = (username, password)

    def will_set(self, topic, payload, qos, retain):
        self.will = (topic, payload, qos, retain)

    def connect_async(self, host, port):
        self.target = (host, port)

    def loop_start(self):
        self.looping = True

    def loop_stop(self):
        self.looping = False

    def disconnect(self):
        pass

    def subscribe(self, topic, qos):
        self.subscribed.append(topic)

    def publish(self, topic, payload, qos, retain):
        self.published.append((topic, payload, retain))
        return SimpleNamespace(wait_for_publish=lambda timeout: None)

    def to(self, topic):
        return [payload for t, payload, _ in self.published if t == topic]


OK = SimpleNamespace(is_failure=False)
REFUSED = SimpleNamespace(is_failure=True)


@pytest.fixture
def client():
    return FakeClient()


@pytest.fixture
def bridge(store, client):
    (store.state_dir / "active-style").write_text("default\n")
    bridge = MqttBridge(store, {"host": "broker", "port": 1884,
                                "username": "eyes", "password": "secret"},
                        client=client)
    bridge.start()
    return bridge


def connect(bridge, reason=OK):
    bridge._on_connect(bridge.client, None, None, reason, None)


def test_start_sets_last_will_credentials_and_target(bridge, client):
    assert client.will == (AVAILABILITY_TOPIC, "offline", 1, True)
    assert client.credentials == ("eyes", "secret")
    assert client.target == ("broker", 1884)
    assert client.looping


def test_connect_announces_entity(bridge, client):
    connect(bridge)
    assert client.subscribed == [COMMAND_TOPIC]
    config = json.loads(client.to(DISCOVERY_TOPIC)[-1])
    assert config["options"] == ["default", "dragon"]
    assert config["unique_id"] == "pi_eyes_style"
    assert config["name"] == "Style"
    assert config["device"]["name"] == "Pi Eyes"
    assert config["command_topic"] == COMMAND_TOPIC
    assert config["state_topic"] == STATE_TOPIC
    assert config["availability_topic"] == AVAILABILITY_TOPIC
    assert client.to(STATE_TOPIC) == ["default"]
    assert client.to(AVAILABILITY_TOPIC) == ["online"]
    assert all(retain for _, _, retain in client.published)


def test_online_comes_after_config_and_state(bridge, client):
    connect(bridge)
    assert client.published[-1][0] == AVAILABILITY_TOPIC


def test_refused_connection_publishes_nothing(bridge, client):
    connect(bridge, REFUSED)
    bridge.sync()
    assert client.published == []


def test_custom_discovery_prefix(store, client):
    bridge = MqttBridge(store, {"host": "b", "discovery_prefix": "ha"}, client=client)
    bridge.start()
    connect(bridge)
    assert client.to("ha/select/pi_eyes/style/config")


def test_command_selects_style(bridge, store):
    bridge._on_message(None, None, SimpleNamespace(payload=b"dragon"))
    assert store.requested() == "dragon"


@pytest.mark.parametrize("payload", [b"nope", b"../default", b"\xff\xfe", b""])
def test_bad_command_is_ignored(bridge, store, payload):
    bridge._on_message(None, None, SimpleNamespace(payload=payload))
    assert store.requested() == "default"


def test_sync_reports_active_not_requested(bridge, store, client):
    connect(bridge)
    store.select("dragon")
    bridge.sync()
    assert client.to(STATE_TOPIC) == ["default"]  # Supervisor hasn't switched yet
    (store.state_dir / "active-style").write_text("dragon\n")
    bridge.sync()
    assert client.to(STATE_TOPIC) == ["default", "dragon"]


def test_sync_only_publishes_changes(bridge, client):
    connect(bridge)
    count = len(client.published)
    bridge.sync()
    assert len(client.published) == count


def test_sync_republishes_discovery_when_styles_change(bridge, store, client):
    connect(bridge)
    store.add("mine", image_bytes())
    bridge.sync()
    assert json.loads(client.to(DISCOVERY_TOPIC)[-1])["options"] == ["default", "dragon", "mine"]
    store.delete("mine")
    bridge.sync()
    assert json.loads(client.to(DISCOVERY_TOPIC)[-1])["options"] == ["default", "dragon"]


def test_reconnect_republishes_everything(bridge, client):
    connect(bridge)
    bridge._on_disconnect(client, None, None, OK, None)
    client.published.clear()
    bridge.sync()
    assert client.published == []  # Nothing while disconnected
    connect(bridge)
    assert client.to(DISCOVERY_TOPIC) and client.to(STATE_TOPIC) and client.to(AVAILABILITY_TOPIC)


def test_stop_announces_offline(bridge, client):
    connect(bridge)
    bridge.stop()
    assert client.to(AVAILABILITY_TOPIC)[-1] == "offline"
    assert not client.looping
