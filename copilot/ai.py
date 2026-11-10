"""AI providers.

LiveClaude    - calls the Claude API with structured outputs.
SavedResponses - replays real responses saved earlier by scripts/build_cache.py.
Hybrid        - live when a key and quota are available, otherwise saved; never breaks the demo.

The provider is the only module that talks to a model, so swapping in another host
(Amazon Bedrock, Google Vertex AI, Snowflake Cortex or a local open-source model) means
writing one more class with the same analyse() method.
"""
import hashlib
import json
import time
from datetime import date, datetime, timezone
from pathlib import Path

from . import config
from .schemas import CaseAnalysis


class AIUnavailable(Exception):
    pass


def input_hash(system, message):
    return hashlib.sha256((config.PROMPT_VERSION + system + message).encode()).hexdigest()[:16]


class LiveClaude:
    name = "live"

    def __init__(self, api_key, model=config.MODEL, effort=config.EFFORT):
        import anthropic
        self._anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=api_key, max_retries=2, timeout=120)
        self.model, self.effort = model, effort

    def analyse(self, case_id, system, message):
        a = self._anthropic
        t0 = time.time()
        try:
            resp = self.client.messages.parse(
                model=self.model,
                max_tokens=config.MAX_TOKENS,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": message}],
                output_format=CaseAnalysis,
                output_config={"effort": self.effort},
            )
        except (a.AuthenticationError, a.PermissionDeniedError) as e:
            raise AIUnavailable(f"API key rejected: {e.message}") from e
        except a.RateLimitError as e:
            raise AIUnavailable("Rate limited or out of credit") from e
        except a.APIStatusError as e:
            raise AIUnavailable(f"API error {e.status_code}") from e
        except a.APIConnectionError as e:
            raise AIUnavailable("Could not reach the API") from e
        if resp.stop_reason == "refusal":
            raise AIUnavailable("The model declined this request; route the case to manual triage")
        if resp.stop_reason == "max_tokens" or resp.parsed_output is None:
            raise AIUnavailable("Response incomplete; route the case to manual triage")
        u = resp.usage
        meta = {
            "provider": "live", "model": resp.model, "effort": self.effort,
            "prompt_version": config.PROMPT_VERSION, "request_id": resp._request_id,
            "latency_s": round(time.time() - t0, 1),
            "usage": {"input": u.input_tokens, "output": u.output_tokens,
                      "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0,
                      "cache_write": getattr(u, "cache_creation_input_tokens", 0) or 0},
            "input_hash": input_hash(system, message),
        }
        return resp.parsed_output, meta


