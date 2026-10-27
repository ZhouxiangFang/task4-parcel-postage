"""The verifier, called as NanoAgent's sandbox calls it, with contract instances built from JSON: every answer to the
task and every tool output, judged against the data. The steps the task's instructions describe, played through the
tools, earn a valid verdict on every sampled parcel."""

from __future__ import annotations

import math
import random
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest
from slimconfig import build_output, plain_output

import verifier
from contract import (
    TOOLS,
    CalculateInput,
    ParcelInput,
    PostageOutput,
    RateInput,
    RulesInput,
    Service,
    Status,
    Tool,
    ZoneInput,
)
from plugin.postage import calculate, get_rate_table, get_service_rules, lookup_zone
from verifier.checks import NUMBER, expected
from verifier.data import ZONES

STATUSES = [status.value for status in Status]
EMPTY = {"zone": 0, "tier": "", "postage": "", "surcharges": [], "total": ""}
SERVICE = "ground_advantage"


def verify(trip: tuple[str, str, str, str, str, str], answer: dict) -> dict:
    """The verdict on an answer to the task; there is no reference."""
    origin, destination, weight, length, width, height = trip
    arguments = build_output(
        {
            "origin_zip": origin,
            "destination_zip": destination,
            "weight": weight,
            "length": length,
            "width": width,
            "height": height,
            "service": SERVICE,
        },
        ParcelInput,
    )
    return verifier.verify_task("price-parcel", arguments, build_output(answer, PostageOutput), None, ".")


def priced(zone: int, tier: str, postage: str, surcharges: list[tuple[str, str]], total: str) -> dict:
    return {
        "status": "priced",
        "zone": zone,
        "tier": tier,
        "postage": postage,
        "surcharges": [{"fee": fee, "amount": amount} for fee, amount in surcharges],
        "total": total,
    }


BOX = ("77005", "10001", "2.3", "10", "8", "4")
RIGHT = priced(7, "3 lb", "19.70", [], "19.70")
# 6272 cubic inches is 46 lb by dimensional weight, with both a length and a volume fee
CRATE = ("77005", "10001", "10", "28", "16", "14")
CRATE_RIGHT = priced(7, "46 lb", "142.35", [("length_over_22_in", "4.50"), ("volume_over_2_cu_ft", "21.00")], "167.85")


def test_accepts_the_right_price() -> None:
    for trip, answer in [(BOX, RIGHT), (CRATE, CRATE_RIGHT)]:
        verdict = verify(trip, answer)
        assert verdict["valid"] is True and verdict["score"] == 1.0, verdict
    # Money may drop trailing zeros, the tier's case and spacing are free, and surcharges come in any order.
    assert verify(BOX, {**RIGHT, "postage": "19.7", "total": "19.700", "tier": " 3  LB "})["valid"] is True
    turned = {**CRATE_RIGHT, "surcharges": CRATE_RIGHT["surcharges"][::-1]}
    assert verify(CRATE, turned)["valid"] is True


@pytest.mark.parametrize(
    ("answer", "wrong", "score"),
    [
        ({**RIGHT, "zone": 6}, "zone", 4 / 5),
        ({**RIGHT, "tier": "2 lb"}, "tier", 4 / 5),  # 2.3 lb rounded down
        ({**RIGHT, "tier": "2.3 lb"}, "tier", 4 / 5),
        ({**RIGHT, "postage": "17.20", "total": "17.20"}, "postage, total", 3 / 5),
        ({**RIGHT, "total": "19.71"}, "total", 4 / 5),
        ({**RIGHT, "total": "$19.70"}, "total", 4 / 5),
        ({**RIGHT, "surcharges": [{"fee": "length_over_22_in", "amount": "4.50"}]}, "surcharges", 4 / 5),
        (priced(0, "", "", [], ""), "zone, tier, postage, total", 1 / 5),
    ],
)
def test_refuses_a_wrong_price_with_partial_credit(answer: dict, wrong: str, score: float) -> None:
    verdict = verify(BOX, answer)
    assert verdict["valid"] is False and verdict["score"] == pytest.approx(score), verdict
    assert verdict["message"].startswith(wrong) and verdict["details"]["expected"]["total"] == "19.70"


