import logging
import logging.config
import os
from urllib.parse import urlsplit

from apiflask import APIFlask
from dotenv import load_dotenv
from flask import jsonify, request
from werkzeug.exceptions import RequestEntityTooLarge

from app.constants import MAX_REQUEST_BYTES, MAX_UPLOAD_MB
from config.logger_config import LOGGING_CONFIG

logger = logging.getLogger("datagov_validator")

load_dotenv()
logging.config.dictConfig(LOGGING_CONFIG)

HSTS_MAX_AGE_SECONDS = 60 * 60 * 24 * 365
HSTS_HEADER = f"max-age={HSTS_MAX_AGE_SECONDS}; includeSubDomains; preload"


def _external_route_to_server_url(route: str | None) -> str | None:
    """Return a normalized external server URL, or None for empty input."""
    if not route:
        return None

    route = route.strip().rstrip("/")
    if not route:
        return None

    if urlsplit(route).scheme:
        return route

    return f"https://{route}"


def create_app():
    # Swagger UI at /docs, the spec at /openapi.json (APIFlask defaults).
    app = APIFlask(__name__, title="Datagov Validator", version="0.1.0")

    external_server_url = _external_route_to_server_url(os.getenv("EXTERNAL_ROUTE"))
    if external_server_url:
        app.config["SERVERS"] = [{"url": external_server_url}]

    app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BYTES
    # Lets synthetic monitoring confirm a request forwarded by another app's
    # proxy (datagov-harvest-proxy's /api/v1/validate) actually reached this one.
    app.config["SERVED_BY"] = os.getenv("SERVED_BY", "datagov-validator")

    @app.after_request
    def apply_headers(response):
        response.headers["X-Served-By"] = app.config["SERVED_BY"]
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Strict-Transport-Security"] = HSTS_HEADER
        # Every validation answer is specific to the submitted document.
        if request.method not in {"GET", "HEAD"} or response.status_code >= 400:
            response.headers["Cache-Control"] = "private, no-store, max-age=0"
        return response

    @app.errorhandler(RequestEntityTooLarge)
    def handle_request_entity_too_large(error):
        """
        Same {"error": ...} shape as the route's own refusals, rather than
        APIFlask's generic {"message": ...} one.
        """
        logger.warning(
            "Rejected request over the %sMB limit path=%s", MAX_UPLOAD_MB, request.path
        )
        message = f"Submission too large - must be {MAX_UPLOAD_MB}MB or less."
        return jsonify({"error": message}), 413

    from .routes import register_routes

    register_routes(app)

    return app
