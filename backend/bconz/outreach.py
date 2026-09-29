"""First-touch outreach drafts for a DIA lead.

The draft is written from the lead's own evidence, most concrete first: a
cleared product, a funded company project, the sentence in their paper that
states the need, a trial with no sites where the data comes from. A person
reading it should see why *they* were written to.

Rules the drafts keep:
  * Nothing about a dataset is quoted unless the dataset profile carries an
    `outreach_blurb` approved for sharing. Otherwise the offer is described by
    origin and data type only, with no figures and no partner name (partner
    catalogs are often under NDA).
  * Early-access framing: "preparing access, subject to governance".
  * Every draft says where the address was found, offers a one-line opt-out,
    and carries BCONZ's postal address (UK GDPR/PECR, CAN-SPAM, PIPA).
  * Sending stays with a person. This module only writes text.
"""
from __future__ import annotations

import re
from datetime import datetime

from .query import ALL_ORIGINS, DATA_TYPES, SUPPLY, supply_label

SENDER = {"name": "Shaw", "org": "BCONZ", "email": "shaw@bconz.com", "web": "www.bconz.com"}
POSTAL = ("Bconz International (OPC) Pvt Ltd, Manipal County Road, Bangalore 560068, India · "
          "60 Paya Lebar Road #06-53, Paya Lebar Square, Singapore 409051")
LINKEDIN_LIMIT = 300          # a LinkedIn connection note
OFFER_WORD = {"ultrasound": "ultrasound and echo", "ecg": "ECG", "ehr": "EHR", "pro": "patient-reported outcome"}


def _month(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso[:10]).strftime("%B %Y")
    except (ValueError, TypeError):
        return ""


def _clip(text: str, n: int) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= n:
        return text
    cut = text[:n].rsplit(" ", 1)[0]
    return cut.rstrip(",;:") + "…"


def _quote(sentence: str, n: int = 220) -> str:
    """The stated need, as they wrote it, trimmed at a word boundary."""
    s = re.sub(r"^(Background|Objectives?|Purpose|Conclusions?|Results?|Methods?)(?=[A-Z])", "",
               (sentence or "").strip())
    return _clip(s, n).rstrip(".")


def _device_name(title: str) -> str:
    name = re.sub(r"\s*\((K|DEN|P)\d[\w/]*\)\s*$", "", title or "").strip()
    return re.split(r"\s*[/;]\s*", name)[0].strip()


LEGAL_TAIL = re.compile(r"[,\s]+(inc|ltd|llc|gmbh|co\.?,? ?ltd|corp(oration)?|s\.?a\.?s?|s\.l|b\.v|ag|"
                        r"pvt\.? ltd|private limited|limited|plc|pte\.? ltd|uab|oy|ab)\.?$", re.I)


def short_org(name: str) -> str:
    """"Anumana, Inc." -> "Anumana", for a greeting."""
    prev = None
    while prev != name:
        prev, name = name, LEGAL_TAIL.sub("", name.strip())
    return name


def offer_text(dataset: dict | None, supply: list[str] | None) -> tuple[str, str]:
    """(one paragraph, a short phrase) describing what BCONZ can offer."""
    blurb = ((dataset or {}).get("outreach_blurb") or "").strip()
    origins = (dataset or {}).get("origin") or supply or list(ALL_ORIGINS)
    dts = (dataset or {}).get("data_types") or []
    types = [OFFER_WORD.get(t, DATA_TYPES[t][0].split(" /")[0].lower()) for t in dts
             if t in DATA_TYPES and t != "reports"]
    with_reports = " with radiologist reports" if "reports" in dts else ""
    if set(origins) >= set(ALL_ORIGINS):
        where = "sourced directly and through partner networks worldwide"
        adj = ""
    else:
        adj = " and ".join(SUPPLY[o]["adj"] for o in origins if o in SUPPLY) + " "
        where = f"from {supply_label(origins)}"
    kinds = (", ".join(types[:-1]) + " and " + types[-1]) if len(types) > 1 else (types[0] if types else "clinical")
    short = f"de-identified {adj}{kinds} data{with_reports}"
    if blurb:
        return blurb, short
    return (f"BCONZ is preparing research and commercial access, subject to governance, to "
            f"de-identified {kinds} data{with_reports} {where}."), short


