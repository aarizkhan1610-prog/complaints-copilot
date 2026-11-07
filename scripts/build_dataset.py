"""Build data/complaints.json and data/labels.json from scripts/scenarios.py.

Inserts invented personal details with a fixed seed, so the output is
reproducible and the redaction ground truth (which personal details appear in
each case) is exact. Run:  python scripts/build_dataset.py
"""
import json
import random
import string
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from scenarios import SCENARIOS, PRODUCTS, ROOT_CAUSES, TEAMS, GAP_KEYS  # noqa: E402

SEED = 1610
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

FIRST_F = ["Margaret", "Aisha", "Chloe", "Priya", "Hannah", "Bethany", "Niamh", "Olufunke",
           "Grace", "Sofia", "Imogen", "Rukhsana", "Delyth", "Kerry-Ann", "Mei"]
FIRST_M = ["Daniel", "Tomasz", "Kwame", "Rhys", "Arjun", "Callum", "Ibrahim", "Stuart",
           "Oluwaseun", "Patrick", "Euan", "Hamza", "Gareth", "Liam", "Yusuf"]
LAST = ["Okafor", "Whitlock", "Brannigan", "Sandhu", "Pellow", "Varga", "Mensah", "Ashworth",
        "Rahman", "Trevithick", "Lindqvist", "Ogunleye", "Castell", "Mbeki-Hart", "Fairbairn",
        "Quayle", "Dunmore", "Haddad", "Kowalczyk", "Penhaligon", "Abernethy", "Sutcliffe",
        "Nwosu", "Gallacher", "Ferreira", "Holroyd", "Chaudhry", "Mackintosh", "Oyelaran", "Treharne"]
STREETS = ["Alder Way", "Foxglove Crescent", "Mill Lane", "Orchard Rise", "Station Road",
           "Wren Close", "Hawthorn Avenue", "Quarry Street", "Bramble Drive", "Linnet Grove"]
TOWNS = ["Westmere", "Ashcombe", "Lindford", "Harrowgate Vale", "Brackley Moor", "Eastholme"]


def postcode(rng):
    L = string.ascii_uppercase
    return f"{rng.choice('BCDHLMNSTW')}{rng.choice('AEHLNRSTW')}{rng.randint(1, 19)} " \
           f"{rng.randint(1, 9)}{rng.choice(L)}{rng.choice(L)}"


def make_person(rng, gender, used, age=None):
    while True:
        first = rng.choice(FIRST_F if gender == "f" else FIRST_M)
        last = rng.choice(LAST)
        if (first, last) not in used:
            used.add((first, last))
            break
    title = rng.choice(["Mrs", "Ms", "Miss"]) if gender == "f" else "Mr"
    year = 2026 - age if age else rng.randint(1958, 2003)
    tail = rng.randint(100, 999)
    phone_fmt = rng.choice(["{a} {b}", "{a}{b}", "+44 7700 {b}"])
    sep = rng.choice(["-", "", " "])
    sort = sep.join(f"{rng.randint(0, 99):02d}" for _ in range(3))
    email = f"{first.lower()}.{last.lower()}{rng.randint(1, 99)}@example.com".replace("'", "")
    return {
        "FIRST": first, "LAST": last, "FULL": f"{first} {last}", "TITLE": f"{title} {last}",
        "EMAIL": email,
        "email_upper": email[0].upper() + email[1:].replace("@example", "@Example"),
        "PHONE": phone_fmt.format(a="07700", b=f"900{tail}"),
        "PHONE_COMPACT": f"07700900{tail}",
        "ACCT": f"{rng.randint(10000000, 99999999)}",
        "SORT": sort,
        "CARD4": f"{rng.randint(1000, 9999)}",
        "ADDRESS": f"{rng.randint(2, 180)} {rng.choice(STREETS)}, {rng.choice(TOWNS)}",
        "POSTCODE": postcode(rng),
        "DOB": f"{rng.randint(1, 28):02d}/{rng.randint(1, 12):02d}/{year}",
        "first_lc": first.lower(), "last_lc": last.lower(), "full_lc": f"{first} {last}".lower(),
    }


