"""REST API and web page."""

from urllib.parse import urlsplit

from flask import Flask, jsonify, render_template, request

from .styles import (DEFAULT_STYLE, InvalidStyle, StyleConflict, StyleNotFound)

MAX_UPLOAD_BYTES = 16 * 1024 * 1024


def create_app(store):
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES

    @app.before_request
    def reject_cross_site_writes():
        """There's no login, so stop other websites a browser on the LAN
        happens to open from changing the eyes."""
        origin = request.headers.get("Origin")
        if (request.method not in ("GET", "HEAD") and origin and
                urlsplit(origin).netloc != request.host):
            return jsonify(error="Cross-site requests are not allowed"), 403

    @app.errorhandler(InvalidStyle)
    def invalid(err):
        return jsonify(error=str(err)), 400

    @app.errorhandler(StyleNotFound)
    def not_found(err):
        return jsonify(error=str(err)), 404

    @app.errorhandler(StyleConflict)
    def conflict(err):
        return jsonify(error=str(err)), 409

    @app.errorhandler(413)
    def too_large(_err):
        limit = MAX_UPLOAD_BYTES // (1024 * 1024)
        return jsonify(error=f"Uploads must be under {limit} MB"), 413

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/styles")
    def list_styles():
        return jsonify(styles=[{"name": name, "uploaded": store.is_uploaded(name)}
                               for name in store.names()])

    @app.get("/api/style")
    def get_style():
        return jsonify(requested=store.requested(), active=store.active())

    @app.put("/api/style")
    def put_style():
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or "style" not in body:
            raise InvalidStyle('Send JSON like {"style": "dragon"}')
        store.select(body["style"])
        return jsonify(requested=store.requested(), active=store.active())

    @app.post("/api/styles")
    def add_style():
        iris = request.files.get("iris")
        if iris is None or not iris.filename:
            raise InvalidStyle("An iris image is required")
        sclera = request.files.get("sclera")
        sclera_data = sclera.read() if sclera and sclera.filename else None
        name = request.form.get("name", "")
        store.add(name, iris.read(), sclera_data,
                  request.form.get("shape", DEFAULT_STYLE))
        return jsonify(name=name), 201

    @app.delete("/api/styles/<name>")
    def delete_style(name):
        store.delete(name)
        return "", 204

    @app.get("/api/styles/<name>/preview")
    def preview(name):
        return app.response_class(store.preview(name), mimetype="image/jpeg")

    return app
