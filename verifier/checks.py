"""Checks shared by the verifiers and the tools: how ZIP codes and a parcel's numbers are written, the zone between two
ZIP codes, how USPS Ground Advantage prices a parcel, and exact decimal arithmetic. Pure functions of their arguments
and data.py."""

import re
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal, InvalidOperation, localcontext

from contract import Fee, Status

from .data import EXCEPTIONS, FEES, OVERSIZED, PRICES, RULES, TIERS, ZONES

NUMBER = re.compile(r"^[0-9]+(\.[0-9]+)?$")
ZIP_CODE = re.compile(r"^([0-9]{5})(-[0-9]{4})?$")
ZONE_NUMBERS = range(1, 10)
MAX_WEIGHT = Decimal(RULES["max_weight"])
MAX_SIZE = Decimal(RULES["max_length_plus_girth"])
OVERSIZED_SIZE = Decimal(RULES["oversized_length_plus_girth"])
DIMENSIONAL_VOLUME = Decimal(RULES["dimensional_volume"])
DIVISOR = Decimal(RULES["dimensional_divisor"])
# The sizes the nonstandard fees are named by; tests/build_data.py checks Notice 123 says the same.
LONG, VERY_LONG, LARGE_VOLUME = Decimal(22), Decimal(30), Decimal(3456)
OVERSIZED_TIER = "oversized"


def exceptions(table):
    """origin prefix -> its 5-digit exceptions: (first ZIP code, last ZIP code, zone, whether only under 1 pound)."""
    parsed = {}
    for origin, items in table.items():
        parsed[origin] = []
        for item in items.split():
            span, zone, applies = item.split(":")
            first, last = span.split("-")
            parsed[origin].append((first, last, int(zone), applies == "under_1_lb"))
    return parsed


EXCEPTION = exceptions(EXCEPTIONS)


def result(valid, message, *, score=None, **details):
    return {
        "valid": valid,
        "score": float(valid) if score is None else score,
        "message": message,
        "details": details,
    }


def number(text):
    """``text`` as a Decimal if it is a number above zero written with digits and at most one point, else None."""
    plain = text.strip()
    if not NUMBER.fullmatch(plain) or Decimal(plain) == 0:
        return None
    return Decimal(plain)


def money(text):
    """``text`` as a Decimal if it is a number of zero or more written with digits and at most one point, else None."""
    plain = text.strip()
    return Decimal(plain) if NUMBER.fullmatch(plain) else None


def zip_code(text):
    """The five digits of ``text`` if it is a ZIP code or ZIP+4 (spaces around it dropped), else None."""
    found = ZIP_CODE.fullmatch(text.strip())
    return found.group(1) if found else None


def zones(origin, destination):
    """The zones from 5-digit ZIP code ``origin`` to ``destination``, (for 1 pound or more, for under 1 pound), or
    None when the charts give none: the origin's prefix has no chart, or its chart leaves out the destination's."""
    row = ZONES.get(origin[:3])
    if row is None or row[int(destination[:3])] == "-":
        return None
    heavy = light = int(row[int(destination[:3])])
    for first, last, zone, under_1_lb in EXCEPTION.get(origin[:3], []):
        if first <= destination <= last:
            light = zone
            if not under_1_lb:
                heavy = zone
    return heavy, light


def rate_table(zone):
    """Each tier in ``zone``, lightest first: (its name, the most it may weigh in pounds, its price)."""
    return [(name, most, price) for (name, most), price in zip(TIERS, PRICES[zone].split())]


def whole(value, rounding):
    return value.to_integral_value(rounding=rounding)


def measure(sides):
    """The length (the longest side) and the girth (twice the sum of the other two) of a box with ``sides``."""
    length, *others = sorted(sides, reverse=True)
    return length, 2 * sum(others)


def dimensional_weight(sides):
    """The dimensional weight in whole pounds, at most the maximum weight: each side rounded up to an inch and
    multiplied, then, if that is over the dimensional volume, divided by the divisor and rounded up; else 0."""
    volume = whole(sides[0], ROUND_CEILING) * whole(sides[1], ROUND_CEILING) * whole(sides[2], ROUND_CEILING)
    if volume <= DIMENSIONAL_VOLUME:
        return Decimal(0)
    return min(whole(volume / DIVISOR, ROUND_CEILING), MAX_WEIGHT)


def surcharges(sides):
    """Every nonstandard fee a box with ``sides`` (not oversized) pays, in Fee's order: (fee, amount)."""
    length, _ = measure(sides)
    fees = []
    if length > VERY_LONG:
        fees.append(Fee.LENGTH_OVER_30_IN)
    elif length > LONG:
        fees.append(Fee.LENGTH_OVER_22_IN)
    rounded = [whole(side, ROUND_HALF_UP) for side in sides]
    if rounded[0] * rounded[1] * rounded[2] > LARGE_VOLUME:
        fees.append(Fee.VOLUME_OVER_2_CU_FT)
    return [(fee, FEES[fee.value]) for fee in fees]


