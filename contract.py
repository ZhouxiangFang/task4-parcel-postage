"""Each tool's and task's typed input and output (see nanoagent.plugin.v0001.contract): declarations only."""

from dataclasses import dataclass
from enum import Enum
from typing import Annotated

from slimconfig import Output


class Tool(Enum):
    LOOKUP_ZONE = "lookup_zone"
    GET_SERVICE_RULES = "get_service_rules"
    GET_RATE_TABLE = "get_rate_table"
    CALCULATE = "calculate"


class Task(Enum):
    PRICE_PARCEL = "price-parcel"


class Service(Enum):
    GROUND_ADVANTAGE = "ground_advantage"


class Fee(Enum):
    LENGTH_OVER_22_IN = "length_over_22_in"
    LENGTH_OVER_30_IN = "length_over_30_in"
    VOLUME_OVER_2_CU_FT = "volume_over_2_cu_ft"


class Status(Enum):
    PRICED = "priced"
    INVALID_PARCEL = "invalid_parcel"
    INVALID_ZIP = "invalid_zip"
    NO_ZONE = "no_zone"
    TOO_HEAVY = "too_heavy"
    TOO_LARGE = "too_large"


SERVICE = "The USPS service: ground_advantage, USPS Ground Advantage at retail prices"
ZIP = "A 5-digit ZIP code, or ZIP+4, such as 77005 or 10001-2301"
ZONE = "A USPS zone, 1 to 9"
MONEY = "US dollars with cents, such as 19.70"
FEE = (
    "length_over_22_in: longest side more than 22 up to 30 inches; length_over_30_in: longest side more than 30 "
    "inches; volume_over_2_cu_ft: more than 3456 cubic inches with each side rounded to the nearest inch"
)
STATUS = (
    "priced: success; invalid_parcel: the weight or a side is not a positive plain decimal; "
    "invalid_zip: a ZIP code is not 5 digits or ZIP+4; no_zone: the zone charts give no zone between the ZIP codes; "
    "too_heavy: more than the maximum weight; too_large: length plus girth more than the maximum"
)


@dataclass
class ParcelInput(Output):
    origin_zip: Annotated[str, "The ZIP code mailed from: 5 digits or ZIP+4, such as 77005"]
    destination_zip: Annotated[str, "The ZIP code mailed to: 5 digits or ZIP+4, such as 10001-2301"]
    weight: Annotated[str, "The parcel's weight in pounds, a decimal number such as 2.3 (16 ounces is 1 pound)"]
    length: Annotated[str, "One side of the box in inches, a decimal number such as 10"]
    width: Annotated[str, "Another side of the box in inches, a decimal number such as 8"]
    height: Annotated[str, "The third side of the box in inches, a decimal number such as 4"]
    service: Annotated[Service, SERVICE]


@dataclass
class Charge(Output):
    fee: Annotated[Fee, FEE]
    amount: Annotated[str, "The fee in dollars with cents, such as 4.50"]


@dataclass
class PostageOutput(Output):
    status: Annotated[Status, STATUS]
    zone: Annotated[int, "The zone the parcel is priced at, 1 to 9; 0 unless status is priced"]
    tier: Annotated[
        str, "The rate table tier the parcel is priced at, such as 8 oz, 3 lb, or oversized; empty unless priced"
    ]
    postage: Annotated[str, "The tier's price in the zone, in dollars with cents such as 19.70; empty unless priced"]
    surcharges: Annotated[list[Charge], "Every nonstandard fee that applies, each once; empty unless priced"]
    total: Annotated[str, "The postage plus every surcharge, in dollars with cents such as 19.70; empty unless priced"]


@dataclass
class ZoneInput(Output):
    origin_zip: Annotated[str, ZIP]
    destination_zip: Annotated[str, ZIP]


@dataclass
class ZoneOutput(Output):
    origin_zip: Annotated[str, "The origin ZIP code, unchanged"]
    destination_zip: Annotated[str, "The destination ZIP code, unchanged"]
    zone: Annotated[int, "The zone for a parcel weighing 1 pound or more, 1 to 9"]
    zone_under_1_lb: Annotated[
        int, "The zone for a parcel weighing under 1 pound, 1 to 9; differs from zone only for some military ZIP codes"
    ]


@dataclass
class RulesInput(Output):
    service: Annotated[Service, SERVICE]


@dataclass
class RulesOutput(Output):
    service: Annotated[Service, "The service asked about"]
    prices_effective: Annotated[str, "The day the prices took effect, YYYY-MM-DD"]
    zones_effective: Annotated[str, "The day the zone charts took effect, YYYY-MM-DD"]
    max_weight: Annotated[
        str, "The most a parcel may weigh, in pounds; also the most a dimensional weight is billed at"
    ]
    max_length_plus_girth: Annotated[str, "The most a parcel's length plus girth may measure, in inches"]
    oversized_length_plus_girth: Annotated[
        str, "Over this length plus girth, in inches, a parcel pays the oversized price and no surcharge"
    ]
    dimensional_volume: Annotated[
        str, "Over this volume, in cubic inches with each side rounded up, a parcel has a dimensional weight"
    ]
    dimensional_divisor: Annotated[str, "The volume divided by this, rounded up, is the dimensional weight in pounds"]


@dataclass
class RateInput(Output):
    service: Annotated[Service, SERVICE]
    zone: Annotated[int, ZONE]


@dataclass
class Tier(Output):
    tier: Annotated[str, "The tier's name, such as 4 oz, 15.999 oz, or 3 lb"]
    max_weight: Annotated[str, "The most a parcel priced at this tier may weigh, in pounds, such as 0.25 or 3"]
    price: Annotated[str, MONEY]


@dataclass
class RateOutput(Output):
    service: Annotated[Service, "The service asked about"]
    zone: Annotated[int, "The zone asked about"]
    tiers: Annotated[list[Tier], "Every weight tier, lightest first"]
    oversized: Annotated[str, "The oversized price in dollars with cents, such as 271.20"]
    surcharges: Annotated[list[Charge], "Every nonstandard fee and its amount"]


@dataclass
class CalculateInput(Output):
    expression: Annotated[str, "Arithmetic on decimal numbers with + - * / and parentheses, such as 10 + 2 * (8 + 4)"]


@dataclass
class CalculateOutput(Output):
    expression: Annotated[str, "The expression, unchanged"]
    value: Annotated[str, "The result in plain decimal notation, calculated with 28-digit precision"]


TOOLS = {
    Tool.LOOKUP_ZONE: (ZoneInput, ZoneOutput),
    Tool.GET_SERVICE_RULES: (RulesInput, RulesOutput),
    Tool.GET_RATE_TABLE: (RateInput, RateOutput),
    Tool.CALCULATE: (CalculateInput, CalculateOutput),
}
TASKS = {Task.PRICE_PARCEL: (ParcelInput, PostageOutput)}