def _inline_refs(schema):
    """Replace $ref/$defs with inline copies; some local runtimes handle flat schemas more reliably."""
    defs = schema.get("$defs", {})

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(defs[node["$ref"].split("/")[-1]])
            return {k: walk(v) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node
    return walk(schema)


class LocalOllama:
    """A model running on this machine through Ollama (https://ollama.com). No key, no data leaves the laptop."""
    name = "local"

    def __init__(self, model=config.OLLAMA_MODEL, url=config.OLLAMA_URL, timeout=600):
        self.model, self.url, self.timeout = model, url.rstrip("/"), timeout

    @staticmethod
    def _opener():
        import urllib.request
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))  # local traffic never goes via a proxy

    def available(self):
        try:
            with self._opener().open(f"{self.url}/api/tags", timeout=3) as r:
                tags = json.loads(r.read())
            return any(m.get("name", "").startswith(self.model) for m in tags.get("models", []))
        except Exception:
            return False

    def _chat(self, messages):
        import urllib.request
        body = {
            "model": self.model, "messages": messages, "stream": False,
            "format": _inline_refs(CaseAnalysis.model_json_schema()),
            # num_ctx must hold the whole policy set plus the case, or the model silently loses the start.
            "options": {"temperature": 0, "num_ctx": 16384},
        }
        req = urllib.request.Request(f"{self.url}/api/chat", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with self._opener().open(req, timeout=self.timeout) as r:
            return json.loads(r.read())

    def analyse(self, case_id, system, message):
        from pydantic import ValidationError
        t0 = time.time()
        messages = [{"role": "system", "content": system}, {"role": "user", "content": message}]
        last_err = None
        for _attempt in range(2):
            try:
                out = self._chat(messages)
            except Exception as e:
                raise AIUnavailable(f"Local model not reachable at {self.url}: {e}") from e
            text = out.get("message", {}).get("content", "")
            try:
                analysis = CaseAnalysis.model_validate_json(text)
                break
            except ValidationError as e:
                last_err = e
                messages += [{"role": "assistant", "content": text},
                             {"role": "user", "content": f"That did not match the required format: {e}. Return corrected JSON only."}]
        else:
            raise AIUnavailable(f"Local model output did not match the schema: {last_err}")
        meta = {
            "provider": "local", "model": f"ollama/{self.model}", "effort": None,
            "prompt_version": config.PROMPT_VERSION, "request_id": None,
            "latency_s": round(time.time() - t0, 1),
            "usage": {"input": out.get("prompt_eval_count", 0), "output": out.get("eval_count", 0),
                      "cache_read": 0, "cache_write": 0},
            "input_hash": input_hash(system, message),
        }
        return analysis, meta


class SavedResponses:
    name = "saved"

    def __init__(self, cache_dir: Path = config.CACHE_DIR):
        self.dir = cache_dir

    def path(self, case_id):
        return self.dir / f"{case_id}.json"

    def has(self, case_id, system, message):
        p = self.path(case_id)
        if not p.exists():
            return False
        return json.loads(p.read_text())["meta"]["input_hash"] == input_hash(system, message)

    def analyse(self, case_id, system, message):
        if not self.has(case_id, system, message):
            raise AIUnavailable("No saved response for this exact input. Live AI is needed for new or edited cases.")
        rec = json.loads(self.path(case_id).read_text())
        meta = dict(rec["meta"], provider="saved", saved_at=rec["saved_at"])
        return CaseAnalysis.model_validate(rec["analysis"]), meta

    def save(self, case_id, analysis, meta):
        self.dir.mkdir(parents=True, exist_ok=True)
        rec = {"saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "meta": meta, "analysis": analysis.model_dump()}
        self.path(case_id).write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n")


class DailyQuota:
    """Process-wide daily cap on live calls, persisted to a small file."""

    def __init__(self, cap=config.DAILY_LIVE_CAP, path=Path("/tmp/copilot_quota.json")):
        self.cap, self.path = cap, path

    def _load(self):
        try:
            d = json.loads(self.path.read_text())
            return d if d.get("day") == date.today().isoformat() else {"day": date.today().isoformat(), "used": 0}
        except Exception:
            return {"day": date.today().isoformat(), "used": 0}

    def remaining(self):
        return max(0, self.cap - self._load()["used"])

    def use(self):
        d = self._load()
        d["used"] += 1
        try:
            self.path.write_text(json.dumps(d))
        except Exception:
            pass


class Hybrid:
    """Prefer live when allowed; fall back to saved responses with a clear reason."""

    def __init__(self, live=None, saved=None, quota=None):
        self.live, self.saved = live, saved or SavedResponses()
        self.quota = quota or DailyQuota()

    def analyse(self, case_id, system, message, want_live=False, session_left=None):
        reason = None
        if want_live:
            if self.live is None:
                reason = "No API key configured, so showing the saved response."
            elif self.quota.remaining() <= 0:
                reason = "Today's live quota is used up, so showing the saved response."
            elif session_left is not None and session_left <= 0:
                reason = "This session's live quota is used up, so showing the saved response."
            else:
                try:
                    self.quota.use()
                    a, m = self.live.analyse(case_id, system, message)
                    return a, m, None
                except AIUnavailable as e:
                    reason = f"Live AI unavailable ({e}), so showing the saved response."
        a, m = self.saved.analyse(case_id, system, message)
        return a, m, reason
