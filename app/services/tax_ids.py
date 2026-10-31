"""GSTIN and PAN validation (FR-04, AUD-028).

Both identifiers are validated in two steps: the format (and the embedded
PAN), then the check character. The algorithms are the published ones:

- GSTIN: 15 characters — 2-digit state code, 10-character PAN, 1-digit entity
  number, the letter Z, then a base-36 check character. The check character is
  computed over the first 14 characters with alternating weights 1 and 2; each
  product is folded as (product // 36) + (product % 36) and the check is
  (36 - total % 36) % 36.
- PAN: 5 letters, 4 digits, 1 letter, where the fourth character must be one
  of C P F H A T B L J G. The tenth character is a mod-26 check over the first
  nine with position weights 1..9.

The tax adviser must still confirm these rules in writing before go-live
(evidence E-022); no rate or code above is a tax opinion.
"""
import re
import string

# ---------------------------------------------------------------- GSTIN
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
_GST_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _gstin_check_char(first14: str) -> str:
    total = 0
    for i, ch in enumerate(first14):
        value = _GST_ALPHABET.index(ch)
        product = value * (1 if i % 2 == 0 else 2)
        total += product // 36 + product % 36
    return _GST_ALPHABET[(36 - total % 36) % 36]


def gstin_state_code(gstin: str) -> str:
    return gstin[:2]


def gstin_problems(gstin: str) -> list[str]:
    """Everything wrong with a GSTIN (empty list = valid)."""
    g = (gstin or "").strip().upper()
    if not g:
        return ["GSTIN is required for a registered supplier"]
    if len(g) != 15:
        return ["GSTIN must be 15 characters"]
    if not GSTIN_RE.match(g):
        return ["GSTIN format is invalid (state code, PAN, entity number, Z, check character)"]
    from ..core.india_states import STATE_CODES
    if g[:2] not in STATE_CODES:
        return [f"GSTIN state code {g[:2]} is not a known Indian state or union territory"]
    if _gstin_check_char(g[:14]) != g[14]:
        return ["GSTIN check character does not match (typo or fabricated number?)"]
    return []


def validate_gstin(gstin: str) -> str:
    problems = gstin_problems(gstin)
    if problems:
        raise ValueError("; ".join(problems))
    return gstin.strip().upper()


# ---------------------------------------------------------------- PAN
PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
_PAN_FOURTH = {"C": 1, "P": 2, "H": 3, "F": 4, "A": 5, "T": 6, "B": 7, "L": 8, "J": 9, "G": 10}
_PAN_DIGIT = {str(d): 9 - d for d in range(10)}


def pan_value(ch: str, index: int) -> int | None:
    if index == 3:
        return _PAN_FOURTH.get(ch)
    if ch.isdigit():
        return _PAN_DIGIT.get(ch)
    return string.ascii_uppercase.find(ch) + 1 if ch in string.ascii_uppercase else None


def _pan_check_char(first9: str) -> str:
    total = sum(pan_value(ch, i) * (i + 1) for i, ch in enumerate(first9))
    rem = total % 26
    return "Z" if rem == 0 else string.ascii_uppercase[rem - 1]


def pan_problems(pan: str) -> list[str]:
    p = (pan or "").strip().upper()
    if not p:
        return []
    if not PAN_RE.match(p):
        return ["PAN format is invalid (5 letters, 4 digits, 1 letter)"]
    if p[3] not in _PAN_FOURTH:
        return ["PAN fourth character must be one of C P F H A T B L J G"]
    if _pan_check_char(p[:9]) != p[9]:
        return ["PAN check character does not match (typo or fabricated number?)"]
    return []


def validate_pan(pan: str) -> str:
    problems = pan_problems(pan)
    if problems:
        raise ValueError("; ".join(problems))
    return pan.strip().upper()


def identity_problems(registration_type: str, gstin: str | None, pan: str | None,
                      state_code: str | None, require_state: bool = True) -> list[str]:
    """Everything wrong with a party's tax identity (empty list = valid).

    Shared by the supplier master, the company profile and the distributor
    master so the same rules apply wherever a GSTIN is entered.

    `require_state` is False for a distributor that may simply not have its
    place of supply recorded yet: the record stays honestly incomplete instead
    of inventing a state, and the tax engine refuses to quote without one.
    """
    from ..core.india_states import STATE_CODES

    if registration_type not in ("regular", "composition", "unregistered"):
        return ["registration_type must be regular, composition or unregistered"]
    state = (state_code or "").strip().upper() or None
    g = (gstin or "").strip().upper() or None
    p = (pan or "").strip().upper() or None

    if registration_type == "unregistered":
        if g:
            return ["An unregistered party cannot have a GSTIN"]
        if not state:
            if require_state:
                return ["state_code is required (place of supply)"]
            return pan_problems(p) if p else []
        if state not in STATE_CODES:
            return [f"Unknown state code {state}"]
        return pan_problems(p) if p else []

    if not g:
        return ["GSTIN is required for a registered party"]
    problems = gstin_problems(g)
    if problems:
        return problems
    derived = g[:2]
    if state and state != derived:
        from ..core.india_states import state_name
        return [f"GSTIN belongs to state {derived} ({state_name(derived)}), not {state}"]
    if p and p != g[2:12]:
        return [f"PAN does not match the GSTIN (GSTIN embeds {g[2:12]})"]
    return []


def normalize_identity(registration_type: str, gstin: str | None, pan: str | None,
                       state_code: str | None, require_state: bool = True) -> dict:
    """Validate a tax identity and return the values to store.

    Raises ValueError with a readable message; the API layer turns that into a
    422. The state and PAN of a registered party are taken from the GSTIN.
    """
    problems = identity_problems(registration_type, gstin, pan, state_code, require_state)
    if problems:
        raise ValueError("; ".join(problems))
    g = (gstin or "").strip().upper() or None
    p = (pan or "").strip().upper() or None
    state = (state_code or "").strip().upper() or None
    if registration_type == "unregistered":
        return {"gstin": None, "pan": p, "state_code": state}
    return {"gstin": g, "pan": p or g[2:12], "state_code": g[:2]}


# ---------------------------------------------------------------- fixtures
def make_gstin(state_code: str, pan: str) -> str:
    """Build a syntactically valid GSTIN for tests and demo fixtures.
    Fixtures must never use a real taxpayer's identifiers."""
    first14 = f"{state_code}{pan}1Z"
    return first14 + _gstin_check_char(first14)


def make_pan(letters: str = "AAACX", digits: str = "1234") -> str:
    """Build a checksum-valid PAN for tests and demo fixtures.

    `letters` is the five-letter block (its fourth character must be one of the
    permitted holder types), `digits` the four digits that make each fixture
    PAN distinct."""
    if len(letters) != 5 or len(digits) != 4 or not digits.isdigit():
        raise ValueError("a fixture PAN needs five letters and four digits")
    stem = f"{letters}{digits}"
    return stem + _pan_check_char(stem)
