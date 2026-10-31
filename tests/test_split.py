from decimal import Decimal

from app.split import UNCLAIMED, allocate, shares, to_usdc, unit_costs


def test_allocate_sums_and_even_zero_weights():
    assert allocate(100, [1, 1, 1]) == [34, 33, 33]
    assert allocate(10, [0, 0]) == [5, 5]
    assert sum(allocate(10001, [3, 7, 11])) == 10001
    assert allocate(0, [5, 5]) == [0, 0]


def test_unit_costs_remainder_to_first_units():
    assert unit_costs(1000, 3) == [334, 333, 333]


def test_three_people_vat_and_service_sum_to_total():
    items = [(1, 2, 9000), (2, 1, 4500), (3, 3, 2550), (4, 1, 1999)]  # mains, steak, drinks, chips
    subtotal = 9000 + 4500 + 2550 + 1999
    vat, service = round(subtotal * 0.16), round(subtotal * 0.10)
    total = subtotal + vat + service
    claims = [("a", 1, 0), ("b", 1, 1), ("c", 2, 0), ("a", 3, 0), ("a", 3, 1), ("b", 3, 2), ("c", 4, 0)]
    s = shares(items, claims, vat + service)
    assert UNCLAIMED not in s
    assert sum(s.values()) == total
    assert s["a"] > s["b"]  # a had a main and two drinks, b a main and one drink


def test_shared_unit_claimed_by_three():
    s = shares([(1, 1, 1000)], [("a", 1, 0), ("b", 1, 0), ("c", 1, 0)], 0)
    assert sorted(s.values()) == [333, 333, 334] and sum(s.values()) == 1000


def test_leftover_units_go_to_unclaimed_bucket():
    s = shares([(1, 3, 3000)], [("a", 1, 0)], 300)
    assert s == {"a": 1100, UNCLAIMED: 2200}


def test_rounding_total_k100_01():
    items = [(1, 3, 9001)]
    s = shares(items, [("a", 1, 0), ("b", 1, 1), ("c", 1, 2)], 1000)
    assert sum(s.values()) == 10001
    assert max(s.values()) - min(s.values()) <= 2


def test_to_usdc():
    assert to_usdc(2650, Decimal("26.5"), Decimal(1)) == Decimal("1.00")
    assert to_usdc(45000, Decimal("26.5"), Decimal("0.01")) == Decimal("0.17")
    assert to_usdc(1, Decimal("26.5"), Decimal(1)) == Decimal("0.01")  # floor at one cent
