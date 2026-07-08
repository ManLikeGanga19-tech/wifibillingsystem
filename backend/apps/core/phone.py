"""Kenyan MSISDN normalization. Canonical storage format: 2547XXXXXXXX / 2541XXXXXXXX."""

import re


class InvalidPhoneError(ValueError):
    pass


def normalize_msisdn(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("254") and len(digits) == 12 and digits[3] in "17":
        return digits
    if digits.startswith("0") and len(digits) == 10 and digits[1] in "17":
        return "254" + digits[1:]
    if len(digits) == 9 and digits[0] in "17":
        return "254" + digits
    raise InvalidPhoneError(f"Not a valid Kenyan mobile number: {raw!r}")
