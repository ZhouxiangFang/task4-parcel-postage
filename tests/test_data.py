"""The data and the tools: the snapshot is the pinned one and data.py is built from it, zones agree with the raw charts
read apart from data.py and with USPS's own answers for ZIP code pairs, prices agree with cells read off Notice 123 by
hand, every price agrees with one worked out apart from checks.py (fractions and math.ceil), and the tools are true to
the data."""

from __future__ import annotations

import gzip
import json
import math
import random
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import pytest
from build_data import TARGET, USPS, build, render

from contract import CalculateInput, Fee, RateInput, RulesInput, Service, Status, ZoneInput
from plugin.postage import calculate, get_rate_table, get_service_rules, lookup_zone
from verifier.checks import EXCEPTION, evaluate, expected, zones
from verifier.data import FEES, OVERSIZED, PRICES, RULES, TIERS, ZONES

CHARTS = json.loads(gzip.decompress((USPS / "zone-charts.json.gz").read_bytes()))
GROUND = Service.GROUND_ADVANTAGE

# Zones USPS's ZIP code pair lookup (https://postcalc.usps.com/DomesticZoneChart, "Get Zone for ZIP Code Pair") gave
# on 2026-10-26, apart from the charts.
PAIRS = [
    ("77005", "10001", 7),
    ("77005", "77005", 1),
    ("10001", "90210", 8),
    ("99501", "96910", 8),  # Anchorage to Guam
    ("33101", "98101", 8),
    ("60601", "60614", 1),
    ("02108", "00601", 7),  # Boston to Puerto Rico
    ("77005", "96799", 8),  # American Samoa
    ("96813", "96720", 1),  # Honolulu to Hilo: the charts write 967 as 96700
    ("80202", "59001", 4),
    ("20500", "99801", 8),
]

# Prices read off Notice 123's USPS Ground Advantage - Retail table by hand: (tier, zone, price).
CELLS = [
    ("4 oz", 1, "8.40"),
    ("8 oz", 9, "10.20"),
    ("15.999 oz", 9, "13.65"),
    ("1 lb", 1, "10.05"),
    ("3 lb", 7, "19.70"),
    ("20 lb", 4, "28.55"),
    ("21 lb", 4, "36.30"),
    ("46 lb", 7, "142.35"),
    ("70 lb", 1, "68.00"),
    ("70 lb", 9, "204.30"),
]


def chart_zone(origin: str, destination: str, under_1_lb: bool) -> int | None:
    """The zone read straight off the raw chart response with a linear scan: the destination prefix's zone, then any
    5-digit exception that applies to USPS Ground Advantage at this weight."""
    response = CHARTS[origin[:3]]
    zone = None
    for key, entries in response.items():
        for entry in entries if key.startswith("Column") and entries else []:
            low, _, high = entry["ZipCodes"].partition("---")
            low, high = low[:3], high[:3]  # 96700 is the prefix 967
            if int(low) <= int(destination[:3]) <= int(high or low):
                zone = int(entry["Zone"][0])
    if zone is None:
        return None
    for entry in response.get("Zip5Digit") or []:
        low, _, high = entry["ZipCodes"].partition("---")
        service = entry["MailService"]
        applies = service == "" or (under_1_lb and service.startswith("USPS Ground Advantage"))
        if applies and int(low) <= int(destination) <= int(high or low):
            zone = int(entry["Zone"])
    return zone


def test_the_snapshot_is_the_pinned_one_and_data_py_is_built_from_it() -> None:
    assert TARGET.read_text(encoding="utf-8") == render(build())


def test_the_rules_and_fees_are_notice_123_and_dmm_133s() -> None:
    assert RULES == {
        "max_weight": "70",
        "max_length_plus_girth": "130",
        "oversized_length_plus_girth": "108",
        "dimensional_volume": "1728",
        "dimensional_divisor": "139",  # 166 until July 12, 2026
    }
    assert FEES == {fee.value: amount for fee, amount in zip(Fee, ["4.50", "10.00", "21.00"])}


def test_the_tiers_are_four_ounce_steps_then_every_pound() -> None:
    assert TIERS[:5] == [
        ("4 oz", "0.25"),
        ("8 oz", "0.5"),
        ("12 oz", "0.75"),
        ("15.999 oz", "0.9999375"),
        ("1 lb", "1"),
    ]
    assert TIERS[4:] == [(f"{pounds} lb", str(pounds)) for pounds in range(1, 71)]
    for zone in range(1, 10):
        prices = [Decimal(price) for price in PRICES[zone].split()]
        assert len(prices) == len(TIERS) and prices == sorted(prices)  # never cheaper for more weight
        assert Decimal(OVERSIZED[zone]) > prices[-1]


