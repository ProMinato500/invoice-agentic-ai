import re
from decimal import Decimal, InvalidOperation

from pint import UnitRegistry

ureg = UnitRegistry()


def number(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    s = str(value).strip().replace("\u00a0", "").replace(" ", "")
    negative = s.startswith("(") and s.endswith(")")
    s = re.sub(r"[^\d,\.\-+]", "", s)
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        s = "".join(parts) if len(parts) > 2 or len(parts[-1]) == 3 else ".".join(parts)
    try:
        result = Decimal(s)
        if not result.is_finite():
            raise ValueError("Non-finite number")
        return -result if negative else result
    except InvalidOperation as exc:
        raise ValueError(f"Unreadable numeric value: {value}") from exc


def identifier(value):
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def unit(value):
    v = (value or "").strip().upper()
    return {
        "EACH": "EA",
        "PCS": "EA",
        "PIECES": "EA",
        "UNIT": "EA",
        "UNITS": "EA",
        "NOS": "EA",
        "LITRES": "L",
        "LITER": "L",
        "MILLILITRE": "ML",
    }.get(v, v)


def attributes(text):
    out = {}
    patterns = {
        "ram": r"(\d+)\s*GB\s*(?:RAM|DDR[345]?)",
        "storage": r"(\d+)\s*(?:GB|TB)\s*(?:SSD|HDD|storage)",
        "cpu": r"\b(i[3579](?:-\d+[A-Z]*)?)\b",
        "power": r"(\d+(?:\.\d+)?\s*(?:kW|HP|W))\b",
        "voltage": r"(\d+(?:\s*[-?]\s*\d+)?\s*V)\b",
        "ip_rating": r"\b(IP\d{2})\b",
        "dimension": r"(\d+(?:\.\d+)?\s*mm)\b",
        "grade": r"\b((?:SS|AISI|grade)\s*\d{3}[A-Z]?)\b",
        "warranty": r"(\d+\s*(?:years?|months?))\s*warranty",
        "model": r"\b(?:model)\s*[:#]?\s*([A-Z0-9][A-Z0-9-]+)",
    }
    for name, pattern in patterns.items():
        m = re.search(pattern, text, re.I)
        if m:
            out[name] = m.group(1).upper().replace(" ", "")
    storage = re.search(r"(\d+)\s*(GB|TB)\s*(?:SSD|HDD|storage)", text, re.I)
    if storage:
        out["storage"] = str(int(storage[1]) * (1024 if storage[2].upper() == "TB" else 1)) + "GB"
    return out


def compare_constraint(expected, actual, operator="EQ"):
    if actual is None or actual == "":
        return "UNKNOWN"
    if operator == "MANDATORY_FEATURE":
        return (
            "PASS" if str(actual).lower() in ("true", "yes", "1", str(expected).lower()) else "FAIL"
        )
    if operator == "MEMBER_OF":
        return "PASS" if actual in expected else "FAIL"
    if operator in ("IN_RANGE", "SUPERSET_RANGE"):
        lo, hi = expected
        return (
            "PASS"
            if (
                actual[0] <= lo and actual[1] >= hi
                if operator == "SUPERSET_RANGE"
                else lo <= actual <= hi
            )
            else "FAIL"
        )
    # Certifications, IP protection classes, model revisions and material grades require exact evidence.
    if re.match(r"^(IP|SS|AISI|ISO|IEC)", str(expected), re.I):
        return "PASS" if identifier(str(expected)) == identifier(str(actual)) else "FAIL"
    try:

        def unit_text(value):
            replacements = {
                "years": "year",
                "year": "year",
                "months": "month",
                "month": "month",
                "gb": "gigabyte",
                "tb": "terabyte",
                "kw": "kilowatt",
                "hp": "horsepower",
                "w": "watt",
                "v": "volt",
                "mm": "millimeter",
            }
            return re.sub(
                r"(years?|months?|GB|TB|kW|HP|mm|V|W)\b",
                lambda m: replacements[m.group(0).lower()],
                str(value),
                flags=re.I,
            )

        a, b = ureg.Quantity(unit_text(expected)), ureg.Quantity(unit_text(actual))
        if a.dimensionality != b.dimensionality:
            return "UNKNOWN"
        ev, av = Decimal(str(a.magnitude)), Decimal(str(b.to(a.units).magnitude))
    except Exception:
        ev, av = str(expected).upper(), str(actual).upper()
    operations = {
        "EQ": lambda: av == ev,
        "NEQ": lambda: av != ev,
        "GTE": lambda: av >= ev,
        "GT": lambda: av > ev,
        "LTE": lambda: av <= ev,
        "LT": lambda: av < ev,
    }
    if operator not in operations:
        return "UNKNOWN"
    try:
        return "PASS" if operations[operator]() else "FAIL"
    except TypeError:
        return "UNKNOWN"


def specs(po, inv, approved=False):
    if not po.attributes:
        if po.description.casefold().strip() != inv.description.casefold().strip() and not approved:
            return "UNKNOWN", [
                {
                    "code": "SPECIFICATION_UNVERIFIED",
                    "severity": "review",
                    "message": "Descriptions differ and no typed specification constraints could be verified.",
                }
            ]
        return "NOT_APPLICABLE", []
    findings = []
    for name, expected in po.attributes.items():
        actual = inv.attributes.get(name)
        result = compare_constraint(expected, actual)
        if result != "PASS":
            findings.append(
                {
                    "code": "SPEC_MISSING" if result == "UNKNOWN" else "SPEC_MISMATCH",
                    "severity": "review" if result == "UNKNOWN" else "error",
                    "message": f"{name}: ordered {expected}; invoiced {actual or 'not stated'}.",
                    "attribute": name,
                }
            )
    if approved:
        return "PASS", []
    return (
        "FAIL"
        if any(f["code"] == "SPEC_MISMATCH" for f in findings)
        else "UNKNOWN"
        if findings
        else "PASS"
    ), findings
