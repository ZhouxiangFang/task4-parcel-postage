"""The price-parcel task's check: the status the data gives, and for a priced parcel the right zone, tier, postage,
surcharges and total, each to the cent."""

from collections import Counter

from contract import Status

from .checks import expected, folded, money, result


def verify_task(arguments, output, reference, workspace):
    """``output``: a contract PostageOutput, judged against the data itself (the task has no reference tool)."""
    status, fact, zone, tier, postage, fees, total = expected(
        arguments.origin_zip,
        arguments.destination_zip,
        arguments.weight,
        arguments.length,
        arguments.width,
        arguments.height,
    )
    if output.status is not status:
        return result(False, f"{fact}, so the status is {status.value}, but the answer says {output.status.value}")
    if status is not Status.PRICED:
        if output.zone or output.tier or output.postage or output.surcharges or output.total:
            return result(False, f"zone must be 0 and every other field empty unless status is priced; {fact}")
        return result(True, f"{fact}, as the answer says")
    # Each fee once with its amount, in any order; an amount not written as a number matches none.
    given_fees = Counter((charge.fee, money(charge.amount)) for charge in output.surcharges)
    checks = {
        "zone": output.zone == zone,
        "tier": folded(output.tier) == folded(tier),
        "postage": money(output.postage) == money(postage),
        "surcharges": given_fees == Counter((fee, money(amount)) for fee, amount in fees),
        "total": money(output.total) == money(total),
    }
    wrong = [name for name, right in checks.items() if not right]
    if wrong:
        expected_fields = {
            "zone": zone,
            "tier": tier,
            "postage": postage,
            "surcharges": [{"fee": fee.value, "amount": amount} for fee, amount in fees],
            "total": total,
        }
        return result(
            False,
            f"{', '.join(wrong)} wrong: {fact}",
            score=1 - len(wrong) / len(checks),
            expected=expected_fields,
        )
    return result(True, f"{fact}, as the answer says")