@pytest.mark.parametrize(
    "surcharges",
    [
        [],
        [("length_over_22_in", "4.50")],  # one missing
        [("length_over_30_in", "10.00"), ("volume_over_2_cu_ft", "21.00")],  # the wrong length fee
        [("length_over_22_in", "4.50"), ("volume_over_2_cu_ft", "21.00"), ("volume_over_2_cu_ft", "21.00")],  # twice
        [("length_over_22_in", "4.5O"), ("volume_over_2_cu_ft", "21.00")],  # not a number
        [("length_over_22_in", "10.00"), ("volume_over_2_cu_ft", "21.00")],  # the wrong amount
    ],
)
def test_checks_every_surcharge_and_its_amount(surcharges: list[tuple[str, str]]) -> None:
    answer = {**CRATE_RIGHT, "surcharges": [{"fee": fee, "amount": amount} for fee, amount in surcharges]}
    verdict = verify(CRATE, answer)
    assert verdict["valid"] is False and verdict["message"].startswith("surcharges"), verdict


def test_billing_at_the_actual_weight_instead_of_the_dimensional_weight_is_wrong() -> None:
    answer = priced(7, "10 lb", "34.70", [("length_over_22_in", "4.50"), ("volume_over_2_cu_ft", "21.00")], "60.20")
    verdict = verify(CRATE, answer)
    assert verdict["valid"] is False and verdict["message"].startswith("tier, postage, total"), verdict


@pytest.mark.parametrize(
    ("trip", "status"),
    [
        (("77005", "10001", "0", "10", "8", "4"), "invalid_parcel"),
        (("77005", "10001", "2.3", "10", "8", "-4"), "invalid_parcel"),
        (("77005", "10001", "2 lb", "10", "8", "4"), "invalid_parcel"),
        (("77005", "10001", "2.3", "10", "8", ".5"), "invalid_parcel"),
        (("7705", "10001", "2.3", "10", "8", "4"), "invalid_zip"),
        (("77005", "Houston", "2.3", "10", "8", "4"), "invalid_zip"),
        (("77005", "10001 2301", "2.3", "10", "8", "4"), "invalid_zip"),
        (("00001", "10001", "2.3", "10", "8", "4"), "no_zone"),  # no chart for 000
        (("09001", "10001", "2.3", "10", "8", "4"), "no_zone"),  # a military post office has no chart
        (("77005", "21301", "2.3", "10", "8", "4"), "no_zone"),  # 213 is not in use
        (("77005", "10001", "70.01", "10", "8", "4"), "too_heavy"),
        (("77005", "10001", "2.3", "60", "20", "20.5"), "too_large"),  # 60 + 81 = 141 in
        (("77005", "10001", "2.3", "50.01", "20", "20"), "too_large"),
    ],
)
def test_accepts_only_the_status_the_parcel_has(trip, status: str) -> None:
    verdict = verify(trip, {"status": status, **EMPTY})
    assert verdict["valid"] is True and verdict["score"] == 1.0, verdict
    for other in STATUSES:
        if other != status:
            assert verify(trip, {"status": other, **EMPTY})["valid"] is False
    # The other fields go only with priced.
    for field, value in [("zone", 7), ("tier", "3 lb"), ("total", "19.70")]:
        verdict = verify(trip, {"status": status, **EMPTY, field: value})
        assert verdict["valid"] is False and "empty" in verdict["message"]


def test_a_parcel_that_can_be_priced_is_never_another_status() -> None:
    for status in STATUSES[1:]:
        assert verify(BOX, {"status": status, **EMPTY})["valid"] is False


