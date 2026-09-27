"""Scout demand for a portfolio of datasets and write one summary table.

  python -m scripts.scout --supply US --out ../out_scout "glaucoma" "asthma" ...

Each argument is a disease. Writes per-disease leads.json (and contacts when
--contacts N is given) plus summary.json / summary.md across the portfolio.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from bconz import dia, pcia
from bconz.query import SearchQuery


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("diseases", nargs="+")
    ap.add_argument("--supply", action="append", default=[])
    ap.add_argument("--data-type", action="append", default=[])
    ap.add_argument("--contacts", type=int, default=0, help="resolve contacts for top N leads")
    ap.add_argument("--out", type=Path, default=Path("./out_scout"))
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    rows = []
    for d in a.diseases:
        t0 = time.time()
        q = SearchQuery(disease=d, supply=a.supply, data_types=a.data_type)
        print(f"\n=== {q.label()}", file=sys.stderr, flush=True)
        try:
            doc = dia.run(q, log=lambda m: print(f"  {m}", file=sys.stderr, flush=True))
        except Exception as exc:                       # one failure must not stop the portfolio
            rows.append({"disease": d, "error": f"{type(exc).__name__}: {exc}"})
            continue
        slug = "".join(c if c.isalnum() else "_" for c in d.lower())
        (a.out / f"{slug}.leads.json").write_text(json.dumps(doc, default=str), encoding="utf-8")
        contactable = None
        if a.contacts:
            recs = pcia.resolve(doc, top=a.contacts, log=lambda m: None)
            contactable = sum(r.exportable for r in recs)
            (a.out / f"{slug}.contacts.json").write_text(
                json.dumps(pcia.to_json(recs, doc["disease"]), default=str), encoding="utf-8")
        leads = doc["leads"]
        stated = [l for l in leads if any(k in dia.NEEDS and dia.NEEDS[k][2] for k in l["needs"])]
        data_needs = {}
        for l in leads:
            for k in l["needs"]:
                if k.startswith("data_"):
                    data_needs[k] = data_needs.get(k, 0) + 1
        us_gap = sum(1 for l in leads if "geographic_gap" in l["needs"])
        industry_ab = [l for l in leads if l["org_type"] == "industry" and l["tier"] in "AB"]
        rows.append({
            "disease": d, "signals": doc["summary"]["signals"], "organisations": len(leads),
            "tiers": doc["summary"]["tiers"], "by_registry": doc["summary"]["by_registry"],
            "stated_gap_orgs": len(stated), "data_type_needs": data_needs,
            "no_supply_sites_orgs": us_gap, "industry_tier_ab": len(industry_ab),
            "contactable_top": contactable,
            "top": [{"org": l["org_display"], "tier": l["tier"], "score": l["score"],
                     "type": l["org_type"], "country": l["country"],
                     "angle": l["opening_angle"]} for l in leads[:8]],
            "top_industry": [l["org_display"] for l in industry_ab[:6]],
            "seconds": round(time.time() - t0)})
        (a.out / "summary.json").write_text(json.dumps(rows, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