PII_TYPES = {
    "FULL": "PERSON", "FIRST": "PERSON", "LAST": "PERSON", "TITLE": "PERSON",
    "first_lc": "PERSON", "last_lc": "PERSON", "full_lc": "PERSON",
    "P2": "PERSON", "P2_FIRST": "PERSON",
    "EMAIL": "EMAIL", "email_upper": "EMAIL",
    "PHONE": "PHONE", "PHONE_COMPACT": "PHONE",
    "ACCT": "ACCOUNT_NUMBER", "SORT": "SORT_CODE", "CARD4": "CARD_DIGITS",
    "ADDRESS": "ADDRESS", "POSTCODE": "POSTCODE", "DOB": "DATE_OF_BIRTH",
}


def build():
    rng = random.Random(SEED)
    used = set()
    complaints, labels = [], {}
    for i, sc in enumerate(SCENARIOS):
        age = 78 if sc["id"] == "C002" else None
        vals = make_person(rng, sc["gender"], used, age)
        p2 = make_person(rng, sc.get("p2_gender", rng.choice("fm")), used)
        vals["P2"], vals["P2_FIRST"] = p2["FULL"], p2["FIRST"]

        complaint = sc["complaint"].format_map(vals)
        notes = [{"date": d, "author": a, "text": t.format_map(vals)} for d, a, t in sc["notes"]]
        full_text = complaint + "\n" + "\n".join(n["text"] for n in notes)

        pii = []
        for key, ptype in PII_TYPES.items():
            v = vals[key]
            if v in full_text and {"type": ptype, "value": v} not in pii:
                pii.append({"type": ptype, "value": v})
        for ptype, v in sc.get("extra_pii", []):
            assert v in full_text, (sc["id"], v)
            pii.append({"type": ptype, "value": v})

        complaints.append({
            "id": sc["id"],
            "customer_ref": f"HBK-{4100 + i * 37}",
            "received": sc["received"],
            "channel": sc["channel"],
            "complaint": complaint,
            "case_notes": notes,
            "evidence": sc["evidence"],
        })
        lab = dict(sc["labels"])
        lab.setdefault("severity_alt", [])
        lab["pii"] = pii
        labels[sc["id"]] = lab
        validate(sc["id"], lab, full_text)

    DATA.mkdir(exist_ok=True)
    (DATA / "complaints.json").write_text(json.dumps(complaints, indent=2, ensure_ascii=False) + "\n")
    (DATA / "labels.json").write_text(json.dumps(labels, indent=2, ensure_ascii=False) + "\n")
    return complaints, labels


def validate(cid, lab, text):
    assert "{" not in text and "}" not in text, f"{cid}: unfilled placeholder"
    assert lab["product"] in PRODUCTS, cid
    if lab["is_complaint"]:
        assert lab["root_cause"] in ROOT_CAUSES, cid
    for rc in lab["root_cause_alt"]:
        assert rc in ROOT_CAUSES, (cid, rc)
    assert lab["severity"] in {"Low", "Medium", "High"}, cid
    for t in lab["specialist_team"] or []:
        assert t in TEAMS, (cid, t)
    for g in lab["handover_gaps"]:
        assert g in GAP_KEYS, (cid, g)
    policy_ids = set()
    for f in (DATA / "policies").glob("*.md"):
        import re
        policy_ids |= set(re.findall(r"\*\*([A-Z]{2,3}-\d+)", f.read_text()))
    for c in lab["clauses"]:
        assert c in policy_ids, (cid, c)


if __name__ == "__main__":
    complaints, labels = build()
    n_pii = sum(len(l["pii"]) for l in labels.values())
    print(f"Wrote {len(complaints)} complaints, {n_pii} personal-data items in the answer key.")