def follow_instructions(trip: tuple[str, str, str, str, str, str], tmp_path: Path) -> dict:
    """The answer the task's instructions lead to, through the tools."""
    origin, destination, weight, *sides_text = trip
    if not all(NUMBER.fullmatch(text.strip()) and Decimal(text.strip()) > 0 for text in [weight, *sides_text]):
        return {"status": "invalid_parcel", **EMPTY}

    def calc(expression: str) -> Decimal:
        return Decimal(calculate(CalculateInput(expression=expression), tmp_path).value)

    try:
        found = lookup_zone(ZoneInput(origin_zip=origin, destination_zip=destination), tmp_path)
    except ValueError as error:
        return {"status": "invalid_zip" if "invalid ZIP" in str(error) else "no_zone", **EMPTY}
    rules = get_service_rules(RulesInput(service=Service.GROUND_ADVANTAGE), tmp_path)
    pounds = Decimal(weight.strip())
    zone = found.zone_under_1_lb if pounds < 1 else found.zone
    if pounds > Decimal(rules.max_weight):
        return {"status": "too_heavy", **EMPTY}
    sides = sorted((Decimal(text.strip()) for text in sides_text), reverse=True)
    size = calc(f"{sides[0]} + 2 * ({sides[1]} + {sides[2]})")
    if size > Decimal(rules.max_length_plus_girth):
        return {"status": "too_large", **EMPTY}
    table = get_rate_table(RateInput(service=Service.GROUND_ADVANTAGE, zone=zone), tmp_path)
    amounts = {charge.fee.value: charge.amount for charge in table.surcharges}
    fees = []
    if size > Decimal(rules.oversized_length_plus_girth):
        tier, postage = "oversized", table.oversized
    else:
        up = [math.ceil(side) for side in sides]
        product = calc(f"{up[0]} * {up[1]} * {up[2]}")
        dimensional = 0
        if product > Decimal(rules.dimensional_volume):
            dimensional = min(math.ceil(calc(f"{product} / {rules.dimensional_divisor}")), int(rules.max_weight))
        billed = max(pounds, dimensional)
        row = next(row for row in table.tiers if Decimal(row.max_weight) >= billed)
        tier, postage = row.tier, row.price
        if sides[0] > 30:
            fees.append("length_over_30_in")
        elif sides[0] > 22:
            fees.append("length_over_22_in")
        nearest = [side.quantize(Decimal(1), rounding=ROUND_HALF_UP) for side in sides]
        if calc(f"{nearest[0]} * {nearest[1]} * {nearest[2]}") > 3456:
            fees.append("volume_over_2_cu_ft")
    total = calc(" + ".join([postage, *(amounts[fee] for fee in fees)]))
    return priced(zone, tier, postage, [(fee, amounts[fee]) for fee in fees], f"{total}")


def test_the_instructions_earn_a_valid_verdict(tmp_path: Path) -> None:
    rng = random.Random(580)
    origins = sorted(ZONES)
    trips = [
        BOX,
        CRATE,
        ("77005", "09021", "0.5", "6", "4", "2"),  # a military ZIP code under 1 pound...
        ("77005", "09021", "1", "6", "4", "2"),  # ...and at 1 pound
        ("77005", "10001", "5", "50", "15", "15"),  # oversized
        ("77005", "10001", "5", "48", "15", "15"),  # 108 in exactly, dimensional weight capped at 70
        ("77005", "10001", "1", "15.5", "15.5", "15.5"),
        ("77005", "10001", "0.25", "12", "12", "12"),
        ("77005", "10001", "0.2501", "12", "12", "12.01"),
        (" 77005 ", "10001-2301", "70", "50", "20", "20"),
    ]
    for _ in range(500):
        origin = f"{rng.choice(origins)}{rng.randint(0, 99):02d}"
        destination = f"{rng.choice(origins)}{rng.randint(0, 99):02d}"
        weight = rng.choice(["0.1", "0.25", "0.3", "0.75", "0.99", "1", "2.3", "13", "35.5", "70", "71", "0", "abc"])
        sides = [rng.choice(["1", "6", "10.5", "12", "15.5", "18", "22.5", "24", "31", "36.2", "48", "60", "-1"])]
        sides += [f"{rng.randint(1, 30)}.{rng.randint(0, 9)}" for _ in range(2)]
        if rng.random() < 0.05:
            destination = rng.choice(["21300", "1234", "ABCDE", "00000"])
        trips.append((origin, destination, weight, *rng.sample(sides, 3)))
    seen = set()
    for trip in trips:
        answer = follow_instructions(trip, tmp_path)
        verdict = verify(trip, answer)
        assert verdict["valid"] is True, (trip, answer, verdict)
        seen.add(answer["status"])
    assert seen == set(STATUSES)