@pytest.mark.parametrize(("tier", "zone", "price"), CELLS)
def test_prices_are_the_cells_read_by_hand(tier: str, zone: int, price: str) -> None:
    assert PRICES[zone].split()[[name for name, _ in TIERS].index(tier)] == price


def test_oversized_prices_are_the_cells_read_by_hand() -> None:
    assert (OVERSIZED[1], OVERSIZED[5], OVERSIZED[8], OVERSIZED[9]) == ("116.00", "211.30", "301.75", "301.75")


def test_every_charted_origin_has_a_zone_row_and_no_other_does() -> None:
    charted = sorted(origin for origin, response in CHARTS.items() if response.get("Column0"))
    assert sorted(ZONES) == charted and all(len(row) == 1000 for row in ZONES.values())
    for origin in ["000", "090", "213", "967"]:  # unused, military, unused, unused
        assert origin not in ZONES
    assert set(EXCEPTION) <= set(ZONES)


def test_zones_agree_with_the_raw_charts() -> None:
    rng = random.Random(580)
    origins = sorted(ZONES)
    pairs = [(f"{origin}{rng.randint(0, 99):02d}", f"{rng.randint(0, 99999):05d}") for origin in origins]
    for origin, kept in EXCEPTION.items():  # every exception's ends, and just past them
        for first, last, _, _ in kept:
            for number in (int(first) - 1, int(first), int(last), int(last) + 1):
                pairs.append((f"{origin}00", f"{number:05d}"))
    for origin, destination in pairs:
        found = zones(origin, destination)
        heavy, light = chart_zone(origin, destination, False), chart_zone(origin, destination, True)
        assert found == (None if heavy is None else (heavy, light)), (origin, destination)


@pytest.mark.parametrize(("origin", "destination", "zone"), PAIRS)
def test_zones_agree_with_usps_pair_lookup(origin: str, destination: str, zone: int) -> None:
    assert zones(origin, destination)[0] == zone


def test_hilo_has_no_chart() -> None:
    # USPS's pair lookup gives 96720 to 10001 zone 8, but its chart tool refuses 967's chart, so the snapshot has none.
    assert CHARTS["967"]["PageError"] == "Access is Denied." and zones("96720", "10001") is None


def test_military_and_pacific_zip_codes() -> None:
    assert zones("77005", "09021") == (7, 5)  # APO AE: zone 5 only under 1 pound
    assert zones("77005", "96349") == (7, 5)  # FPO AP
    assert zones("77005", "96910") == (8, 8)  # Guam, a 5-digit exception for every parcel
    assert zones("77005", "96939") == (9, 9)  # Palau keeps its prefix's zone
    assert zones("77005", "77005") == (1, 1) and zones("77005", "77100") is None  # 771 is not in use


def price_by_hand(trip: tuple[str, str, str, str, str, str]) -> tuple:
    """(zone, tier, postage, fees, total) for a parcel that can be mailed, worked out with fractions and math.ceil from
    the raw charts and the tiers' prices."""
    origin, destination, weight, *sides_text = trip
    pounds, sides = Fraction(weight), sorted((Fraction(side) for side in sides_text), reverse=True)
    zone = chart_zone(origin[:5], destination[:5], pounds < 1)
    size = sides[0] + 2 * (sides[1] + sides[2])
    if size > 108:
        return zone, "oversized", OVERSIZED[zone], [], OVERSIZED[zone]
    cube = math.prod(math.ceil(side) for side in sides)
    dimensional = min(math.ceil(Fraction(cube, 139)), 70) if cube > 1728 else 0
    billed = max(pounds, dimensional)
    rows = zip(TIERS, PRICES[zone].split())
    tier, price = next((name, price) for (name, most), price in rows if Fraction(most) >= billed)
    fees = [Fee.LENGTH_OVER_30_IN] if sides[0] > 30 else [Fee.LENGTH_OVER_22_IN] if sides[0] > 22 else []
    if math.prod(math.floor(side + Fraction(1, 2)) for side in sides) > 3456:
        fees.append(Fee.VOLUME_OVER_2_CU_FT)
    total = Decimal(price) + sum(Decimal(FEES[fee.value]) for fee in fees)
    return zone, tier, price, [(fee, FEES[fee.value]) for fee in fees], f"{total}"


