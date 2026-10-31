"""Pure money math. All amounts are integer minor units (ngwee). No DB, no LLM."""

import os
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

UNCLAIMED = None  # shares() key for units nobody has claimed yet


def allocate(total: int, weights: list[int]) -> list[int]:
    """Split total by weights with largest-remainder rounding. Always sums to total."""
    if not weights:
        return []
    if not any(weights):
        weights = [1] * len(weights)
    w_sum = sum(weights)
    floors = [total * w // w_sum for w in weights]
    left = total - sum(floors)
    # biggest remainder first, ties to the earliest index
    order = sorted(range(len(weights)), key=lambda i: (-(total * weights[i] % w_sum), i))
    for i in order[:left]:
        floors[i] += 1
    return floors


def unit_costs(line_total: int, qty: int) -> list[int]:
    return allocate(line_total, [1] * qty)


def shares(items, claims, extras_minor: int) -> dict:
    """items: [(item_id, qty, line_total)], claims: [(participant_id, item_id, unit_index)].

    Returns {participant_id: minor}, with unclaimed units under UNCLAIMED. Extras (tax, service, tip,
    receipt rounding) follow each bucket's item subtotal. The values always sum to lines + extras.
    """
    claimers = defaultdict(list)
    for pid, item_id, unit in sorted(claims, key=lambda c: str(c[0])):
        claimers[(item_id, unit)].append(pid)
    sub = defaultdict(int)
    for item_id, qty, line_total in items:
        for unit, cost in enumerate(unit_costs(line_total, qty)):
            who = claimers.get((item_id, unit)) or [UNCLAIMED]
            for pid, part in zip(who, allocate(cost, [1] * len(who))):
                sub[pid] += part
    for pid, *_ in claims:
        sub[pid] += 0  # people who claimed only zero-cost units still show up
    keys = list(sub)
    for pid, extra in zip(keys, allocate(extras_minor, [sub[k] for k in keys])):
        sub[pid] += extra
    return dict(sub)


def to_usdc(minor: int, fx: Decimal | None = None, scale: Decimal | None = None) -> Decimal:
    fx = fx or Decimal(os.getenv("FX_ZMW_PER_USD", "26.5"))
    scale = scale if scale is not None else Decimal(os.getenv("CHARGE_SCALE", "1"))
    usd = (Decimal(minor) / 100 / fx * scale).quantize(Decimal("0.01"), ROUND_HALF_UP)
    return max(usd, Decimal("0.01"))


def kwacha(minor: int) -> str:
    return f"K{minor / 100:,.2f}"


def to_minor(kwacha_amount) -> int:
    return int((Decimal(str(kwacha_amount)) * 100).quantize(Decimal(1), ROUND_HALF_UP))
