"""Alpha8: share-grade redaction for posting diagnostics to GitHub issues.

Extends :mod:`codex_rescue.redact` with the token shapes that actually
appear in Codex session logs and crash dumps (field evidence: users
refuse to post logs without stronger guarantees):

- OpenAI project/user keys: ``sk-proj-...``, ``sk-svcacct-...``, ``sk-None-...``
- AWS access keys: ``AKIA...`` / ``ASIA...`` (16 uppercase alnum suffix)
- Google API keys ``AIza...``, Slack ``xox[baprs]-...``, Anthropic
  ``sk-ant-...``, npm tokens, generic hex/base64url secrets assigned to
  secret-looking JSON keys.
- Windows user-profile paths beyond the existing POSIX ones, WSL
  ``/mnt/<drive>/Users/<name>`` spellings, and ``\\\\?\\`` extended forms.
- Emails already covered upstream; kept.

``redact_for_share()`` returns both the sanitized text and a hit count so
callers can display "N secrets removed" as positive evidence of local
processing (zero-telemetry positioning).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .redact import redact_text

SHARE_SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # OpenAI-style keys with structured prefixes.
    (re.compile(r"sk-proj-[A-Za-z0-9_\-]{20,}"), "[REDACTED_OPENAI_KEY]"),
    (re.compile(r"sk-svcacct-[A-Za-z0-9_\-]{20,}"), "[REDACTED_OPENAI_KEY]"),
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"), "[REDACTED_ANTHROPIC_KEY]"),
    (re.compile(r"sk-None-[A-Za-z0-9_\-]{20,}"), "[REDACTED_OPENAI_KEY]"),
    # Cloud provider keys.
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "[REDACTED_AWS_KEY]"),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}\b"), "[REDACTED_GOOGLE_KEY]"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}"), "[REDACTED_SLACK_TOKEN]"),
    (re.compile(r"\bnpm_[A-Za-z0-9]{36}\b"), "[REDACTED_NPM_TOKEN]"),
    # Generic authorization headers not caught by the bearer rule.
    (
        re.compile(r"(?i)(authorization\s*:\s*(?:basic|token)\s+[A-Za-z0-9_\-.=+/]{10,})"),
        "[REDACTED_AUTH_HEADER]",
    ),
]

SHARE_PATH_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Windows user profiles incl. \\?\ extended-length spellings.
    (
        re.compile(r"(?:\\\\?\\)?[A-Za-z]:\\Users\\[A-Za-z0-9_.\- ]+"),
        "~",
    ),
    # WSL translations of Windows profiles.
    (re.compile(r"/mnt/[a-z]/Users/[A-Za-z0-9_.\-]+"), "~"),
]

# Secret-looking JSON/YAML keys whose long values should be dropped even
# when the value format is unknown ("api_key": "a1b2..." / token: eyJ...).
_KEYED_SECRET_RE = re.compile(
    r"""(?i)(["']?(?:api[_-]?key|secret|token|password|passwd|pwd|credential[s]?|auth)["']?\s*[:=]\s*["']?)([A-Za-z0-9_\-./+=]{12,})(["']?)"""
)


@dataclass
class ShareRedactionResult:
    text: str
    hits: dict[str, int] = field(default_factory=dict)

    @property
    def total_hits(self) -> int:
        return sum(self.hits.values())

    def to_dict(self) -> dict[str, object]:
        return {"hits": self.hits, "total": self.total_hits}


def redact_for_share(text: str) -> ShareRedactionResult:
    """Sanitize arbitrary diagnostic text for public posting."""
    if not isinstance(text, str) or not text:
        return ShareRedactionResult(text=text if isinstance(text, str) else "")

    hits: dict[str, int] = {}
    result = text

    def _sub(label: str, repl: str, match: re.Match[str]) -> str:
        hits[label] = hits.get(label, 0) + 1
        return repl

    for pattern, label_repl in SHARE_SECRET_PATTERNS:
        label = label_repl.strip("[]")
        result = pattern.sub(lambda m, r=label_repl, l=label: _sub(l, r, m), result)

    def _keyed_sub(match: re.Match[str]) -> str:
        prefix, value, quote = match.group(1), match.group(2), match.group(3)
        hits["REDACTED_KEYED_SECRET"] = hits.get("REDACTED_KEYED_SECRET", 0) + 1
        return f"{prefix}[REDACTED_KEYED_SECRET]{quote}"

    result = _KEYED_SECRET_RE.sub(_keyed_sub, result)

    for pattern, repl in SHARE_PATH_PATTERNS:
        label = "HOME_PATH"
        result = pattern.sub(lambda m, r=repl, l=label: _sub(l, r, m), result)

    # Upstream baseline patterns last (bearer/sk-/ghp_/JWT/cookie/email/POSIX homes).
    before = result
    result = redact_text(result)
    if result != before:
        # Count upstream hits coarsely by diffing pattern presence.
        for _, repl in [
            *[
                (None, "[REDACTED_BEARER_TOKEN]"),
                (None, "[REDACTED_API_KEY]"),
                (None, "[REDACTED_GITHUB_TOKEN]"),
                (None, "[REDACTED_JWT]"),
                (None, "[REDACTED_COOKIE]"),
                (None, "[REDACTED_EMAIL]"),
                (None, "[REDACTED_PASSWORD]"),
            ]
        ]:
            n = result.count(repl)
            if n:
                hits[repl.strip("[]")] = hits.get(repl.strip("[]"), 0) + n

    return ShareRedactionResult(text=result, hits=hits)
