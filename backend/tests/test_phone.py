import pytest

from apps.core.phone import InvalidPhoneError, normalize_msisdn


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0712345678", "254712345678"),
        ("0112345678", "254112345678"),
        ("+254 712 345 678", "254712345678"),
        ("254712345678", "254712345678"),
        ("712345678", "254712345678"),
        ("0712-345-678", "254712345678"),
    ],
)
def test_valid_numbers(raw, expected):
    assert normalize_msisdn(raw) == expected


@pytest.mark.parametrize("raw", ["", "12345", "0812345678", "07123456789", "+1 415 555 2671", None])
def test_invalid_numbers(raw):
    with pytest.raises(InvalidPhoneError):
        normalize_msisdn(raw)
