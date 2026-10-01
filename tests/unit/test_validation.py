"""
Error-message formatting tests, ported from GSA/datagov-harvester's
tests/unit/test_utils.py alongside the code in app/validation.py. Keep them in
step with the harvester's copies.
"""

import json
import time
from unittest.mock import patch

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from app import validation
from app.schema_paths import DCATUS3_DEFINITIONS_DIR, DCATUS3_JSONSCHEMA_DIR
from app.validation import (
    NESTING_TOO_DEEP_MESSAGE,
    CatalogTooDeeplyNested,
    assemble_validation_errors,
    build_dcatus3_validator,
    validate_records,
)

DCATUS3_COMPLETE_EXAMPLE = (
    DCATUS3_JSONSCHEMA_DIR / "examples" / "Dataset" / "good" / "complete_example.json"
)

# Real DCAT-US 3.0 validator, used to reproduce assembler errors on the
# complete example.
DCATUS3_DATASET_VALIDATOR = build_dcatus3_validator(
    DCATUS3_DEFINITIONS_DIR,
    root_ref="https://resources.data.gov/dcat-us/3.0.0/definitions/dataset",
)


@pytest.fixture
def dcatus3_complete_example():
    with open(DCATUS3_COMPLETE_EXAMPLE) as f:
        return json.load(f)


