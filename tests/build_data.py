"""Builds verifier/data.py from the frozen USPS snapshot in tests/usps/.

    uv run python tests/build_data.py

Three files, each downloaded on SNAPSHOT_DAY and gzipped; each page is checked against its SHA-256 (taken before
gzip) before anything is read:

- notice123.htm.gz: Notice 123, the USPS price list, https://pe.usps.com/text/dmm300/Notice123.htm. Its USPS Ground
  Advantage - Retail table gives the price of each weight tier in each zone, and the oversized price; its notes give
  the nonstandard fees and the sizes they start at.
- dmm133.htm.gz: section 133 of the Domestic Mail Manual, https://pe.usps.com/text/dmm300/133.htm, which says how a
  dimensional weight is worked out.
- zone-charts.json.gz: {prefix: response} for every 3-digit origin ZIP prefix 000 to 999, each response the
  domestic zone chart https://postcalc.usps.com/DomesticZoneChart/GetZoneChart?zipCode3Digit=<prefix> returned
  for a parcel shipped on SNAPSHOT_DAY.

The rules:

- A chart gives a zone to each destination prefix or range of prefixes. A * (same network distribution center) or
  + (some of its 5-digit ZIP codes have their own zone) after a zone does not change it. A prefix with no chart, or a
  destination prefix its chart leaves out, has no zone. Prefixes not in use and military post offices have no chart;
  nor has 967 (Hawaii outside Honolulu), whose chart USPS's tool refuses ("Access is Denied."). As a destination,
  every chart writes 967 as 96700.
- A chart's 5-digit exceptions override the prefix's zone: for every parcel when they name no service, only for a
  parcel under 1 pound when they name USPS Ground Advantage (< 16 oz.), and never when they name Priority Mail.
- A tier is a row of the price table, named as Notice 123 names it, with a pound added to a bare number: 4 oz, ...,
  15.999 oz, 1 lb, ..., 70 lb. Its most weight is in pounds, 16 ounces to the pound. Prices are kept as written.
- Every number a rule uses is read from the pages, and the sentences that state the rules are checked to be there.
"""

from __future__ import annotations

import gzip
import hashlib
import html
import json
import re
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path

HERE = Path(__file__).parent
USPS = HERE / "usps"
TARGET = HERE.parent / "verifier" / "data.py"
SNAPSHOT_DAY = "2026-10-26"
SHA256 = {
    "notice123.htm.gz": "25c53f5edf704ffb88e3ad19d43473e36187e37b25c52d6a17ae158c6be538b8",
    "dmm133.htm.gz": "c94c63cb511acc189b74d66ebc03842be46aaf6b6bb63b91fcbc0db66f8ee09e",
    "zone-charts.json.gz": "20d34d6fb6c9a319b52410608608dba48382eddf276f8671c7cc2b796db5b651",
}
# Why a prefix has no chart: not in use, a military post office, or (967, on Hawaii) refused by USPS's chart tool,
# which gives its zones only pair by pair.
NO_CHART = {
    "No Zones found for the entered ZIP Code.",
    'Please use the "Get Zone for ZIP Code Pair" tab for all inbound APO/FPO/DPO.',
    "Access is Denied.",
}
# The charts write the destination prefix 967 as 96700.
HAWAII = {"96700": "967"}
MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]
GROUND_ADVANTAGE_UNDER_1_LB = "USPS Ground Advantage (< 16 oz.)"
PRIORITY_MAIL = "Priority Mail service"


def read(name: str) -> str:
    data = gzip.decompress((USPS / name).read_bytes())
    if hashlib.sha256(data).hexdigest() != SHA256[name]:
        raise SystemExit(f"tests/usps/{name} is not the pinned snapshot: its SHA-256 differs")
    return data.decode("utf-8")


def text(page: str) -> str:
    """``page`` as plain text: tags dropped, entities decoded, runs of spaces made one."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).split())


def day(written: str) -> str:
    """A date written like October 4, 2026 as YYYY-MM-DD."""
    month, number, year = re.fullmatch(r"(\w+) (\d{1,2}), (\d{4})", written).groups()
    return f"{year}-{MONTHS.index(month) + 1:02d}-{int(number):02d}"


def found(pattern: str, page: str) -> re.Match:
    match = re.search(pattern, page)
    if not match:
        raise SystemExit(f"the snapshot no longer says {pattern!r}")
    return match


class Cells(HTMLParser):
    """The text of each data cell of each row of a page's first table; header cells are kept apart."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self.headers: list[list[str]] = []
        self.cell: list[str] | None = None
        self.done = False

    def handle_starttag(self, tag, attrs) -> None:
        if self.done:
            return
        if tag == "tr":
            self.rows.append([])
            self.headers.append([])
        elif tag in ("td", "th"):
            self.cell = []

    def handle_endtag(self, tag) -> None:
        if self.done:
            return
        if tag in ("td", "th") and self.cell is not None:
            (self.rows if tag == "td" else self.headers)[-1].append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "table":
            self.done = True

    def handle_data(self, data) -> None:
        if self.cell is not None:
            self.cell.append(data)


