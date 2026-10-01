"""Filesystem locations of the JSON Schemas this service validates against.

DCAT-US 3.0 lives in the GSA/dcat-us git submodule at `_external/dcat-us`, not
in this repo. Pin it to the same commit as GSA/datagov-harvester's submodule so
the validator accepts and rejects the same records a harvest would.

Do not edit anything under `_external/dcat-us` — open a PR against GSA/dcat-us
instead.

DCAT-US 1.1 has no GSA/dcat-us equivalent and stays vendored under `schemas/`
(copied from GSA/datagov-harvester).
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

DCATUS1_1_DIR = REPO_ROOT / "schemas" / "dcatus1.1"

DCATUS3_JSONSCHEMA_DIR = REPO_ROOT / "_external" / "dcat-us" / "jsonschema"
DCATUS3_DEFINITIONS_DIR = DCATUS3_JSONSCHEMA_DIR / "definitions"
