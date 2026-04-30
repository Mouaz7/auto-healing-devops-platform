"""Build the AUTO_HEAL_REPORT.md that is committed alongside every fix."""
from __future__ import annotations

import datetime


_AGENT_TABLE = """\
| Steg | Agent | Uppgift |
|------|-------|---------|
| 3 | `log-cleaner-mcp` | Rensade och normaliserade build-loggar |
| 4 | `error-analyst-mcp` | Identifierade rotorsak och blast-radius |
| 5 | `llm-mcp (code-repairer)` | Genererade kodfixen |
| 6 | `notification-mcp` | Utvärderade fixkvalitet och skickade notiser |
"""

_VERDICT_EMOJI = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}
_VERDICT_LABEL = {
    "GREEN":  "GREEN — automatiskt applicerad",
    "YELLOW": "YELLOW — inväntar manuell granskning",
    "RED":    "RED — blockerad, manuell åtgärd krävs",
}


def _fmt_duration(elapsed_s: int) -> str:
    if elapsed_s <= 0:
        return "—"
    if elapsed_s < 60:
        return f"{elapsed_s}s"
    return f"{elapsed_s // 60}m {elapsed_s % 60}s"


def build_report(
    build_id: str,
    colour: str,
    confidence: float,
    elapsed_s: int,
    error_type: str,
    blast_radius: str,
    root_cause: str,
    affected_files: list[str],
    explanation: str,
) -> str:
    """Return the full markdown content for AUTO_HEAL_REPORT.md."""
    emoji   = _VERDICT_EMOJI.get(colour, "🔴")
    verdict = _VERDICT_LABEL.get(colour, colour)
    score   = round(confidence * 100)
    files   = "\n".join(f"- `{f}`" for f in affected_files) or "- _(inga filer rapporterade)_"
    ts      = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    return f"""\
# Auto-Heal Rapport

> Genererad automatiskt av **Auto-Healing AI DevOps Platform**
> Tidpunkt: {ts}

---

## Bygginformation

| Fält | Värde |
|------|-------|
| **Build ID** | `{build_id}` |
| **Verdict** | {emoji} {verdict} |
| **Konfidenspoäng** | {score}% |
| **Tid till fix** | {_fmt_duration(elapsed_s)} |

---

## Hittad bugg

| Fält | Värde |
|------|-------|
| **Feltyp** | `{error_type}` |
| **Blast-radius** | `{blast_radius}` |
| **Rotorsak** | {root_cause or "_(ej tillgänglig)_"} |

---

## Fixade filer

{files}

---

## Vad fixades

{explanation or "_(ingen förklaring tillgänglig)_"}

---

## Agentpipeline

{_AGENT_TABLE}

---

_Rapporten är en del av PR-commiten och speglar tillståndet vid fix-genereringen._
"""