def test_prices_agree_with_fractions_and_the_raw_charts() -> None:
    rng = random.Random(580)
    origins = sorted(ZONES)
    done = 0
    for _ in range(3000):
        origin, destination = (f"{rng.choice(origins)}{rng.randint(0, 99):02d}" for _ in range(2))
        weight = f"{rng.randint(0, 72)}.{rng.randint(1, 9999):04d}"
        sides = [f"{rng.randint(0, 50)}.{rng.randint(1, 99):02d}" for _ in range(3)]
        status, *got = expected(origin, destination, weight, *sides)
        if chart_zone(origin, destination, False) is None:
            assert status is Status.NO_ZONE
            continue
        if Fraction(weight) > 70:
            assert status is Status.TOO_HEAVY
            continue
        ordered = sorted((Fraction(side) for side in sides), reverse=True)
        if ordered[0] + 2 * (ordered[1] + ordered[2]) > 130:
            assert status is Status.TOO_LARGE
            continue
        assert status is Status.PRICED and tuple(got[1:]) == price_by_hand((origin, destination, weight, *sides))
        done += 1
    assert done > 1500


# Parcels from 77005 (Houston) to 10001 (New York), zone 7, worked out by hand from the rules and the table.
NEW_YORK = ("77005", "10001")
LONG, VERY_LONG, LARGE = Fee.LENGTH_OVER_22_IN, Fee.LENGTH_OVER_30_IN, Fee.VOLUME_OVER_2_CU_FT


@pytest.mark.parametrize(
    ("parcel", "status", "tier", "postage", "fees", "total"),
    [
        (("2.3", "10", "8", "4"), Status.PRICED, "3 lb", "19.70", [], "19.70"),  # the README's example
        (("0.3", "6", "4", "2"), Status.PRICED, "8 oz", "9.70", [], "9.70"),  # 4.8 ounces
        (("0.25", "6", "4", "2"), Status.PRICED, "4 oz", "9.70", [], "9.70"),  # 4 ounces exactly
        (("0.2501", "6", "4", "2"), Status.PRICED, "8 oz", "9.70", [], "9.70"),
        (("0.9999", "6", "4", "2"), Status.PRICED, "15.999 oz", "12.70", [], "12.70"),  # 15.9984 ounces
        (("0.99995", "6", "4", "2"), Status.PRICED, "1 lb", "12.70", [], "12.70"),  # 15.9992 ounces
        (("1", "6", "4", "2"), Status.PRICED, "1 lb", "12.70", [], "12.70"),
        (("1", "12", "12", "12"), Status.PRICED, "1 lb", "12.70", [], "12.70"),  # 1728 cubic inches exactly
        (("1", "12", "12", "12.01"), Status.PRICED, "14 lb", "47.55", [], "47.55"),  # 13 rounded up: 1872 / 139
        (("5", "18", "14", "12"), Status.PRICED, "22 lb", "74.30", [], "74.30"),  # 3024 / 139 = 21.8
        (("30", "18", "14", "12"), Status.PRICED, "30 lb", "104.80", [], "104.80"),  # heavier than its 22 lb
        (("3", "24", "6", "6"), Status.PRICED, "3 lb", "19.70", [Fee.LENGTH_OVER_22_IN], "24.20"),
        (("3", "22", "6", "6"), Status.PRICED, "3 lb", "19.70", [], "19.70"),  # 22 inches is not over 22
        (("3", "30", "6", "6"), Status.PRICED, "3 lb", "19.70", [Fee.LENGTH_OVER_22_IN], "24.20"),
        (("2", "36", "4", "4"), Status.PRICED, "2 lb", "17.20", [Fee.LENGTH_OVER_30_IN], "27.20"),
        (("1", "15.2", "15.2", "15.2"), Status.PRICED, "30 lb", "104.80", [], "104.80"),  # 16 up, 15 to nearest
        (("1", "15.5", "15.5", "15.5"), Status.PRICED, "30 lb", "104.80", [Fee.VOLUME_OVER_2_CU_FT], "125.80"),
        (("10", "28", "16", "14"), Status.PRICED, "46 lb", "142.35", [LONG, LARGE], "167.85"),  # 6272 / 139
        (("5", "48", "15", "15"), Status.PRICED, "70 lb", "181.65", [VERY_LONG, LARGE], "212.65"),  # 108 in; 78 lb
        (("5", "50", "15", "15"), Status.PRICED, "oversized", "271.20", [], "271.20"),  # 110 inches: no fee
        (("70", "50", "20", "20"), Status.PRICED, "oversized", "271.20", [], "271.20"),  # 130 inches, 70 lb
        (("70.01", "10", "8", "4"), Status.TOO_HEAVY, "", "", [], ""),
        (("2", "50", "20", "20.01"), Status.TOO_LARGE, "", "", [], ""),
        (("0", "10", "8", "4"), Status.INVALID_PARCEL, "", "", [], ""),
        (("2", "10", "8", "0.0"), Status.INVALID_PARCEL, "", "", [], ""),
        (("1/2", "10", "8", "4"), Status.INVALID_PARCEL, "", "", [], ""),
        (("80", "10", "8", "x"), Status.INVALID_PARCEL, "", "", [], ""),  # the parcel first
    ],
)
def test_each_parcel_has_the_price_worked_out_by_hand(parcel, status, tier, postage, fees, total) -> None:
    got = expected(*NEW_YORK, *parcel)
    assert (got[0], got[3], got[4], [fee for fee, _ in got[5]], got[6]) == (status, tier, postage, fees, total)


