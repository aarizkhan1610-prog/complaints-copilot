"""Jump to source: find and highlight the exact words behind an AI claim."""
import html
import re

from .data import POLICY_DIR

WORD_RE = re.compile(r"\S+")


def _key(w):
    return re.sub(r"[^a-z0-9£%\[\]_]+", "", w.lower())


def find_span(text, quote):
    """(start, end) character span in text that best matches quote, or None.
    Exact match (ignoring case and punctuation) first; otherwise the window of words with most overlap."""
    if not quote or not text:
        return None
    words = [(m.start(), m.end(), _key(m.group())) for m in WORD_RE.finditer(text)]
    q = [k for k in (_key(w) for w in quote.split()) if k]
    if not q or not words:
        return None
    keys = [w[2] for w in words]
    n = len(q)
    for i in range(len(keys) - n + 1):
        if keys[i:i + n] == q:
            return words[i][0], words[i + n - 1][1]
    qs, best, best_i = set(q), 0, None
    for i in range(len(keys)):
        window = keys[i:i + n]
        score = sum(k in qs for k in window)
        if score > best:
            best, best_i = score, i
    if best_i is None or best / n < 0.6:
        return None
    j = min(len(words), best_i + n) - 1
    return words[best_i][0], words[j][1]


def highlight_html(text, quote=None, whole=False):
    """Escape text for HTML and wrap the matching span (or all of it) in <mark>."""
    if whole:
        return f"<mark>{html.escape(text)}</mark>".replace("\n", "<br>")
    span = find_span(text, quote) if quote else None
    if not span:
        return html.escape(text).replace("\n", "<br>")
    a, b = span
    return (html.escape(text[:a]) + "<mark>" + html.escape(text[a:b]) + "</mark>" +
            html.escape(text[b:])).replace("\n", "<br>")


def policy_document(clause_id):
    """Full markdown of the policy file that holds clause_id, with that clause highlighted."""
    prefix = clause_id.split("-")[0].upper()
    files = sorted(POLICY_DIR.glob(f"{prefix}_*.md"))
    if not files:
        return None
    raw = files[0].read_text()
    out = []
    for para in raw.split("\n\n"):
        if para.lstrip().startswith(f"**{clause_id}"):
            para = "> " + para.replace("\n", "\n> ")
            para = "> 👉 **Cited clause**\n>\n" + para
        out.append(para)
    return "\n\n".join(out)
