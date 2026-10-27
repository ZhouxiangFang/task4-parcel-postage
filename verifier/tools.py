"""The tool calls' checks: every zone asked about is one, and each output is exactly what the data says."""

from contract import Tool

from .checks import ZONE_NUMBERS, evaluate, rate_table, result, zip_code, zones
from .data import FEES, OVERSIZED, PRICES_EFFECTIVE, RULES, ZONES_EFFECTIVE


def verify_input(tool, value):
    # Any ZIP code or expression may be asked about: the tool itself says when it means nothing.
    if tool is Tool.GET_RATE_TABLE and value.zone not in ZONE_NUMBERS:
        return result(False, f"zone {value.zone} is not a zone: zones run from 1 to 9", given=value.zone)
    return result(True, "input is valid")


def verify_output(tool, input_value, output_value, workspace):
    if tool is Tool.LOOKUP_ZONE:
        return verify_zone(input_value, output_value)
    if tool is Tool.GET_SERVICE_RULES:
        expected = (input_value.service, PRICES_EFFECTIVE, ZONES_EFFECTIVE, *RULES.values())
        given = (
            output_value.service,
            output_value.prices_effective,
            output_value.zones_effective,
            output_value.max_weight,
            output_value.max_length_plus_girth,
            output_value.oversized_length_plus_girth,
            output_value.dimensional_volume,
            output_value.dimensional_divisor,
        )
        if given != expected:
            return result(
                False, "get_service_rules must give exactly what the data says", expected=expected, given=given
            )
        return result(True, "output is valid")
    if tool is Tool.GET_RATE_TABLE:
        return verify_rates(input_value, output_value)
    try:
        value = evaluate(input_value.expression)
    except ValueError:
        return result(False, f"{input_value.expression!r} cannot be worked out, so the tool must fail, not answer")
    if output_value.expression != input_value.expression or output_value.value != value:
        return result(False, f"{input_value.expression} is {value}", given=output_value.value)
    return result(True, "output is valid")


def verify_zone(input_value, output_value):
    origin, destination = zip_code(input_value.origin_zip), zip_code(input_value.destination_zip)
    pair = zones(origin, destination) if origin and destination else None
    if pair is None:
        return result(False, "the charts give no zone between these ZIP codes, so the tool must fail, not answer")
    echoed = (output_value.origin_zip, output_value.destination_zip) == (
        input_value.origin_zip,
        input_value.destination_zip,
    )
    given = (output_value.zone, output_value.zone_under_1_lb)
    if not echoed or given != pair:
        return result(False, f"the zones are {pair}", expected=pair, given=given)
    return result(True, "output is valid")


def verify_rates(input_value, output_value):
    zone = input_value.zone
    expected = (
        rate_table(zone),
        OVERSIZED[zone],
        list(FEES.items()),
    )
    given = (
        [(row.tier, row.max_weight, row.price) for row in output_value.tiers],
        output_value.oversized,
        [(charge.fee.value, charge.amount) for charge in output_value.surcharges],
    )
    if (output_value.service, output_value.zone) != (input_value.service, zone) or given != expected:
        return result(False, f"get_rate_table must give exactly zone {zone}'s prices", expected=expected, given=given)
    return result(True, "output is valid")
