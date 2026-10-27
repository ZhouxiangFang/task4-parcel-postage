"""The tools that read the USPS prices and zone charts, from verifier/data.py: the one copy, which the verifier also
judges by. ZIP codes, zones and arithmetic follow verifier/checks.py's rules, so a tool and a verdict never disagree on
them. No tool prices a parcel: the agent works the price out from what they give."""

from __future__ import annotations

from pathlib import Path

from contract import (
    CalculateInput,
    CalculateOutput,
    Charge,
    Fee,
    RateInput,
    RateOutput,
    RulesInput,
    RulesOutput,
    Tier,
    ZoneInput,
    ZoneOutput,
)
from verifier.checks import ZONE_NUMBERS, evaluate, rate_table, zip_code, zones
from verifier.data import FEES, OVERSIZED, PRICES_EFFECTIVE, RULES, ZONES_EFFECTIVE


def lookup_zone(given: ZoneInput, workspace: Path) -> ZoneOutput:
    origin, destination = zip_code(given.origin_zip), zip_code(given.destination_zip)
    for role, text, code in (("origin", given.origin_zip, origin), ("destination", given.destination_zip, destination)):
        if code is None:
            raise ValueError(f"invalid ZIP: the {role} {text!r} is not a 5-digit ZIP code or ZIP+4, such as 77005")
    pair = zones(origin, destination)
    if pair is None:
        raise ValueError(
            f"no zone: the USPS zone charts give no zone from {origin} to {destination}; "
            "the origin may have no chart (an unused prefix or a military post office) or the destination none in it"
        )
    return ZoneOutput(
        origin_zip=given.origin_zip, destination_zip=given.destination_zip, zone=pair[0], zone_under_1_lb=pair[1]
    )


def get_service_rules(given: RulesInput, workspace: Path) -> RulesOutput:
    return RulesOutput(
        service=given.service,
        prices_effective=PRICES_EFFECTIVE,
        zones_effective=ZONES_EFFECTIVE,
        **RULES,
    )


def get_rate_table(given: RateInput, workspace: Path) -> RateOutput:
    if given.zone not in ZONE_NUMBERS:
        raise ValueError(f"no such zone: {given.zone}; zones run from 1 to 9, and lookup_zone gives them")
    return RateOutput(
        service=given.service,
        zone=given.zone,
        tiers=[Tier(tier=name, max_weight=most, price=price) for name, most, price in rate_table(given.zone)],
        oversized=OVERSIZED[given.zone],
        surcharges=[Charge(fee=Fee(fee), amount=amount) for fee, amount in FEES.items()],
    )


def calculate(given: CalculateInput, workspace: Path) -> CalculateOutput:
    return CalculateOutput(expression=given.expression, value=evaluate(given.expression))