def _hook(lead: dict, supply: list[str]) -> dict:
    """The most concrete reason to write, from the lead's evidence."""
    sigs = lead.get("signals") or []
    anchor = ((lead.get("fit") or {}).get("anchor") or {}).get("url")
    devs = [s for s in sigs if s.get("source") == "devices"]
    dev = next((s for s in devs if s.get("url") == anchor), None) or         (max(devs, key=lambda s: s.get("date", "")) if devs else None)
    if dev:
        name, when = _device_name(dev.get("title", "")), _month(dev.get("date", ""))
        return {"kind": "device", "subject": f"Validation data for {name}",
                "line": (f"Congratulations on the FDA clearance of {name}" + (f" ({when})" if when else "")
                         + ". Each new indication, site and market brings the same need: validation data "
                           "from a population the model hasn't yet seen."),
                "short": f"your FDA clearance of {name}"}
    grant = next((s for s in sigs if "company_grant" in (s.get("needs") or {})), None)
    if grant:
        funder = (grant.get("extra") or {}).get("registry", "")
        return {"kind": "grant", "subject": "Data for your funded product development",
                "line": f"I saw your funded project \"{_clip(grant.get('title', ''), 110)}\""
                        + (f" ({funder})" if funder else "") + ".",
                "short": f"your project \"{_clip(grant.get('title', ''), 60)}\""}
    paper = next((s for s in sigs if s.get("url") == anchor and s.get("source") == "publications"), None) \
        or next((s for s in sigs if s.get("source") == "publications"
                 and any(k.startswith(("data_", "diverse", "external", "single", "general", "small", "real", "longit"))
                         for k in (s.get("needs") or {}))), None)
    if paper:
        needs = paper.get("needs") or {}
        sentence = next((v for k, v in needs.items() if k not in ("company_rnd",)), "")
        title = _clip(paper.get("title", ""), 110)
        if sentence:
            return {"kind": "paper", "subject": "Data for the gap your paper describes",
                    "line": f"I read your paper \"{title}\". You noted that \"{_quote(sentence)}\". "
                            "That is why I'm writing.",
                    "short": f"your paper \"{_clip(paper.get('title', ''), 60)}\""}
    cpaper = next((s for s in sigs if "company_rnd" in (s.get("needs") or {})), None)
    if cpaper:
        return {"kind": "company_paper", "subject": "Data for your team's research",
                "line": f"I read your team's paper \"{_clip(cpaper.get('title', ''), 110)}\".",
                "short": f"your team's paper \"{_clip(cpaper.get('title', ''), 60)}\""}
    trial = next((s for s in sigs if "geographic_gap" in (s.get("needs") or {})), None)
    if trial:
        return {"kind": "trial", "subject": f"Evidence from {supply_label(supply)} for your study",
                "line": f"I saw your study \"{_clip(trial.get('title', ''), 110)}\". "
                        f"{trial['needs']['geographic_gap']}.",
                "short": f"your study \"{_clip(trial.get('title', ''), 60)}\""}
    return {"kind": "generic", "subject": "Research-ready data for your work",
            "line": "I'm writing because your organisation's recent work suggests a need for data we can help with.",
            "short": "your recent work"}


USE = {
    "ai_product_imaging": "External validation and training data for new indications, sites and markets",
    "ai_product": "External validation and training data for new indications, sites and markets",
    "company_grant": "Training and validation data for your funded development",
    "diverse_population": "Data from a population under-represented in most datasets",
    "generalisability": "Data from a different population and care setting, to test generalisability",
    "single_centre": "Data from many sites, beyond a single centre",
    "external_validation": "An independent cohort for external validation",
    "small_sample": "A larger cohort than a single study can provide",
    "real_world_data": "Real-world clinical data",
    "longitudinal_gap": "Repeat data on the same patients over time",
}


def _uses(lead: dict, hook_kind: str, supply: list[str]) -> list[str]:
    """What the dataset could do for them, in plain words.

    Deliberately never the fit's "why" text: it carries the profile's exact
    counts ("2985 sites"), which partner NDAs usually forbid sharing.
    """
    out: list[str] = []
    for r in (lead.get("fit") or {}).get("met", []):
        code = r.get("need", "")
        if code.startswith("data_") and code[5:] in DATA_TYPES:
            use = f"{DATA_TYPES[code[5:]][2][0].upper()}{DATA_TYPES[code[5:]][2][1:]}, which your work notes is missing"
        elif code == "geographic_gap":
            use = f"Evidence from {supply_label(supply)}, where your programme has no sites"
        else:
            use = USE.get(code, "")
        if use and use not in out:
            out.append(use)
    if not out and hook_kind == "device":
        out = [USE["ai_product_imaging"]]
    return out[:3]


def draft(lead: dict, dataset: dict | None = None, supply: list[str] | None = None,
          person_name: str = "", found_at: str = "") -> dict:
    """{subject, body, linkedin} for a first message to this lead."""
    supply = supply or (dataset or {}).get("origin") or list(ALL_ORIGINS)
    org = lead.get("org_display", "")
    hook = _hook(lead, supply)
    offer, short_offer = offer_text(dataset, supply)
    uses = _uses(lead, hook["kind"], supply)
    person = person_name.strip()
    greet = f"Dear {person}," if person else f"Dear {short_org(org)} team,"
    forward = "" if person else ("Please forward this to whoever leads data partnerships or clinical "
                                 "validation.\n\n")
    source = (f"I found your address on {found_at.strip()}." if found_at.strip()
              else f"I found your address on {WHERE_PLACEHOLDER}.")
    lines = [greet, "", forward + hook["line"], "", offer]
    if uses:
        lines += ["", "For your work, it could offer:"] + [f"- {u}" for u in uses]
    lines += ["",
              "We're speaking to a small number of groups before access opens. Would a 20-minute call "
              "in the next few weeks be useful? I'd like to understand what your next study or product "
              "needs, so we can check feasibility honestly.",
              "", "Best regards,", SENDER["name"],
              f"{SENDER['org']} | {SENDER['email']} | {SENDER['web']}", "",
              f"{source} If you'd prefer not to hear from us, reply \"no\" and I won't write again.",
              POSTAL]
    first = person.split()[0] if person else ""
    li = (f"Hi {first}, " if first else "Hello, ") + (
        f"I came across {hook['short']}. BCONZ is preparing governed access to {short_offer} "
        f"that may fit. Open to a short call? – {SENDER['name']}, {SENDER['org']}")
    if len(li) > LINKEDIN_LIMIT:
        li = (f"Hi {first}, " if first else "Hello, ") + (
            f"BCONZ is preparing governed access to {short_offer} relevant to {short_org(org)}'s work. "
            f"Open to a short call? – {SENDER['name']}, {SENDER['org']}")
    return {"subject": hook["subject"], "body": "\n".join(lines).replace("\n\n\n", "\n\n"),
            "linkedin": li[:LINKEDIN_LIMIT], "angle": hook["kind"]}


# Filled in by the send script when the address was found after drafting.
WHERE_PLACEHOLDER = "[where you found it]"

EMAIL_OK = re.compile(r"^[\w.+'-]+@[\w-]+(\.[\w-]+)+$")
