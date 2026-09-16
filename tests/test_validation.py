import pytest

from app.errors import ApiError
from app.validation import validate_lead


def test_valid_lead_is_normalized():
    lead = validate_lead(
        {
            "full_name": "  Jane Doe  ",
            "email": " Jane@Example.COM ",
            "estimated_value": 1250,
        }
    )
    assert lead["full_name"] == "Jane Doe"
    assert lead["email"] == "jane@example.com"
    assert lead["estimated_value"] == "1250.00"


def test_stage_must_be_allowlisted():
    with pytest.raises(ApiError) as error:
        validate_lead({"full_name": "Jane", "stage": "root"})
    assert error.value.status_code == 422