def prices() -> tuple[str, list[tuple[str, str]], dict[int, list[str]], dict[int, str], dict[str, str], dict]:
    """The prices' effective day, the tiers, each zone's tier prices and oversized price, the fees, and the size
    rules, from Notice 123."""
    page = read("notice123.htm.gz")
    effective = day(found(r"Notice 123 • Effective (\w+ \d{1,2}, \d{4})", text(page)).group(1))
    start = page.index("<h2>USPS Ground Advantage-Retail</h2>")
    section = page[start : page.index("<h2>", start + 1)]
    table = Cells()
    table.feed(section)
    if [cells for cells in table.headers if cells][1] != [str(zone) for zone in range(1, 10)]:
        raise SystemExit("the price table's columns are no longer zones 1 to 9")
    tiers, by_zone, oversized = [], {zone: [] for zone in range(1, 10)}, {}
    for weight, *cells in (row for row in table.rows if row):
        money = [cell.removeprefix("$") for cell in cells]
        if len(money) != 9 or not all(re.fullmatch(r"[0-9]+\.[0-9]{2}", cell) for cell in money):
            raise SystemExit(f"the {weight} row is not nine prices")
        if weight == "Oversized":
            oversized = dict(zip(range(1, 10), money))
            continue
        ounces = re.fullmatch(r"([0-9.]+) oz", weight)
        if ounces:
            tiers.append((weight, format((Decimal(ounces.group(1)) / 16).normalize(), "f")))
        else:
            tiers.append((f"{int(weight)} lb", str(int(weight))))
        for zone, price in zip(range(1, 10), money):
            by_zone[zone].append(price)
    notes = text(section)
    fees = {
        "length_over_22_in": found(
            r"exceed 22 inches but not greater than 30 inches in length, add \$([0-9.]+)", notes
        ),
        "length_over_30_in": found(r"exceed 30 inches in length, add \$([0-9.]+)", notes),
        "volume_over_2_cu_ft": found(r"exceed 2 cubic feet \(3456 cubic inches\), add \$([0-9.]+)", notes),
    }
    oversize = found(r"more than ([0-9]+) inches but not more than ([0-9]+) inches, use the oversized price", notes)
    cube = found(
        r"exceed one cubic foot \(([0-9,]+) cubic inches\) are charged based on the actual weight or the "
        r"dimensional weight, whichever is greater",
        notes,
    )
    rules = {
        "max_weight": tiers[-1][1],
        "max_length_plus_girth": oversize.group(2),
        "oversized_length_plus_girth": oversize.group(1),
        "dimensional_volume": cube.group(1).replace(",", ""),
    }
    return effective, tiers, by_zone, oversized, {fee: match.group(1) for fee, match in fees.items()}, rules


def divisor(max_weight: str) -> str:
    """The dimensional weight divisor from DMM 133, once its rules are checked to be the ones the verifier follows."""
    page = text(read("dmm133.htm.gz"))
    found(r"Round up \(see 604\.7\.0 \) each measurement to the nearest whole inch", page)
    found(r"rounding off \(see 604\.7\.0 \) each measurement to the nearest whole inch and multiplying", page)
    found(
        rf"If the dimensional weight exceeds {max_weight} pounds, the customer pays the {max_weight}-pound price", page
    )
    found(
        r"Except for oversized price parcels, a USPS Ground Advantage . Retail .{0,60} is subject to a nonstandard fee",
        page,
    )
    divisors = set(re.findall(r"divide the result by ([0-9]+) and round up", page))
    if len(divisors) != 1:
        raise SystemExit(f"DMM 133 gives {sorted(divisors)} as the dimensional weight divisor")
    return divisors.pop()


def prefixes(written: str) -> range:
    """A chart's ZIP code text, 123 or 123---125 (or 5 digits), as numbers."""
    first, _, last = written.partition("---")
    return range(int(first), int(last or first) + 1)


