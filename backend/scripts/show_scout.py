"""Print a scout summary.json compactly for review."""
import json
import sys

for path in sys.argv[1:]:
    for r in json.load(open(path, encoding="utf-8")):
        if "error" in r:
            print(f"\n### {r['disease']}: ERROR {r['error']}")
            continue
        print(f"\n### {r['disease']}  ({r['seconds']}s)")
        print(f"  orgs {r['organisations']} | tiers {r['tiers']} | stated-gap orgs {r['stated_gap_orgs']} "
              f"| no-US-site orgs {r['no_supply_sites_orgs']} | industry A/B {r['industry_tier_ab']} "
              f"| contactable(top15) {r['contactable_top']}")
        print(f"  registries {r['by_registry']}")
        print(f"  data-type needs {r['data_type_needs']}")
        for t in r["top"][:6]:
            print(f"   {t['score']:>5} {t['tier']} {t['type']:<10} {t['country'] or '--':<3} {t['org'][:48]}")
            print(f"         -> {t['angle'][:170]}")
        print(f"  industry A/B: {', '.join(r['top_industry'])}")