@pytest.mark.parametrize(
    "answer",
    [
        {},
        {"status": "priced"},
        {"status": "priced", "zone": 7, "tier": "3 lb", "postage": "19.70", "surcharges": []},
        {**RIGHT, "status": "PRICED"},
        {**RIGHT, "status": "ok"},
        {**RIGHT, "zone": "7"},
        {**RIGHT, "postage": 19.70},
        {**RIGHT, "total": None},
        {**RIGHT, "surcharges": ["length_over_22_in"]},
        {**RIGHT, "surcharges": [{"fee": "too_long", "amount": "4.50"}]},
        {**RIGHT, "surcharges": [{"fee": "length_over_22_in"}]},
        {**RIGHT, "weight": "3"},
        {"status": "free", **EMPTY},
    ],
)
def test_a_malformed_answer_never_reaches_the_verifier(answer: dict) -> None:
    # NanoAgent builds every answer into its contract class first, and refuses one that does not fit.
    with pytest.raises(ValueError):
        build_output(answer, PostageOutput)


ARGUMENTS = {
    "origin_zip": "77005",
    "destination_zip": "10001",
    "weight": "2.3",
    "length": "10",
    "width": "8",
    "height": "4",
    "service": SERVICE,
}


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {key: value for key, value in ARGUMENTS.items() if key != "height"},
        {**ARGUMENTS, "origin_zip": 77005},
        {**ARGUMENTS, "weight": 2.3},
        {**ARGUMENTS, "service": "priority_mail"},  # one service only
        {**ARGUMENTS, "girth": "24"},
    ],
)
def test_a_malformed_task_input_is_refused(arguments: dict) -> None:
    build_output(ARGUMENTS, ParcelInput)
    with pytest.raises(ValueError):
        build_output(arguments, ParcelInput)


def check(tool: str, value: dict, output: dict | None = None) -> bool:
    """Whether verify_input (without ``output``) or verify_output (with it) approves a tool call."""
    given, made = TOOLS[Tool(tool)]
    if output is None:
        return verifier.verify_input(tool, build_output(value, given))["valid"]
    return verifier.verify_output(tool, build_output(value, given), build_output(output, made), ".")["valid"]


def test_checks_tool_inputs() -> None:
    for pair in [("77005", "10001"), ("Houston", "10001"), ("", ""), ("00001", "10001")]:
        assert check("lookup_zone", {"origin_zip": pair[0], "destination_zip": pair[1]}) is True  # the tool says
    assert check("get_service_rules", {"service": SERVICE}) is True
    for zone in range(1, 10):
        assert check("get_rate_table", {"service": SERVICE, "zone": zone}) is True
    for zone in [0, 10, -1]:
        assert check("get_rate_table", {"service": SERVICE, "zone": zone}) is False
    assert check("calculate", {"expression": "1/0"}) is True  # the tool says it divides by zero


