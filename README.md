# Parcel Postage

Price a parcel for USPS Ground Advantage at retail prices. Enter an origin and a destination ZIP code, the parcel's
weight in pounds, and the three sides of its box in inches. The agent looks up the zone, the service's limits, and the
zone's price table, then works out the postage, any nonstandard fees, and the total. A deterministic verifier checks
every part of the answer against the same fixed copy of the USPS price list and zone charts.

Prices are the ones that took effect on **October 4, 2026**, and zones those of **October 1, 2026**. The plugin runs
offline and needs no API key.

## Example

Ask: **How much is it to mail a 2.3 lb box, 10 x 8 x 4 inches, from 77005 to 10001?**

Input:

```json
{"origin_zip": "77005", "destination_zip": "10001", "weight": "2.3", "length": "10", "width": "8", "height": "4", "service": "ground_advantage"}
```

Output:

```json
{"status": "priced", "zone": 7, "tier": "3 lb", "postage": "19.70", "surcharges": [], "total": "19.70"}
```

Houston to New York is zone 7. The box is under one cubic foot, so it is billed at its own weight, and 2.3 lb rounds up
to the 3 lb tier.

## Tools

| Tool | Purpose |
|---|---|
| `lookup_zone` | Give the zone between two ZIP codes, and the zone for a parcel under 1 pound where that differs. |
| `get_service_rules` | Give the weight and size limits and the dimensional weight rules. |
| `get_rate_table` | Give one zone's price for every weight tier, the oversized price, and the nonstandard fees. |
| `calculate` | Evaluate decimal arithmetic with 28-digit precision. |

The `price-parcel` task uses all four tools. No tool gives a final price: the agent decides from the rules and the
tables which tier and fees apply.

## Pricing rules

1. The length is the longest side; the girth is twice the sum of the other two sides.
2. A parcel over 108 inches in length plus girth pays the zone's oversized price and no other fee.
3. Otherwise, round each side up to a whole inch. If the box is over 1,728 cubic inches, its dimensional weight is the
   volume divided by 139, rounded up, and at most 70 pounds. The parcel is billed at the larger of its weight and its
   dimensional weight, at the first tier that holds it: 4, 8, 12 or 15.999 oz, then each whole pound to 70 lb.
4. Nonstandard fees: longest side over 22 up to 30 inches, $4.50; over 30 inches, $10.00; over 3,456 cubic inches with
   each side rounded to the nearest inch, $21.00.
5. A parcel under 1 pound uses the zone for parcels under 1 pound, which differs only for some military ZIP codes.

Checks run in this order, the first that holds deciding:

| Status | Meaning |
|---|---|
| `invalid_parcel` | The weight or a side is not a decimal above zero. |
| `invalid_zip` | A ZIP code is not 5 digits or ZIP+4. |
| `no_zone` | The zone charts give no zone between the ZIP codes. |
| `too_heavy` | The parcel weighs over 70 pounds. |
| `too_large` | Its length plus girth is over 130 inches. |
| `priced` | The parcel is priced. |

Unless the status is `priced`, the zone is 0, the surcharges are empty, and every other field is an empty string.

## Verification

The verifier works out the status, zone, tier, postage, surcharges and total itself from the data. A priced answer
with wrong fields gets partial credit across five checks: zone, tier, postage, surcharges, and total. Money must match
to the cent, and surcharges may come in any order. A wrong status is refused. Typed contracts refuse malformed
answers, and every tool output is checked against the data.

Tests cover each status and the order they are checked in, tier edges, the dimensional weight threshold and cap,
both roundings of a side, oversized and maximum sizes, military ZIP codes, and the agent's procedure played through
the tools.

## Layout

`contract.py` defines typed inputs and outputs; `nanoagent.yaml` defines tools and task instructions. Tool
implementations live in `src/plugin/`, verification in `verifier/`, and tests and the USPS snapshot in `tests/`.

## Develop and run

Requires Git, uv, and Python 3.12 or later.

```bash
git clone https://github.com/ZhouxiangFang/task4-parcel-postage.git
cd task4-parcel-postage
uv sync --extra dev
uv run pytest
uv run ruff check .
```

Check plugin packaging:

```bash
uvx --from "git+https://github.com/RUSH-LAB/nanoagent#subdirectory=nanoagent" nanoagent plugin inspect .
```

Rebuild the generated data:

```bash
uv run python tests/build_data.py
```

## Data and limitations

Source: United States Postal Service. `tests/usps/` holds Notice 123 (the price list), section 133 of the Domestic
Mail Manual (dimensional weight), and the domestic zone chart of every origin ZIP prefix from USPS's zone chart tool,
all downloaded on October 26, 2026 and pinned by SHA-256 in `tests/build_data.py`. A test checks that
`verifier/data.py` matches a fresh rebuild.

This version prices one service, USPS Ground Advantage at retail prices, for rectangular boxes. It leaves out
commercial prices, other services, Flat Rate packaging, Limited Overland Routes in Alaska, cylinders and other
nonrectangular parcels, and fees for contents (liquids, live animals, hazardous materials) or extra services.
ZIP codes are checked only by their 3-digit prefix: a prefix in the charts is priced even when the 5-digit code is not
in use. Military post offices (APO/FPO/DPO) have no chart as an origin, and USPS's chart tool refuses the chart of the
prefix 967 (Hawaii outside Honolulu), so parcels mailed from those get `no_zone`; parcels mailed to them are priced.
City names are not accepted. Prices and zones after their next USPS change are not covered.
