from collections import defaultdict
from decimal import Decimal

from ortools.sat.python import cp_model
from sqlalchemy import select

from backend.app.models import Allocation, Line, Match, Run
from backend.app.normalization import identifier, number, unit


def solve_allocations(demands, capacities, edges):
    """Deterministic integer min-cost capacity assignment; quantities use exact micro-units."""
    model = cp_model.CpModel()
    variables = {}
    for inv_id, po_id, cost in edges:
        variables[(inv_id, po_id)] = model.new_int_var(
            0, min(demands[inv_id], capacities[po_id]), inv_id + po_id
        )
    unallocated = {}
    for inv_id, qty in demands.items():
        unallocated[inv_id] = model.new_int_var(0, qty, "unallocated_" + inv_id)
        model.add(
            sum(v for (i, p), v in variables.items() if i == inv_id) + unallocated[inv_id] == qty
        )
    for po_id, qty in capacities.items():
        model.add(sum(v for (i, p), v in variables.items() if p == po_id) <= qty)
    costs = {(i, p): c for i, p, c in edges}
    model.minimize(
        sum(unallocated.values()) * 100000 + sum(v * costs[key] for key, v in variables.items())
    )
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5
    solver.parameters.num_search_workers = 1
    status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {"status": "UNRESOLVED", "pieces": [], "unallocated": demands}
    return {
        "status": "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE",
        "pieces": [
            {"invoice_line_id": i, "po_line_id": p, "micro_quantity": solver.value(v)}
            for (i, p), v in variables.items()
            if solver.value(v)
        ],
        "unallocated": {i: solver.value(v) for i, v in unallocated.items() if solver.value(v)},
    }


def allocation_stage(run_id, emit):
    from backend.app.db import Session

    with Session() as db:
        run = db.get(Run, run_id)
        po = list(
            db.scalars(
                select(Line).where(
                    Line.document_id == run.po_id, Line.organization_id == run.organization_id
                )
            )
        )
        matches = list(db.scalars(select(Match).where(Match.run_id == run.id)))
        invoiced = {m.invoice_line_id: db.get(Line, m.invoice_line_id) for m in matches}
        prior = defaultdict(lambda: Decimal(0))
        if not run.policy.get("evaluation_id"):
            for a in db.scalars(
                select(Allocation).where(
                    Allocation.organization_id == run.organization_id, Allocation.run_id != run.id
                )
            ):
                other = db.get(Run, a.run_id)
                if not other.policy.get("evaluation_id"):
                    prior[a.po_line_id] += number(a.quantity)
        scale = 1000000
        demands = {
            id: int(max(Decimal(0), number(line.quantity)) * scale) for id, line in invoiced.items()
        }
        capacities = {
            p.id: int(max(Decimal(0), number(p.quantity) - prior[p.id]) * scale) for p in po
        }
        edges = []
        for match in matches:
            inv = invoiced[match.invoice_line_id]
            for p in po:
                same = match.po_line_id == p.id and match.identity_status == "SAME_PRODUCT"
                exact = bool(inv.sku) and identifier(inv.sku) == identifier(p.sku)
                if (same or exact) and unit(inv.unit) == unit(p.unit):
                    edges.append((inv.id, p.id, 0 if same else 10))
        result = solve_allocations(demands, capacities, edges)
        result["quantities"] = [
            {**p, "quantity": str(Decimal(p["micro_quantity"]) / scale)} for p in result["pieces"]
        ]
        # Multiple PO pieces and ambiguous identities are proposals, never silent approval.
        complex_ids = {
            i for i in demands if sum(p["invoice_line_id"] == i for p in result["pieces"]) > 1
        }
        result["requires_review"] = not bool(run.policy.get("allocation_overrides")) and bool(
            complex_ids
            or any(
                m.po_line_id is None
                and any(p["invoice_line_id"] == m.invoice_line_id for p in result["pieces"])
                for m in matches
            )
        )
        result["authority"] = (
            "CAPACITY_PROPOSAL; final financial policy and reviewer mapping remain authoritative"
        )
        run.policy = {**run.policy, "allocation_plan": result}
        db.commit()
        emit(
            "ALLOCATION_SOLVED",
            "Global capacity and split allocation plan computed",
            {"output": result},
        )