@pytest.mark.parametrize(
    ("origin", "destination"),
    [("77005", "10001"), ("77005", "09021"), ("77005", "96939"), ("10001-2301", " 77005 "), ("99501", "00601")],
)
def test_approves_every_true_lookup_zone_output(origin: str, destination: str, tmp_path: Path) -> None:
    given = {"origin_zip": origin, "destination_zip": destination}
    output = plain_output(lookup_zone(build_output(given, ZoneInput), tmp_path))
    assert check("lookup_zone", given, output) is True


def test_approves_every_true_rules_and_rate_table_output(tmp_path: Path) -> None:
    rules = plain_output(get_service_rules(RulesInput(service=Service.GROUND_ADVANTAGE), tmp_path))
    assert check("get_service_rules", {"service": SERVICE}, rules) is True
    for zone in range(1, 10):
        table = plain_output(get_rate_table(RateInput(service=Service.GROUND_ADVANTAGE, zone=zone), tmp_path))
        assert check("get_rate_table", {"service": SERVICE, "zone": zone}, table) is True


@pytest.mark.parametrize("expression", ["10 + 2 * (8 + 4)", "24 * 12 * 12 / 139", "0", "-1/3", "19.70 + 4.50"])
def test_approves_every_true_calculate_output(expression: str, tmp_path: Path) -> None:
    output = plain_output(calculate(CalculateInput(expression=expression), tmp_path))
    assert check("calculate", {"expression": expression}, output) is True


def changed(output: dict, **fields) -> dict:
    return {**output, **fields}


def test_refuses_a_tool_output_that_is_not_the_data(tmp_path: Path) -> None:
    zone = {"origin_zip": "77005", "destination_zip": "09021"}
    true_zone = plain_output(lookup_zone(build_output(zone, ZoneInput), tmp_path))
    assert check("lookup_zone", zone, changed(true_zone, zone=5)) is False  # the under-1-pound zone for every parcel
    assert check("lookup_zone", zone, changed(true_zone, zone_under_1_lb=7)) is False
    assert check("lookup_zone", zone, changed(true_zone, origin_zip="77006")) is False
    no_zone = {"origin_zip": "77005", "destination_zip": "21301"}
    assert check("lookup_zone", no_zone, changed(true_zone, **no_zone)) is False  # must fail
    rules = plain_output(get_service_rules(RulesInput(service=Service.GROUND_ADVANTAGE), tmp_path))
    assert check("get_service_rules", {"service": SERVICE}, changed(rules, dimensional_divisor="166")) is False
    assert check("get_service_rules", {"service": SERVICE}, changed(rules, max_weight="150")) is False
    table = plain_output(get_rate_table(RateInput(service=Service.GROUND_ADVANTAGE, zone=7), tmp_path))
    given = {"service": SERVICE, "zone": 7}
    assert check("get_rate_table", given, changed(table, zone=6)) is False
    assert check("get_rate_table", given, changed(table, oversized="1.00")) is False
    assert check("get_rate_table", given, changed(table, tiers=table["tiers"][1:])) is False
    cheaper = [*table["tiers"][:6], {**table["tiers"][6], "price": "1.00"}, *table["tiers"][7:]]
    assert check("get_rate_table", given, changed(table, tiers=cheaper)) is False
    assert check("get_rate_table", given, changed(table, surcharges=table["surcharges"][:2])) is False
    six = plain_output(get_rate_table(RateInput(service=Service.GROUND_ADVANTAGE, zone=6), tmp_path))
    assert check("get_rate_table", given, changed(six, zone=7)) is False  # zone 6's prices passed off as zone 7's
    assert check("calculate", {"expression": "1/3"}, {"expression": "1/3", "value": "0.33"}) is False
    assert check("calculate", {"expression": "1/0"}, {"expression": "1/0", "value": "0"}) is False  # must fail


def test_expected_matches_the_readme_example() -> None:
    assert expected(*BOX)[2:] == (7, "3 lb", "19.70", [], "19.70")
