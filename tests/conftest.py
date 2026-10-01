import json
from pathlib import Path

import pytest

from app import create_app

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SCHEMAS_DIR = Path(__file__).parents[1] / "schemas"


@pytest.fixture(autouse=True)
def allow_private_addresses(monkeypatch):
    """
    Tests mock `requests.get`, so nothing is actually fetched, but the
    private-address check still resolves the hostname. Allow by default so the
    suite doesn't depend on DNS; tests of the check itself turn it back off.
    """
    monkeypatch.setattr("app.fetch.ALLOW_PRIVATE_ADDRESSES", True)


@pytest.fixture
def app():
    app = create_app()
    app.config.update({"TESTING": True})
    yield app


@pytest.fixture
def client(app):
    return app.test_client()


def _read_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text()


@pytest.fixture
def dol_distribution_json():
    return json.loads(_read_fixture("dol-example.json"))


@pytest.fixture
def dcatus_long_description_json():
    return _read_fixture("dcatus_long_description.json")


@pytest.fixture
def dcatus_bad_license_uri_json():
    return _read_fixture("dcatus_bad_license_uri.json")


@pytest.fixture
def dcatus_no_identifier_json():
    return _read_fixture("dcatus_no_identifier.json")


@pytest.fixture
def dcatus_multiple_invalid_json():
    return _read_fixture("dcatus_multiple_invalid.json")


@pytest.fixture
def dcatus_non_federal_schema():
    with open(SCHEMAS_DIR / "dcatus1.1" / "non-federal_dataset.json") as f:
        return json.load(f)


@pytest.fixture
def dcatus_3_catalog_missing_identifier():
    return json.dumps(
        {
            "@type": "Catalog",
            "title": "Catalog With Invalid Homepage",
            "description": "This catalog has homepage as a string URL instead of a Document object.",  # noqa: E501
            "dataset": [
                {
                    "@type": "Dataset",
                    "title": "Example Dataset",
                    "description": "A valid dataset.",
                    "contactPoint": {
                        "fn": "Support",
                        "hasEmail": "mailto:support@example.gov",
                    },
                    "publisher": {"name": "Example Org"},
                }
            ],
        }
    )
