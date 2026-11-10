"""Remove personal data BEFORE anything is sent to an AI model.

Approach: pattern rules for structured identifiers (emails, phones, sort codes,
account numbers, card digits, postcodes, dates of birth, street addresses) plus
context rules for names (titles, "Cust ...", sign-offs, relationship words).
Any name found once is then masked everywhere it appears in the case
("propagation"), which catches lowercase or repeated mentions.

The token -> original mapping stays on the bank's side and is never sent to
the model. Known limitation: a name that never appears in a recognisable
context can be missed; see docs/assumptions.md and the evaluation results.
"""
import re
from dataclasses import dataclass, field

STREET_SUFFIX = (r"(?:Road|Street|Lane|Way|Close|Crescent|Rise|Avenue|Drive|Grove|Court|Place|"
                 r"Gardens|Terrace|Hill|Park|View|Row|Mews|Square|Walk)")
NAME = r"[A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)*"
NAME_ANY = r"[A-Za-z][a-z]+(?:[-'][A-Za-z]?[a-z]+)*"

PATTERNS = [
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    ("PHONE", re.compile(r"(?:\+44\s?7\d{3}|\b07\d{3})\s?\d{3}\s?\d{3}\b")),
    ("SORT_CODE", re.compile(r"(?i)(?<=sort code )\d{2}[-\s]?\d{2}[-\s]?\d{2}\b")),
    ("SORT_CODE", re.compile(r"\b\d{2}-\d{2}-\d{2}\b")),
    ("CARD_NUMBER", re.compile(r"\b(?:\d{4}[\s-]?){3}\d{4}\b")),
    ("CARD_DIGITS", re.compile(r"(?i)(?<=ending )(?:in )?\d{4}\b")),
    ("ACCOUNT_NUMBER", re.compile(r"\b\d{8}\b")),
    ("DATE_OF_BIRTH", re.compile(r"(?i)(?<=dob )\d{1,2}/\d{1,2}/\d{2,4}")),
    ("DATE_OF_BIRTH", re.compile(r"\b\d{1,2}/\d{1,2}/(?:19\d{2}|200[0-8])\b")),
    ("POSTCODE", re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}\b")),
    ("ADDRESS", re.compile(rf"\b\d{{1,4}}[A-Za-z]? (?:{NAME} ){{1,3}}{STREET_SUFFIX}\b(?:, (?:{NAME} ?){{1,3}})?")),
]

# Name in a recognisable context. Group "n" is the name.
TITLE_RE = re.compile(rf"\b(?:Mr|Mrs|Ms|Miss|Mx|Dr)\.? (?P<n>{NAME}(?: {NAME})?)")
CONTEXT_RE = re.compile(
    rf"(?:\b(?:[Cc]ust(?:omer)?|[Cc]aller|[Nn]ame of|[Dd]aughter|[Ss]on|[Mm]other|[Ff]ather|"
    rf"[Hh]usband|[Ww]ife|[Pp]artner|[Ee]x-partner|[Cc]arer|[Ee]xecutor is|[Ff]rom|[Hh]older|"
    rf"[Dd]ear|[Hh]i|[Hh]ello)[:,]? )(?P<n>{NAME}(?: {NAME})?)")
SIGNOFF_RE = re.compile(
    rf"(?im)(?:faithfully|sincerely|regards|thanks|thank you|cheers|many thanks)[,!.]?\s*\n?\s*"
    rf"(?P<n>{NAME_ANY}(?: {NAME_ANY})?)\s*(?:\(|,|\n|$)")
# Sign-off at the very end of a message: "... real reason. Rhys Treharne" or "\nyusuf"
SIG_END_RE = re.compile(rf"(?:[.!?]\s+|\n\s*)(?P<n>{NAME}(?: {NAME})?)(?:,[^\n]*)?\s*$")
SIG_END_LC_RE = re.compile(r"\n\s*(?P<n>[a-z]{3,}(?: [a-z]{3,})?)\s*$")
# A line that is only a name (signature block), e.g. "\nDaniel Okafor\n"
SIG_LINE_RE = re.compile(rf"(?m)^(?P<n>{NAME} {NAME})\s*(?:,|$)")