def charts() -> tuple[str, dict[str, str], dict[str, list[tuple[str, str, int, bool]]]]:
    """The charts' effective day; origin prefix -> the zone to each destination prefix (- for none); and origin
    prefix -> its 5-digit exceptions that apply to USPS Ground Advantage."""
    responses = json.loads(read("zone-charts.json.gz"))
    if sorted(responses) != [f"{prefix:03d}" for prefix in range(1000)]:
        raise SystemExit("zone-charts.json.gz must hold the chart of every prefix 000 to 999")
    effective, zones, exceptions = set(), {}, {}
    for origin, response in sorted(responses.items()):
        columns = [entry for key in sorted(response) if key.startswith("Column") for entry in response[key] or []]
        if not columns:
            if response["PageError"] not in NO_CHART:
                raise SystemExit(f"{origin} has no chart for an unknown reason, {response['PageError']!r}")
            continue
        effective.add(response["EffectiveDate"])
        row = ["-"] * 1000
        for entry in columns:
            zone = re.fullmatch(r"([1-9])\*?\+?", entry["Zone"]).group(1)
            if entry["MailService"]:
                raise SystemExit(f"{origin}'s chart names a service for prefixes {entry['ZipCodes']}")
            written = HAWAII.get(entry["ZipCodes"], entry["ZipCodes"])
            if not re.fullmatch(r"[0-9]{3}(---[0-9]{3})?", written):
                raise SystemExit(f"{origin}'s chart gives a zone to {written!r}, which is no prefix")
            for prefix in prefixes(written):
                if row[prefix] != "-":
                    raise SystemExit(f"{origin}'s chart gives {prefix:03d} two zones")
                row[prefix] = zone
        zones[origin] = "".join(row)
        kept = []
        for entry in response.get("Zip5Digit") or []:
            service = entry["MailService"]
            if service not in ("", GROUND_ADVANTAGE_UNDER_1_LB, PRIORITY_MAIL):
                raise SystemExit(f"{origin}'s chart names an unknown service, {service!r}")
            if service == PRIORITY_MAIL:
                continue
            span = prefixes(entry["ZipCodes"])
            if any(row[number // 100] == "-" for number in (span[0], span[-1])):
                raise SystemExit(f"{origin}'s exception {entry['ZipCodes']} is in a prefix with no zone")
            kept.append((f"{span[0]:05d}", f"{span[-1]:05d}", int(entry["Zone"]), service != ""))
        for one in kept:
            for other in kept:
                if one is not other and one[0] <= other[1] and other[0] <= one[1]:
                    raise SystemExit(f"{origin}'s exceptions {one} and {other} overlap")
        if kept:
            exceptions[origin] = kept
    if len(effective) != 1:
        raise SystemExit(f"the charts take effect on several days: {sorted(effective)}")
    return day(effective.pop()), zones, exceptions


def build() -> dict:
    effective, tiers, by_zone, oversized, fees, rules = prices()
    zones_effective, zones, exceptions = charts()
    return {
        "prices_effective": effective,
        "zones_effective": zones_effective,
        "rules": {**rules, "dimensional_divisor": divisor(rules["max_weight"])},
        "fees": fees,
        "tiers": tiers,
        "prices": by_zone,
        "oversized": oversized,
        "zones": zones,
        "exceptions": exceptions,
    }


def quoted(text: str) -> str:
    """``text`` as a double-quoted Python string, the way ruff formats one."""
    return json.dumps(text, ensure_ascii=False)


def exception(first: str, last: str, zone: int, under_1_lb: bool) -> str:
    return f"{first}-{last}:{zone}:{'under_1_lb' if under_1_lb else 'all'}"


def render(data: dict) -> str:
    lines = [
        '"""USPS Ground Advantage retail prices and the domestic zone charts: a frozen snapshot, built by',
        f"tests/build_data.py from tests/usps/ (downloaded {SNAPSHOT_DAY}), which says how.",
        "",
        "This is the one copy of the data. The plugin's tools read it, and the verifier judges every tool output and every",
        "answer against it, so no verdict trusts what a tool returned.",
        "",
        (
            f"Prices take effect {data['prices_effective']} and zones {data['zones_effective']}; "
            f'{len(data["tiers"])} weight tiers; zone charts from {len(data["zones"])} origin prefixes."""'
        ),
        "",
        f"PRICES_EFFECTIVE = {quoted(data['prices_effective'])}",
        f"ZONES_EFFECTIVE = {quoted(data['zones_effective'])}",
        "",
        "# the limits and rules of a USPS Ground Advantage retail parcel, in pounds, inches and cubic inches",
        "RULES = {",
        *(f"    {quoted(name)}: {quoted(value)}," for name, value in data["rules"].items()),
        "}",
        "",
        "# nonstandard fee -> its amount in dollars",
        "FEES = {",
        *(f"    {quoted(fee)}: {quoted(amount)}," for fee, amount in data["fees"].items()),
        "}",
        "",
        "# every weight tier, lightest first: (its name, the most it may weigh in pounds)",
        "TIERS = [",
        *(f"    ({quoted(name)}, {quoted(most)})," for name, most in data["tiers"]),
        "]",
        "",
        "# zone -> the price of each tier, in TIERS' order, space-separated",
        "PRICES = {",
        *(f"    {zone}: {quoted(' '.join(values))}," for zone, values in data["prices"].items()),
        "}",
        "",
        "# zone -> the oversized price",
        "OVERSIZED = {",
        *(f"    {zone}: {quoted(price)}," for zone, price in data["oversized"].items()),
        "}",
        "",
        "# origin prefix -> the zone to each destination prefix 000 to 999, a character each: 1 to 9, or - for none",
        "ZONES = {",
        *(f"    {quoted(origin)}: {quoted(row)}," for origin, row in data["zones"].items()),
        "}",
        "",
        "# origin prefix -> its 5-digit exceptions, space-separated: first-last ZIP code:zone:the parcels it applies to,",
        "# all or under_1_lb",
        "EXCEPTIONS = {",
        *(
            f"    {quoted(origin)}: {quoted(' '.join(exception(*each) for each in kept))},"
            for origin, kept in data["exceptions"].items()
        ),
        "}",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    TARGET.write_text(render(build()), encoding="utf-8")
    print(f"wrote {TARGET}")
