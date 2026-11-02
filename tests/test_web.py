import io

import pytest

from conftest import image_bytes
from pi_eyes_control.web import MAX_UPLOAD_BYTES, create_app


@pytest.fixture
def client(store):
    return create_app(store).test_client()


def upload(client, **overrides):
    data = {"name": "mine", "iris": (io.BytesIO(image_bytes()), "iris.png")}
    data.update(overrides)
    return client.post("/api/styles", data=data, content_type="multipart/form-data")


def test_page_loads(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Pi Eyes" in response.data


def test_lists_styles(client):
    assert client.get("/api/styles").json == {"styles": [
        {"name": "default", "uploaded": False},
        {"name": "dragon", "uploaded": False},
    ]}


def test_put_changes_requested_style(client, store):
    (store.state_dir / "active-style").write_text("default\n")
    response = client.put("/api/style", json={"style": "dragon"})
    assert response.status_code == 200
    assert response.json == {"requested": "dragon", "active": "default"}
    assert client.get("/api/style").json["requested"] == "dragon"


@pytest.mark.parametrize("body,status", [
    ({"style": "nope"}, 404),
    ({"style": "../default"}, 404),
    ({"style": 5}, 404),
    ({"wrong": "dragon"}, 400),
    (["dragon"], 400),
])
def test_put_rejects_bad_requests(client, store, body, status):
    assert client.put("/api/style", json=body).status_code == status
    assert store.requested() == "default"


def test_upload_then_delete(client, store):
    assert upload(client).status_code == 201
    assert {"name": "mine", "uploaded": True} in client.get("/api/styles").json["styles"]
    assert client.delete("/api/styles/mine").status_code == 204
    assert not store.exists("mine")


def test_upload_errors(client):
    assert upload(client, iris=(io.BytesIO(b"junk"), "iris.png")).status_code == 400
    assert upload(client, name="Bad Name").status_code == 400
    assert upload(client, shape="nope").status_code == 404
    assert upload(client, name="dragon").status_code == 409
    assert client.post("/api/styles", data={"name": "x"},
                       content_type="multipart/form-data").status_code == 400


def test_upload_size_limit(client):
    big = io.BytesIO(b"\0" * (MAX_UPLOAD_BYTES + 1))
    response = upload(client, iris=(big, "iris.png"))
    assert response.status_code == 413
    assert "error" in response.json


def test_builtin_delete_refused(client):
    assert client.delete("/api/styles/dragon").status_code == 409


def test_preview(client):
    response = client.get("/api/styles/default/preview")
    assert (response.status_code, response.mimetype) == (200, "image/jpeg")
    assert client.get("/api/styles/nope/preview").status_code == 404


def test_cross_site_writes_are_refused(client, store):
    evil = {"Origin": "http://evil.example"}
    assert client.put("/api/style", json={"style": "dragon"}, headers=evil).status_code == 403
    assert store.requested() == "default"
    same = {"Origin": "http://localhost"}
    assert client.put("/api/style", json={"style": "dragon"}, headers=same).status_code == 200
