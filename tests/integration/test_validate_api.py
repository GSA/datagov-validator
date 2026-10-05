import itertools
import json
from unittest.mock import Mock

import requests

from app.constants import MAX_REQUEST_BYTES, MAX_UPLOAD_BYTES, MAX_UPLOAD_MB
from app.fetch import (
    FETCH_TIMEOUT_SECONDS,
    PAYLOAD_TOO_LARGE_MESSAGE,
    UNEXPECTED_FETCH_ERROR_MESSAGE,
)
from app.validation import NESTING_TOO_DEEP_MESSAGE

URL = "/api/v1/validate"


def _json_response(body: str):
    response = Mock()
    response.status_code = 200
    response.headers = {"Content-Type": "application/json"}
    response.raise_for_status = Mock()
    response.close = Mock()
    response.iter_content = Mock(return_value=[body.encode()])
    return response


def _deeply_nested_catalog(depth=200):
    """3.0: Catalog.catalog is `items: {"$ref": "#"}`. 150 validates, 200 does not."""
    catalog = {"@type": "Catalog", "title": "t", "description": "d", "dataset": []}
    for _ in range(depth):
        catalog = {
            "@type": "Catalog",
            "title": "t",
            "description": "d",
            "dataset": [],
            "catalog": [catalog],
        }
    return json.dumps(catalog)


class TestValidate:
    def test_paste(self, client, dcatus_bad_license_uri_json):
        res = client.post(
            URL,
            json={
                "schema": "dcatus1.1: non-federal dataset",
                "fetch_method": "paste",
                "json_text": dcatus_bad_license_uri_json,
            },
        )

        # ruff: noqa: E501
        assert res.status_code == 200
        assert res.get_json() == {
            "validation_errors": [
                [
                    "https://www.arcgis.com/home/item.html?id=99731bb0369848169d98f31ce83fb0e2",
                    "$.license, 'center' does not match any of the acceptable formats: 'uri', 'null', '^(\\\\[\\\\[REDACTED).*?(\\\\]\\\\])$'",
                ]
            ]
        }

    def test_url(self, client, monkeypatch, dcatus_no_identifier_json):
        get = Mock(return_value=_json_response(dcatus_no_identifier_json))
        monkeypatch.setattr("app.fetch.requests.get", get)

        res = client.post(
            URL,
            json={
                "schema": "dcatus1.1: non-federal dataset",
                "fetch_method": "url",
                "url": "https://example.com/data.json",
            },
        )

        assert res.status_code == 200
        # dataset position, not a string, when the dataset has no identifier
        assert res.get_json() == {
            "validation_errors": [[0, "$, 'identifier' is a required property"]]
        }
        assert get.call_args.args[0] == "https://example.com/data.json"

    def test_url_with_many_errors(
        self, client, monkeypatch, dcatus_multiple_invalid_json
    ):
        monkeypatch.setattr(
            "app.fetch.requests.get",
            Mock(return_value=_json_response(dcatus_multiple_invalid_json)),
        )

        res = client.post(
            URL,
            json={
                "schema": "dcatus1.1: federal dataset",
                "fetch_method": "url",
                "url": "https://example.com/data.json",
            },
        )

        assert res.status_code == 200
        assert len(res.get_json()["validation_errors"]) == 5

    def test_dcatus3_catalog(self, client, dcatus_3_catalog_missing_identifier):
        """The harvester's API only accepted 1.1; its validator page took 3.0 too."""
        res = client.post(
            URL,
            json={
                "schema": "dcatus3.0 catalog",
                "fetch_method": "paste",
                "json_text": dcatus_3_catalog_missing_identifier,
            },
        )

        assert res.status_code == 200
        assert res.get_json() == {
            "validation_errors": [
                ["", "$.dataset[0], 'identifier' is a required property"]
            ]
        }

    def test_valid_catalog_has_no_errors(self, client):
        res = client.post(
            URL,
            json={
                "schema": "dcatus1.1: federal dataset",
                "fetch_method": "paste",
                "json_text": json.dumps({"dataset": []}),
            },
        )

        assert res.status_code == 200
        assert res.get_json() == {"validation_errors": []}

    def test_unversioned_path_redirects_to_latest(self, client):
        res = client.post("/api/validate", json={})

        assert res.status_code == 308
        assert res.location == URL

    def test_responses_are_not_cached_and_name_the_app(self, client):
        res = client.post(
            URL,
            json={
                "schema": "dcatus1.1: federal dataset",
                "fetch_method": "paste",
                "json_text": json.dumps({"dataset": []}),
            },
        )

        assert res.headers["Cache-Control"] == "private, no-store, max-age=0"
        assert res.headers["X-Served-By"] == "datagov-validator"


class TestRequestValidation:
    def test_bad_url(self, client):
        res = client.post(
            URL,
            json={
                "schema": "dcatus1.1: non-federal dataset",
                "fetch_method": "url",
                "url": "nonsense",
            },
        )

        assert res.status_code == 422
        assert res.get_json() == {
            "detail": {"json": {"url": ["Not a valid URL."]}},
            "message": "Validation error",
        }

    def test_unknown_schema(self, client):
        res = client.post(
            URL,
            json={"schema": "dcatus2", "fetch_method": "paste", "json_text": "{}"},
        )

        assert res.status_code == 422
        assert "schema" in res.get_json()["detail"]["json"]

    def test_missing_url(self, client):
        res = client.post(
            URL, json={"schema": "dcatus1.1: federal dataset", "fetch_method": "url"}
        )

        assert res.status_code == 422

    def test_missing_json_text(self, client):
        res = client.post(
            URL,
            json={"schema": "dcatus1.1: federal dataset", "fetch_method": "paste"},
        )

        assert res.status_code == 422

    def test_unparseable_json_is_reported_by_position(self, client):
        res = client.post(
            URL,
            json={
                "schema": "dcatus1.1: federal dataset",
                "fetch_method": "paste",
                "json_text": '{"dataset": [}',
            },
        )

        assert res.status_code == 400
        assert res.get_json() == {"error": "Invalid JSON at line 1, column 14."}


