import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uuid

from synthetic_data.__main__ import render

folder = Path("storage/browser-fixtures")
folder.mkdir(parents=True, exist_ok=True)
code = uuid.uuid4().hex[:8].upper()
po = [
    {
        "sku": f"{code[:6]}A",
        "description": "Northstar model T1 laptop i7 16GB RAM 512GB SSD 3 years warranty",
        "qty": 2,
        "price": 150,
    },
    {
        "sku": f"{code[:6]}B",
        "description": "Northstar model T2 laptop i7 16GB RAM 512GB SSD 3 years warranty",
        "qty": 2,
        "price": 180,
    },
]
inv = [dict(x) for x in po]
inv[0]["description"] = inv[0]["description"].replace("16GB RAM", "8GB RAM")
render(
    folder / "purchase_order.pdf",
    "po",
    po,
    "browser-" + code,
    "clean_po",
    po_number="QA-PO-" + code,
)
render(
    folder / "invoice.pdf",
    "invoice",
    inv,
    "browser-" + code,
    "clean_invoice",
    po_number="QA-PO-" + code,
)
print("Wrote unique browser fixtures")