class TestAssembleValidationErrors:
    def test_assemble_validation_messages(
        self, dol_distribution_json, dcatus_non_federal_schema
    ):
        # the amount of test cases for something like this is massive
        # because you can check every rule for every piece of data
        # so trying to reasonably cover our bases

        del dol_distribution_json["identifier"]  # missing required field at root
        dol_distribution_json["keyword"] = []  # empty array
        dol_distribution_json["distribution"][0]["title"] = ""  # empty string
        dol_distribution_json["distribution"][1] = bool  # wrong type
        dol_distribution_json["contactPoint"][
            "hasEmail"
        ] = "bad email"  # bad value based on regex
        dol_distribution_json["accrualPeriodicity"] = (
            "No longer updated (dataset archived)"  # bad const value
        )
        dol_distribution_json["rights"] = "a" * 256  # max string length exceeded
        dol_distribution_json["distribution"][0][
            "@type"
        ] = "Distribution"  # not dcat:Distribution

        validator = Draft202012Validator(
            dcatus_non_federal_schema, format_checker=FormatChecker()
        )

        # validation messages are stored in the db via repr which will include the
        # object type (e.g. '<ValidationError: "$, \'identifier\' is a required property">')
        # omitting that here for brevity.
        # backslashes are doubled here but not in the final validation record error message.
        # ruff: noqa E501
        expected = [
            "$, 'identifier' is a required property",
            "$.rights, 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' does not match any of the acceptable formats: max string length of 255 characters, 'null'",
            "$.accrualPeriodicity, 'No longer updated (dataset archived)' does not match any of the acceptable formats: constant value 'irregular' was expected, '^R\\\\/P(?:\\\\d+(?:\\\\.\\\\d+)?Y)?(?:\\\\d+(?:\\\\.\\\\d+)?M)?(?:\\\\d+(?:\\\\.\\\\d+)?W)?(?:\\\\d+(?:\\\\.\\\\d+)?D)?(?:T(?:\\\\d+(?:\\\\.\\\\d+)?H)?(?:\\\\d+(?:\\\\.\\\\d+)?M)?(?:\\\\d+(?:\\\\.\\\\d+)?S)?)?$', 'null', '^(\\\\[\\\\[REDACTED).*?(\\\\]\\\\])$'",
            "$.contactPoint.hasEmail, 'bad email' does not match any of the acceptable formats: \"^mailto:[\\\\w\\\\_\\\\~\\\\!\\\\$\\\\&\\\\'\\\\(\\\\)\\\\*\\\\+\\\\,\\\\;\\\\=\\\\:.-]+@[\\\\w.-]+\\\\.[\\\\w.-]+?$\", '^(\\\\[\\\\[REDACTED).*?(\\\\]\\\\])$'",
            "$.distribution[0]['@type'], @type value does not match any of the acceptable formats: constant value 'dcat:Distribution' was expected",
            "$.distribution[0].title, '' does not match any of the acceptable formats: non-empty, 'null', '^(\\\\[\\\\[REDACTED).*?(\\\\]\\\\])$'",
            "$.distribution[1], 'bool' does not match any of the acceptable formats: 'object', 'string'",
            "$.keyword, [] does not match any of the acceptable formats: non-empty, 'string'",
        ]

        errors = assemble_validation_errors(
            validator.iter_errors(dol_distribution_json)
        )

        for i in range(len(errors)):
            assert errors[i].message == expected[i]

    def test_assemble_validation_messages_keyword_too_many_items(
        self, dol_distribution_json, dcatus_non_federal_schema
    ):
        dol_distribution_json["keyword"] = ["a"] * 1001
        validator = Draft202012Validator(
            dcatus_non_federal_schema, format_checker=FormatChecker()
        )
        errors = assemble_validation_errors(
            validator.iter_errors(dol_distribution_json)
        )
        keyword_error = next(e for e in errors if "$.keyword" in e.message)
        assert "max 1000 items" in keyword_error.message

    def test_assemble_validation_messages_type_error_list_value_is_reported(
        self, dcatus3_complete_example
    ):
        """A non-empty list that fails `type: ["null", "string"]` must be
        reported, not dropped."""
        dcatus3_complete_example["spatialResolutionInMeters"] = ["bad"]

        errors = assemble_validation_errors(
            DCATUS3_DATASET_VALIDATOR.iter_errors(dcatus3_complete_example)
        )

        assert len(errors) == 1
        assert errors[0].message == (
            "$.spatialResolutionInMeters, array value does not match any "
            "of the acceptable formats: 'string'"
        )

    def test_assemble_validation_messages_type_error_dict_value_is_reported(
        self, dcatus3_complete_example
    ):
        """Same as the list case; name the offender as "object value", not a
        dict key."""
        dcatus3_complete_example["temporalResolution"] = {"a": 1}

        errors = assemble_validation_errors(
            DCATUS3_DATASET_VALIDATOR.iter_errors(dcatus3_complete_example)
        )

        assert len(errors) == 1
        assert errors[0].message == (
            "$.temporalResolution, object value does not match any of the "
            "acceptable formats: 'string'"
        )

    def test_assemble_validation_messages_type_error_single_type_leaf_is_reported(
        self, dcatus3_complete_example
    ):
        """A leaf `type: string` error with no parent (nested `@type`) must
        still be reported."""
        dcatus3_complete_example["distribution"][0]["@type"] = {"a": 1}

        errors = assemble_validation_errors(
            DCATUS3_DATASET_VALIDATOR.iter_errors(dcatus3_complete_example)
        )

        assert len(errors) == 1
        assert errors[0].message == (
            "$.distribution[0]['@type'], object value does not match any of "
            "the acceptable formats: 'string'"
        )

        dcatus3_complete_example["distribution"][0]["@type"] = ["a"]

        errors = assemble_validation_errors(
            DCATUS3_DATASET_VALIDATOR.iter_errors(dcatus3_complete_example)
        )

        assert len(errors) == 1
        assert errors[0].message == (
            "$.distribution[0]['@type'], array value does not match any of "
            "the acceptable formats: 'string'"
        )

    def test_assemble_validation_messages_anyof_context_still_finds_specific_cause(
        self, dcatus3_complete_example
    ):
        """An anyOf failure should surface the specific cause, not the
        null-branch type error."""
        del dcatus3_complete_example["contactPoint"][0]["hasEmail"]

        errors = assemble_validation_errors(
            DCATUS3_DATASET_VALIDATOR.iter_errors(dcatus3_complete_example)
        )

        assert len(errors) == 1
        assert (
            errors[0].message == "$.contactPoint[0], 'hasEmail' is a required property"
        )

    def test_assemble_validation_messages_nested_container_type_error_under_anyof(
        self, dcatus3_complete_example
    ):
        """A leaf type error reached through anyOf (deeper json_path than its
        parent) must be reported."""
        dcatus3_complete_example["contactPoint"][0]["@type"] = ["Kind"]

        errors = assemble_validation_errors(
            DCATUS3_DATASET_VALIDATOR.iter_errors(dcatus3_complete_example)
        )

        assert len(errors) == 1
        assert errors[0].message == (
            "$.contactPoint[0]['@type'], array value does not match any of "
            "the acceptable formats: 'string'"
        )

    def test_assemble_validation_messages_plain_leaf_type_error_is_unaffected(
        self, dcatus3_complete_example
    ):
        """A plain `type: string` leaf with no context is unchanged by the
        forced fallback."""
        dcatus3_complete_example["title"] = {"a": 1}

        errors = assemble_validation_errors(
            DCATUS3_DATASET_VALIDATOR.iter_errors(dcatus3_complete_example)
        )

        assert len(errors) == 1
        assert errors[0].message == (
            "$.title, object value does not match any of the acceptable "
            "formats: 'string'"
        )

    def test_assemble_validation_messages_anyof_of_all_scalar_types_is_rescued(
        self, dcatus3_complete_example
    ):
        """When every anyOf alternative is scalar, report a vague type error
        rather than silence."""
        dcatus3_complete_example["accessRights"] = ["x"]

        errors = assemble_validation_errors(
            DCATUS3_DATASET_VALIDATOR.iter_errors(dcatus3_complete_example)
        )

        assert len(errors) == 1
        assert errors[0].message == (
            "$.accessRights, array value does not match any of the "
            "acceptable formats: 'null', 'string'"
        )

    def test_assemble_validation_messages_anyof_of_all_scalar_types_is_rescued_dict(
        self, dcatus3_complete_example
    ):
        """Same all-scalar anyOf rescue, for a dict against `language`."""
        dcatus3_complete_example["language"] = {"a": 1}

        errors = assemble_validation_errors(
            DCATUS3_DATASET_VALIDATOR.iter_errors(dcatus3_complete_example)
        )

        assert len(errors) == 1
        assert errors[0].message == (
            "$.language, object value does not match any of the acceptable "
            "formats: 'null', 'string', 'array'"
        )

    def test_assemble_validation_messages_anyof_of_all_scalar_types_is_rescued_date(
        self, dcatus3_complete_example
    ):
        """Same all-scalar anyOf rescue, for `created` (nested anyOf of date forms)."""
        dcatus3_complete_example["created"] = ["2025"]

        errors = assemble_validation_errors(
            DCATUS3_DATASET_VALIDATOR.iter_errors(dcatus3_complete_example)
        )

        assert len(errors) == 1
        assert errors[0].message == (
            "$.created, array value does not match any of the acceptable "
            "formats: 'string'"
        )

    def test_assemble_validation_messages_anyof_of_all_scalar_types_is_rescued_nested(
        self, dcatus3_complete_example
    ):
        """Same all-scalar anyOf rescue, nested under `spatial[0].bbox`."""
        dcatus3_complete_example["spatial"][0]["bbox"] = ["x"]

        errors = assemble_validation_errors(
            DCATUS3_DATASET_VALIDATOR.iter_errors(dcatus3_complete_example)
        )

        assert len(errors) == 1
        assert errors[0].message == (
            "$.spatial[0].bbox, array value does not match any of the "
            "acceptable formats: 'null', 'string', 'object'"
        )

    def test_assemble_validation_messages_maxitems_numeric_array_does_not_crash(
        self, dcatus3_complete_example
    ):
        """A numeric maxItems array must not crash message assembly; name it
        as "array value"."""
        dcatus3_complete_example["spatial"][0]["centroid"] = {
            "type": "Point",
            "coordinates": [-77, 38, 1],
        }

        errors = assemble_validation_errors(
            DCATUS3_DATASET_VALIDATOR.iter_errors(dcatus3_complete_example)
        )

        assert len(errors) == 1
        assert errors[0].message == (
            "$.spatial[0].centroid.coordinates, array value does not match "
            "any of the acceptable formats: max 2 items"
        )

    def test_assemble_validation_messages_minitems_names_specific_cause(
        self, dcatus3_complete_example
    ):
        """A minItems violation must be reported at its own path, not as a
        parent anyOf type error."""
        dcatus3_complete_example["spatial"][0]["centroid"] = {
            "type": "Point",
            "coordinates": [-77],
        }

        errors = assemble_validation_errors(
            DCATUS3_DATASET_VALIDATOR.iter_errors(dcatus3_complete_example)
        )

        assert len(errors) == 1
        assert errors[0].message == (
            "$.spatial[0].centroid.coordinates, array value does not match "
            "any of the acceptable formats: min 2 items"
        )

    def test_assemble_validation_messages_formats_the_result_once(
        self, dcatus3_complete_example
    ):
        """
        Formatting on every recursive return repeated the same work and made the
        assembler quadratic. (GSA/data.gov#6067)
        """
        dcatus3_complete_example["spatialResolutionInMeters"] = ["bad"]
        del dcatus3_complete_example["title"]

        with patch(
            "app.validation.finalize_validation_messages",
            wraps=validation.finalize_validation_messages,
        ) as finalize:
            errors = assemble_validation_errors(
                DCATUS3_DATASET_VALIDATOR.iter_errors(dcatus3_complete_example)
            )

        # the input recurses through anyOf context, so this is >1 without the fix
        assert finalize.call_count == 1
        assert len(errors) == 2

    def test_assemble_validation_messages_scales_linearly_with_dataset_count(self):
        """
        A 3.0 catalog is assembled in one call, so the message dict grew with the
        dataset count and the per-error work grew with it, on a catalog well under
        the upload limit. 27s before the fix, 0.02s after on a dev laptop. 2s is
        deliberately loose: it catches the quadratic coming back, not a small
        regression.
        """
        count = 4000
        catalog = {
            "@type": "Catalog",
            "title": "Assembler scaling",
            "description": "Every dataset is missing its identifier.",
            "dataset": [
                {
                    "@type": "Dataset",
                    "title": "Example Dataset",
                    "description": "A dataset with no identifier.",
                    "contactPoint": {
                        "fn": "Support",
                        "hasEmail": "mailto:support@example.gov",
                    },
                    "publisher": {"name": "Example Org"},
                }
                for _ in range(count)
            ],
        }
        validator = build_dcatus3_validator(DCATUS3_DEFINITIONS_DIR)
        validation_errors = list(validator.iter_errors(catalog))

        start = time.perf_counter()
        errors = assemble_validation_errors(iter(validation_errors))
        elapsed = time.perf_counter() - start

        # one "'identifier' is a required property" per dataset, all still found
        assert len(errors) == count
        assert elapsed < 2, f"assembling {count} errors took {elapsed:.1f}s"