def expected(origin_zip, destination_zip, weight, length, width, height):
    """The status the parcel has, why, and its zone, tier, postage, surcharges and total (0, "", "", [], "" unless
    priced).

    The checks go in this order, the first that holds deciding: the weight and sides, the ZIP codes' form, whether the
    charts give a zone, the weight's limit, then the size's.
    """
    nothing = (0, "", "", [], "")
    pounds = number(weight)
    sides = [number(side) for side in (length, width, height)]
    if pounds is None or None in sides:
        given = [weight, length, width, height]
        return Status.INVALID_PARCEL, f"the weight and sides {given} must each be a number above zero", *nothing
    origin, destination = zip_code(origin_zip), zip_code(destination_zip)
    for role, text, code in (("origin", origin_zip, origin), ("destination", destination_zip, destination)):
        if code is None:
            return Status.INVALID_ZIP, f"the {role} {text!r} is not a 5-digit ZIP code or ZIP+4", *nothing
    pair = zones(origin, destination)
    if pair is None:
        return Status.NO_ZONE, f"the zone charts give no zone from {origin} to {destination}", *nothing
    if pounds > MAX_WEIGHT:
        return Status.TOO_HEAVY, f"{pounds} lb is over the {MAX_WEIGHT} lb limit", *nothing
    long_side, girth = measure(sides)
    if long_side + girth > MAX_SIZE:
        size = f"length {long_side} plus girth {girth} is {long_side + girth} in"
        return Status.TOO_LARGE, f"{size}, over the {MAX_SIZE} in limit", *nothing
    zone = pair[1] if pounds < 1 else pair[0]
    parcel = f"a {pounds} lb parcel {' x '.join(map(str, sides))} in from {origin} to {destination}, zone {zone},"
    if long_side + girth > OVERSIZED_SIZE:
        tier, postage, fees = OVERSIZED_TIER, OVERSIZED[zone], []
        reason = f"is oversized (length plus girth {long_side + girth} in)"
    else:
        billed = max(pounds, dimensional_weight(sides))
        tier, _, postage = next(row for row in rate_table(zone) if Decimal(row[1]) >= billed)
        fees = surcharges(sides)
        reason = f"is billed at {billed} lb, tier {tier}"
    total = Decimal(postage) + sum(Decimal(amount) for _, amount in fees)
    named = " + ".join(f"{fee.value} {amount}" for fee, amount in fees) or "no surcharge"
    fact = f"{parcel} {reason}: {postage} + {named} = {total}"
    return Status.PRICED, fact, zone, tier, postage, fees, f"{total}"


def folded(text):
    """``text`` as tier names are compared: case folded, runs of spaces made one."""
    return " ".join(text.casefold().split())


TOKEN = re.compile(r"\s*(?:([0-9]+(?:\.[0-9]*)?|\.[0-9]+)|(.))")


def tokens(expression):
    found = []
    for value, other in TOKEN.findall(expression):
        if value:
            found.append(Decimal(value))
        elif other.strip():
            if other not in "+-*/()":
                raise ValueError(f"{other!r} is not a number, + - * /, or a parenthesis")
            found.append(other)
    return found


def evaluate(expression):
    """The exact value of ``expression`` (+ - * / and parentheses on decimal numbers) to 28 significant digits, in
    plain decimal notation; raises ValueError when it is not one or divides by zero."""
    items = tokens(expression)
    position = 0

    def peek():
        return items[position] if position < len(items) else None

    def take():
        nonlocal position
        position += 1
        return items[position - 1]

    def atom():
        item = peek()
        if item == "-":
            take()
            return -atom()
        if item == "+":
            take()
            return atom()
        if item == "(":
            take()
            value = total()
            if peek() != ")":
                raise ValueError("a parenthesis is not closed")
            take()
            return value
        if isinstance(item, Decimal):
            return take()
        raise ValueError("the expression is incomplete")

    def product():
        value = atom()
        while peek() in ("*", "/"):
            if take() == "*":
                value = value * atom()
            else:
                divisor = atom()
                if divisor == 0:
                    raise ValueError("division by zero")
                value = value / divisor
        return value

    def total():
        value = product()
        while peek() in ("+", "-"):
            value = value + product() if take() == "+" else value - product()
        return value

    with localcontext() as context:
        context.prec = 28
        try:
            value = total()
        except InvalidOperation as error:
            raise ValueError("the expression is not arithmetic on decimal numbers") from error
        if position != len(items):
            raise ValueError("the expression has something left over after its end")
        return format(value.normalize(), "f") if value else "0"
