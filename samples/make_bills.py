"""Sample restaurant bills to open on a laptop screen and photograph with a phone.

uv run python -m samples.make_bills ->  samples/bill-*.pdf   (merchants are made up)
"""

from pathlib import Path

from app.pdf import bill_pdf

HERE = Path(__file__).parent

BILLS = {
    # merchant, items (qty, name, line total ngwee), vat %, service %, vat included in prices?
    "bill-grill-vat-service": ("Mwezi Grill House", [(2, "Nshima & chicken", 15000), (1, "T-bone steak", 15000),
                               (2, "Chips", 7000), (3, "Mosi 375ml", 7500), (1, "Coke 500ml", 1500)], 16, 10, False),
    "bill-cafe-vat-incl": ("Kaizen Cafe", [(2, "Tea", 2000), (4, "Samoosa", 3200), (2, "Rolls", 1000),
                           (1, "Maheu", 1200), (1, "Bottled water", 1000)], 16, 0, True),
    "bill-diner-shared": ("Zambezi Sunset Diner", [(1, "Village chicken", 12000), (1, "Kapenta & nshima", 6000),
                          (3, "Castle Lite", 9000), (1, "Large chips (share)", 5500), (2, "Fanta", 3000)], 16, 10, False),
}

for fname, (merchant, items, vat, service, incl) in BILLS.items():
    sub = sum(i[2] for i in items)
    svc = round(sub * service / 100)
    if incl:
        tax = round(sub - sub / (1 + vat / 100))
        totals = [("Subtotal", sub), (f"VAT {vat}% (incl.)", tax), ("TOTAL", sub + svc)]
    else:
        tax = round(sub * vat / 100)
        totals = [("Subtotal", sub), (f"VAT {vat}%", tax)] + ([(f"Service {service}%", svc)] if svc else []) + \
                 [("TOTAL", sub + tax + svc)]
    data = bill_pdf(merchant, ["Plot 12, Cairo Road, Lusaka", "TPIN 1000000000", "Table 7  -  Server: Mary",
                               "31 Oct 2026 13:05"], items, totals, ["Thank you, come again!"])
    (HERE / f"{fname}.pdf").write_bytes(data)
    print(f"{fname}.pdf  total K{totals[-1][1] / 100:,.2f}")