class TestValidateRecords:
    def test_dcatus1_1_errors_are_keyed_by_identifier(
        self, dcatus_bad_license_uri_json
    ):
        errors = validate_records(
            json.loads(dcatus_bad_license_uri_json), "dcatus1.1: non-federal dataset"
        )

        assert errors == [
            (
                "https://www.arcgis.com/home/item.html?id=99731bb0369848169d98f31ce83fb0e2",  # noqa: E501
                "$.license, 'center' does not match any of the acceptable formats: 'uri', 'null', '^(\\\\[\\\\[REDACTED).*?(\\\\]\\\\])$'",  # noqa: E501
            )
        ]

    def test_dcatus1_1_falls_back_to_dataset_position(self, dcatus_no_identifier_json):
        errors = validate_records(
            json.loads(dcatus_no_identifier_json), "dcatus1.1: non-federal dataset"
        )

        assert errors == [(0, "$, 'identifier' is a required property")]

    def test_dcatus3_errors_carry_the_json_path(
        self, dcatus_3_catalog_missing_identifier
    ):
        errors = validate_records(
            json.loads(dcatus_3_catalog_missing_identifier), "dcatus3.0 catalog"
        )

        assert errors == [("", "$.dataset[0], 'identifier' is a required property")]

    def test_recursion_is_reported_as_too_deeply_nested(self):
        catalog = {"@type": "Catalog", "title": "t", "description": "d", "dataset": []}
        for _ in range(200):
            catalog = {**catalog, "catalog": [catalog]}

        with pytest.raises(CatalogTooDeeplyNested, match=NESTING_TOO_DEEP_MESSAGE):
            validate_records(catalog, "dcatus3.0 catalog")

    def test_missing_dcatus3_definitions_say_how_to_fix_it(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="git submodule update"):
            build_dcatus3_validator(tmp_path)