@pytest.mark.parametrize(
    ("origin", "destination", "weight", "status", "zone", "total"),
    [
        ("77005", "09021", "0.5", Status.PRICED, 5, "9.35"),  # APO AE under 1 pound: zone 5's 8 oz
        ("77005", "09021", "1.5", Status.PRICED, 7, "17.20"),  # and at 2 lb, its prefix's zone 7
        ("77005", "77005", "2", Status.PRICED, 1, "11.30"),
        ("77005-1892", " 10001 ", "2.3", Status.PRICED, 7, "19.70"),  # ZIP+4 and spaces
        ("7700", "10001", "2.3", Status.INVALID_ZIP, 0, ""),
        ("77005", "1000l", "2.3", Status.INVALID_ZIP, 0, ""),
        ("00001", "1000l", "2.3", Status.INVALID_ZIP, 0, ""),  # form before zone
        ("00001", "10001", "2.3", Status.NO_ZONE, 0, ""),
        ("77005", "77100", "2.3", Status.NO_ZONE, 0, ""),
        ("09021", "77005", "2.3", Status.NO_ZONE, 0, ""),
        ("09021", "77005", "99", Status.NO_ZONE, 0, ""),  # zone before weight
    ],
)
def test_each_route_has_the_zone_worked_out_by_hand(origin, destination, weight, status, zone, total) -> None:
    got = expected(origin, destination, weight, "6", "4", "2")
    assert (got[0], got[2], got[6]) == (status, zone, total)


def test_looks_up_both_zones(tmp_path: Path) -> None:
    found = lookup_zone(ZoneInput(origin_zip="77005", destination_zip="09021"), tmp_path)
    assert (found.origin_zip, found.destination_zip, found.zone, found.zone_under_1_lb) == ("77005", "09021", 7, 5)
    with pytest.raises(ValueError, match="invalid ZIP"):
        lookup_zone(ZoneInput(origin_zip="Houston", destination_zip="10001"), tmp_path)
    with pytest.raises(ValueError, match="no zone"):
        lookup_zone(ZoneInput(origin_zip="77005", destination_zip="21301"), tmp_path)


def test_gives_the_rules_and_a_zones_rate_table(tmp_path: Path) -> None:
    rules = get_service_rules(RulesInput(service=GROUND), tmp_path)
    assert (rules.prices_effective, rules.zones_effective) == ("2026-10-04", "2026-10-01")
    assert (rules.max_weight, rules.dimensional_divisor) == ("70", "139")
    table = get_rate_table(RateInput(service=GROUND, zone=7), tmp_path)
    tiers = [(row.tier, row.max_weight, row.price) for row in table.tiers]
    assert tiers[:2] == [("4 oz", "0.25", "9.70"), ("8 oz", "0.5", "9.70")] and tiers[-1] == ("70 lb", "70", "181.65")
    assert table.oversized == "271.20"
    assert [(charge.fee, charge.amount) for charge in table.surcharges] == [
        (LONG, "4.50"),
        (VERY_LONG, "10.00"),
        (LARGE, "21.00"),
    ]
    for zone in [0, 10]:
        with pytest.raises(ValueError, match="no such zone"):
            get_rate_table(RateInput(service=GROUND, zone=zone), tmp_path)


def test_calculates_exactly(tmp_path: Path) -> None:
    assert calculate(CalculateInput(expression="18 * 14 * 12 / 139"), tmp_path).value.startswith("21.755")
    assert evaluate("19.70 + 4.50 + 21.00") == "45.2"
    for bad in ["1/0", "2 *", "(1", "1e5", "ceil(2.5)", ""]:
        with pytest.raises(ValueError):
            evaluate(bad)
