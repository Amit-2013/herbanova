"""Indian state and union-territory codes used by GSTINs and place of supply.

These codes are statutory identifiers (CGST Rules), not tax rates: they are a
small fixed list and are not expected to change with a rate revision. The
union territories (marked UT) get UTGST + CGST instead of SGST + CGST when the
place of supply is inside them (Module Phase 3 uses this table).
"""

STATE_CODES: dict[str, tuple[str, bool]] = {
    "01": ("Jammu and Kashmir", False),
    "02": ("Himachal Pradesh", False),
    "03": ("Punjab", False),
    "04": ("Chandigarh", True),
    "05": ("Uttarakhand", False),
    "06": ("Haryana", False),
    "07": ("Delhi", False),
    "08": ("Rajasthan", False),
    "09": ("Uttar Pradesh", False),
    "10": ("Bihar", False),
    "11": ("Sikkim", False),
    "12": ("Arunachal Pradesh", False),
    "13": ("Nagaland", False),
    "14": ("Manipur", False),
    "15": ("Mizoram", False),
    "16": ("Tripura", False),
    "17": ("Meghalaya", False),
    "18": ("Assam", False),
    "19": ("West Bengal", False),
    "20": ("Jharkhand", False),
    "21": ("Odisha", False),
    "22": ("Chhattisgarh", False),
    "23": ("Madhya Pradesh", False),
    "24": ("Gujarat", False),
    "26": ("Dadra and Nagar Haveli and Daman and Diu", True),
    "27": ("Maharashtra", False),
    "29": ("Karnataka", False),
    "30": ("Goa", False),
    "31": ("Lakshadweep", True),
    "32": ("Kerala", False),
    "33": ("Tamil Nadu", False),
    "34": ("Puducherry", True),
    "35": ("Andaman and Nicobar Islands", True),
    "36": ("Telangana", False),
    "37": ("Andhra Pradesh", False),
    "38": ("Ladakh", False),
    "97": ("Other Territory", True),
}


def state_name(code: str) -> str | None:
    entry = STATE_CODES.get(str(code).zfill(2))
    return entry[0] if entry else None


def is_union_territory(code: str) -> bool:
    entry = STATE_CODES.get(str(code).zfill(2))
    return bool(entry and entry[1])