class TestLimits:
    def test_request_body_over_the_limit_returns_json(self, client):
        res = client.post(
            URL,
            data=b'{"json_text":"' + b"x" * (MAX_REQUEST_BYTES + 1024) + b'"}',
            content_type="application/json",
        )

        assert res.status_code == 413
        assert res.get_json() == {
            "error": f"Submission too large - must be {MAX_UPLOAD_MB}MB or less."
        }

    def test_pasted_document_at_the_limit_fits_despite_escaping(self, client):
        """
        A document just under the limit whose JSON encoding is larger than it
        (every quote escaped) must still be accepted.
        """
        padding = [""] * (MAX_UPLOAD_BYTES // 5)
        document = json.dumps({"dataset": [], "padding": padding})
        assert len(document) < MAX_UPLOAD_BYTES
        body = json.dumps(
            {
                "schema": "dcatus1.1: federal dataset",
                "fetch_method": "paste",
                "json_text": document,
            }
        )
        assert MAX_UPLOAD_BYTES < len(body) < MAX_REQUEST_BYTES

        res = client.post(URL, data=body, content_type="application/json")

        assert res.status_code == 200
        assert res.get_json() == {"validation_errors": []}

    def test_pasted_document_over_the_limit_is_refused(self, client):
        res = client.post(
            URL,
            json={
                "schema": "dcatus1.1: federal dataset",
                "fetch_method": "paste",
                "json_text": "x" * (MAX_UPLOAD_BYTES + 1),
            },
        )

        assert res.status_code == 400
        assert res.get_json() == {"error": PAYLOAD_TOO_LARGE_MESSAGE}

    def test_deeply_nested_catalog_returns_422_naming_the_reason(self, client):
        res = client.post(
            URL,
            json={
                "schema": "dcatus3.0 catalog",
                "fetch_method": "paste",
                "json_text": _deeply_nested_catalog(),
            },
        )

        assert res.status_code == 422
        assert res.get_json() == {"error": NESTING_TOO_DEEP_MESSAGE}


class TestRefusedUrlIsExplained:
    """
    A URL we decline to fetch has to say why: 400 (bad submission, not a server
    fault) with the reason, rather than an opaque 500. GSA/data.gov#6293.
    """

    def _url_form(self, url):
        return {
            "schema": "dcatus1.1: federal dataset",
            "fetch_method": "url",
            "url": url,
        }

    def test_timeout(self, client, monkeypatch):
        clock = itertools.chain([100.0, 100.0], itertools.repeat(200.0))
        monkeypatch.setattr("app.fetch.time.monotonic", lambda: next(clock))
        monkeypatch.setattr(
            "app.fetch.requests.get",
            Mock(side_effect=requests.exceptions.Timeout("timed out")),
        )

        res = client.post(URL, json=self._url_form("https://example.com/slow.json"))

        assert res.status_code == 400
        assert f"longer than {FETCH_TIMEOUT_SECONDS} seconds" in res.get_json()["error"]

    def test_connect_timeout(self, client, monkeypatch):
        monkeypatch.setattr(
            "app.fetch.requests.get",
            Mock(side_effect=requests.exceptions.ConnectTimeout("syn lost")),
        )

        res = client.post(URL, json=self._url_form("https://example.com/flaky.json"))

        assert res.status_code == 400
        assert "Could not connect to the URL's server" in res.get_json()["error"]

    def test_private_address(self, client, monkeypatch):
        monkeypatch.setattr("app.fetch.ALLOW_PRIVATE_ADDRESSES", False)

        res = client.post(URL, json=self._url_form("http://127.0.0.1/secret.json"))

        assert res.status_code == 400
        assert "private/internal addresses is not allowed" in res.get_json()["error"]

    def test_unexpected_transport_error_is_not_disclosed(self, client, monkeypatch):
        """Still a 400 the submitter can act on, but requests' own text - which
        can name internal paths - must not reach the response body."""
        monkeypatch.setattr(
            "app.fetch.requests.get",
            Mock(
                side_effect=requests.exceptions.SSLError(
                    "verify failed: /internal/path/ca-bundle.crt"
                )
            ),
        )

        res = client.post(URL, json=self._url_form("https://example.com/data.json"))

        assert res.status_code == 400
        assert res.get_json() == {"error": UNEXPECTED_FETCH_ERROR_MESSAGE}

    def test_unexpected_server_error_is_not_disclosed(self, client, monkeypatch):
        monkeypatch.setattr(
            "app.api.validate.validate_records",
            Mock(side_effect=KeyError("/internal/detail")),
        )

        res = client.post(
            URL,
            json={
                "schema": "dcatus1.1: federal dataset",
                "fetch_method": "paste",
                "json_text": "{}",
            },
        )

        assert res.status_code == 500
        assert res.get_json() == {
            "error": "API Validator error: failed to validate dcatus catalog"
        }


class TestService:
    def test_health(self, client):
        res = client.get("/health")

        assert res.status_code == 200
        assert res.get_json() == {"status": "ok"}

    def test_openapi_spec_documents_validate(self, client):
        spec = client.get("/openapi.json").get_json()

        assert set(spec["paths"]) == {URL}
        assert "post" in spec["paths"][URL]
        # no auth anywhere in this service
        assert "securitySchemes" not in spec.get("components", {})

    def test_docs(self, client):
        assert client.get("/docs").status_code == 200
        assert client.get("/").location == "/docs"
