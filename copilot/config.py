"""Central settings. Everything that an assessor might want to change lives here."""
import os
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Load a local .env file if present (git-ignored), without overriding real environment variables.
_env = ROOT / ".env"
if _env.exists():
    for _line in _env.read_text().splitlines():
        if "=" in _line and not _line.lstrip().startswith("#"):
            _k, _v = _line.split("=", 1)
            if _v.strip():
                os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))
DATA_DIR = ROOT / "data"
POLICY_DIR = DATA_DIR / "policies"
CACHE_DIR = Path(os.environ.get("COPILOT_CACHE_DIR", DATA_DIR / "cached_responses"))
AUDIT_LOG = Path(os.environ.get("COPILOT_AUDIT_LOG", ROOT / "audit_log.jsonl"))

# Fixed "today" so deadline statuses are reproducible (see docs/assumptions.md).
AS_OF = date.fromisoformat(os.environ.get("COPILOT_AS_OF", "2026-11-09"))

# Model settings. The default is Anthropic's current Opus model; effort "low" keeps
# cost and latency down for a structured extraction task.
MODEL = os.environ.get("COPILOT_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("COPILOT_EFFORT", "low")
MAX_TOKENS = 16000

# Which AI backend to use: "claude" (Anthropic API) or "ollama" (a local model on this machine).
PROVIDER = os.environ.get("COPILOT_PROVIDER", "claude")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")
LOCAL_CACHE_DIR = Path(os.environ.get("COPILOT_LOCAL_CACHE_DIR", DATA_DIR / "cached_responses_local"))

# Bump whenever the prompt or output schema changes, so every audit record and
# cached response can be traced to the exact prompt that produced it.
PROMPT_VERSION = "triage-v1.0"

# Spend controls for the hosted demo (layered on top of a prepaid credit cap).
DAILY_LIVE_CAP = int(os.environ.get("COPILOT_DAILY_LIVE_CAP", "50"))
SESSION_LIVE_CAP = int(os.environ.get("COPILOT_SESSION_LIVE_CAP", "10"))


def get_api_key():
    """Read the key from the environment or Streamlit secrets. Never from the repo."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    try:
        import streamlit as st
        return st.secrets.get("ANTHROPIC_API_KEY")
    except Exception:
        return None
