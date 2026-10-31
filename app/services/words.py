"""An amount written in words, in the Indian numbering system (FR-14).

A tax invoice must carry the total in words as well as in figures. The wording
follows the Indian grouping (crore, lakh, thousand) and the paise are written
out when the amount is not a whole number of rupees.
"""
from decimal import Decimal, ROUND_HALF_UP

ONES = ("", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
        "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
        "Seventeen", "Eighteen", "Nineteen")
TENS = ("", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety")


def _below_hundred(n: int) -> str:
    if n < 20:
        return ONES[n]
    return (TENS[n // 10] + (" " + ONES[n % 10] if n % 10 else "")).strip()


def _below_thousand(n: int) -> str:
    if n < 100:
        return _below_hundred(n)
    return (ONES[n // 100] + " Hundred" + (" " + _below_hundred(n % 100) if n % 100 else "")).strip()


def _indian(n: int) -> str:
    """12345678 -> "One Crore Twenty Three Lakh Forty Five Thousand Six Hundred Seventy Eight"."""
    if n == 0:
        return "Zero"
    parts: list[str] = []
    crore, n = divmod(n, 10_000_000)
    lakh, n = divmod(n, 100_000)
    thousand, n = divmod(n, 1_000)
    if crore:
        parts.append(f"{_indian(crore)} Crore")
    if lakh:
        parts.append(f"{_below_hundred(lakh)} Lakh")
    if thousand:
        parts.append(f"{_below_thousand(thousand)} Thousand")
    if n:
        parts.append(_below_thousand(n))
    return " ".join(parts)


def amount_in_words(amount: Decimal | int | float | str) -> str:
    """The amount as words, e.g. "Rupees One Thousand Two Hundred Only"."""
    value = Decimal(str(amount)).quantize(Decimal("0.01"), ROUND_HALF_UP)
    negative = value < 0
    value = abs(value)
    rupees = int(value)
    paise = int((value - rupees) * 100)
    words = f"Rupees {_indian(rupees)}"
    if paise:
        words += f" and {_below_hundred(paise)} Paise"
    words += " Only"
    return ("Minus " + words) if negative else words