NOT_NAMES = {
    "Harbourline", "Bank", "The", "This", "Thanks", "Cust", "Caller", "Card", "Account", "Online",
    "Banking", "Fraud", "Team", "Hello", "Dear", "Hi", "Yours", "Please", "Sort", "Code", "Email",
    "Statement", "Mortgage", "Savings", "Travel", "Easy", "Saver", "Everyday", "Digital", "Ops",
    "Support", "Mum", "Dad", "Branch", "System", "Note", "Phone", "Mobile", "Letter", "Payment",
    "Kingsbridge", "Road", "Lisbon", "Spain", "Android", "Customer", "Complaints", "Concern",
    "Whom", "To", "It", "Got", "She", "He", "They", "Said", "Says", "Wants", "Reported", "Logged",
    "Sir", "Madam", "Regards", "Sincerely", "Faithfully", "Cheers", "Best", "Kind", "Warm", "Love", "HMRC", "TechNova", "WhatsApp", "Mr", "Mrs", "Ms", "Miss", "Mx", "Dr",
}


@dataclass
class Redaction:
    text_by_part: dict  # part name -> redacted text
    mapping: dict = field(default_factory=dict)  # token -> original value
    found: list = field(default_factory=list)  # [(type, value)]


def _name_candidates(text, parts=()):
    out = set()
    found = []
    for rx in (TITLE_RE, CONTEXT_RE, SIGNOFF_RE, SIG_LINE_RE):
        found += list(rx.finditer(text))
    for part in parts:
        for rx in (SIG_END_RE, SIG_END_LC_RE):
            found += list(rx.finditer(part))
    for m in found:
        if True:
            words = [w for w in m.group("n").split() if w.capitalize() not in NOT_NAMES and len(w) > 1]
            if words:
                out.add(" ".join(words))
    return out


def redact_case(parts: dict) -> Redaction:
    """Redact several pieces of text from one case with one consistent token set.

    parts: {"complaint": str, "note_1": str, ...}
    """
    joined = "\n".join(parts.values())
    values = []  # (type, value)
    for ptype, rx in PATTERNS:
        for m in rx.finditer(joined):
            values.append((ptype, m.group(0)))
    names = _name_candidates(joined, parts.values())
    # Propagate: every word of a detected full name is itself a name to mask.
    name_values = set()
    for n in names:
        name_values.add(n)
        for w in n.split():
            if len(w) > 2:
                name_values.add(w)
    values += [("PERSON", n) for n in sorted(name_values, key=lambda x: (-len(x), x))]

    # Assign stable tokens. Persons share a token per full name; parts map to the same.
    mapping, token_of = {}, {}
    counters = {}
    persons_full = sorted([n for n in name_values if " " in n], key=len, reverse=True)
    for ptype, v in values:
        key = (ptype, v.lower())
        if key in token_of:
            continue
        if ptype == "PERSON" and " " not in v:
            parent = next((f for f in persons_full if v.lower() in f.lower().split()), None)
            if parent and ("PERSON", parent.lower()) in token_of:
                token_of[key] = token_of[("PERSON", parent.lower())]
                continue
        counters[ptype] = counters.get(ptype, 0) + 1
        tok = f"[{ptype}_{counters[ptype]}]"
        token_of[key] = tok
        mapping[tok] = v
    # Make sure full names are tokenised before their single-word parts.
    for n in persons_full:
        for w in n.split():
            k = ("PERSON", w.lower())
            if k in token_of:
                token_of[k] = token_of[("PERSON", n.lower())]

    # Replace longest values first so "Daniel Okafor" wins over "Daniel".
    ordered = sorted({(t, v) for t, v in values}, key=lambda x: len(x[1]), reverse=True)
    out = {}
    for part, text in parts.items():
        red = text
        for ptype, v in ordered:
            tok = token_of[(ptype, v.lower())]
            flags = re.IGNORECASE if ptype == "PERSON" else 0
            red = re.sub(rf"(?<![\w\[]){re.escape(v)}(?![\w\]])", tok, red, flags=flags)
        out[part] = red
    return Redaction(text_by_part=out, mapping=mapping, found=sorted(set(values)))


def case_parts(case):
    parts = {"complaint": case["complaint"]}
    for i, n in enumerate(case["case_notes"], 1):
        parts[f"note_{i}"] = n["text"]
    return parts


def reidentify(text, mapping):
    """For the authorised reviewer's screen only. Never used on anything sent to the model."""
    for tok, v in mapping.items():
        text = text.replace(tok, v)
    return text
