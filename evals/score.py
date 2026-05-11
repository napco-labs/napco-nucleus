"""LLM-as-judge scorer for the NN eval harness.

Compares a list of *predicted* requirements (from `write_verification_docx`
JSON sidecar) against the *expected* requirements declared in a case's
`expected.json`. Asks Claude (via the local Claude CLI through the
agent SDK) to classify each predicted item as exact_match, partial_match,
or extra; and which expected items were missed.

Returns a structured score dict with precision, recall, F1, citation
correctness, and per-item details.

No memory writes, no MCP tools, no side effects — just one Claude call
per case.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import anyio

_HERE = Path(__file__).parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_ROOT))

import napco_config as nucleus_config  # noqa: E402

JUDGE_SYSTEM_PROMPT = """\
You are an evaluator scoring a requirement-identifier agent. The agent
reads a pull session containing emails, Teams chats, and call transcripts,
and extracts the distinct CLIENT requirements present. You score whether
the agent's predictions match a gold-standard list.

For each predicted requirement, classify it as exactly one of:
- "exact_match": semantically same as one expected item, allowing paraphrase
- "partial_match": covers part of an expected item but missing significant
  detail, OR conflates two expected items into one
- "extra": false positive — not in the expected list at all (process
  chatter, status update, or fabrication counted as a requirement)

For each expected item NOT matched by ANY predicted item, record it as
missed_recall.

You MUST respond with valid JSON exactly matching this schema, no prose,
no markdown fences:

{
  "predicted_classifications": [
    {
      "predicted_index": <int>,
      "kind": "exact_match" | "partial_match" | "extra",
      "matched_expected_index": <int or null>,
      "reasoning": "<one short sentence>"
    }
  ],
  "missed_expected_indexes": [<int>, ...]
}

Be strict. If a predicted item paraphrases an expected one cleanly,
that's exact_match. If it captures only some of the expected scope,
that's partial_match. Marketing emails, status updates, scheduling,
and internal team announcements counted as requirements are always
extras.
"""


def _build_user_prompt(expected: list[dict], predicted: list[dict]) -> str:
    exp_block = json.dumps(
        [
            {
                "index": i,
                "title": e.get("title"),
                "summary_keywords": e.get("summary_keywords") or [],
            }
            for i, e in enumerate(expected)
        ],
        indent=2,
        ensure_ascii=False,
    )
    pred_block = json.dumps(
        [
            {
                "index": i,
                "title": p.get("title"),
                "summary": p.get("summary"),
                "confidence": p.get("confidence"),
                "rationale": p.get("rationale"),
            }
            for i, p in enumerate(predicted)
        ],
        indent=2,
        ensure_ascii=False,
    )
    return (
        f"EXPECTED REQUIREMENTS (gold standard, {len(expected)} items):\n"
        f"{exp_block}\n\n"
        f"PREDICTED REQUIREMENTS (from the identifier, {len(predicted)} items):\n"
        f"{pred_block}\n\n"
        "Return the classification JSON now."
    )


def _extract_text(msg: Any) -> str:
    """Pull plain text out of an SDK response message."""
    out: list[str] = []
    content = getattr(msg, "content", None)
    if isinstance(content, list):
        for block in content:
            text = getattr(block, "text", None)
            if isinstance(text, str):
                out.append(text)
    text = getattr(msg, "text", None)
    if isinstance(text, str):
        out.append(text)
    return "\n".join(out)


def _strip_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()


async def _judge_via_claude(expected: list[dict],
                            predicted: list[dict]) -> dict:
    """One Claude call. Returns the parsed JSON classification."""
    from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

    options_kwargs: dict = {
        "system_prompt": JUDGE_SYSTEM_PROMPT,
    }
    cli_path = nucleus_config.claude_cli_path()
    if cli_path:
        options_kwargs["cli_path"] = cli_path

    options = ClaudeAgentOptions(**options_kwargs)

    user_prompt = _build_user_prompt(expected, predicted)
    chunks: list[str] = []
    async with ClaudeSDKClient(options=options) as client:
        await client.query(user_prompt)
        async for msg in client.receive_response():
            t = _extract_text(msg)
            if t:
                chunks.append(t)

    raw = _strip_fences("".join(chunks))
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"judge returned non-JSON. error={e}. raw[:500]={raw[:500]!r}")

    classifications = data.get("predicted_classifications") or []
    missed = data.get("missed_expected_indexes") or []
    if not isinstance(classifications, list) or not isinstance(missed, list):
        raise RuntimeError(
            f"judge JSON shape unexpected: {raw[:500]!r}")
    return {
        "predicted_classifications": classifications,
        "missed_expected_indexes": missed,
    }


def _check_citations(expected: list[dict],
                     predicted: list[dict],
                     classifications: list[dict]) -> dict:
    """For each exact/partial match, check the predicted Source IDs
    against the expected_source_id_pattern regex. Returns
    {checked, satisfied, ratio}."""
    checked = 0
    satisfied = 0
    for c in classifications:
        if c.get("kind") not in ("exact_match", "partial_match"):
            continue
        p_idx = c.get("predicted_index")
        e_idx = c.get("matched_expected_index")
        if not isinstance(p_idx, int) or not isinstance(e_idx, int):
            continue
        if not (0 <= p_idx < len(predicted) and 0 <= e_idx < len(expected)):
            continue
        pat = expected[e_idx].get("expected_source_id_pattern")
        if not pat:
            continue
        checked += 1
        srcs = predicted[p_idx].get("source_refs") or []
        if not isinstance(srcs, list):
            continue
        try:
            r = re.compile(pat)
        except re.error:
            continue
        if any(isinstance(s, str) and r.search(s) for s in srcs):
            satisfied += 1
    ratio = (satisfied / checked) if checked else None
    return {"checked": checked, "satisfied": satisfied, "ratio": ratio}


def _check_keywords(expected: list[dict],
                    predicted: list[dict],
                    classifications: list[dict]) -> dict:
    """For each match, check expected.summary_keywords appear (case-
    insensitive) in predicted.summary. Soft signal — Haiku may already
    have judged on substance; this surfaces glaring omissions."""
    checked = 0
    satisfied = 0
    for c in classifications:
        if c.get("kind") not in ("exact_match", "partial_match"):
            continue
        p_idx = c.get("predicted_index")
        e_idx = c.get("matched_expected_index")
        if not isinstance(p_idx, int) or not isinstance(e_idx, int):
            continue
        if not (0 <= p_idx < len(predicted) and 0 <= e_idx < len(expected)):
            continue
        kws = expected[e_idx].get("summary_keywords") or []
        if not kws:
            continue
        haystack = (predicted[p_idx].get("summary") or "").lower()
        for kw in kws:
            checked += 1
            if isinstance(kw, str) and kw.lower() in haystack:
                satisfied += 1
    ratio = (satisfied / checked) if checked else None
    return {"checked": checked, "satisfied": satisfied, "ratio": ratio}


def _check_confidence_floor(expected: list[dict],
                            predicted: list[dict],
                            classifications: list[dict]) -> dict:
    """For each matched item, check predicted confidence >= expected
    floor (when declared). Failing items are listed for review."""
    below: list[dict] = []
    for c in classifications:
        if c.get("kind") not in ("exact_match", "partial_match"):
            continue
        p_idx = c.get("predicted_index")
        e_idx = c.get("matched_expected_index")
        if not isinstance(p_idx, int) or not isinstance(e_idx, int):
            continue
        if not (0 <= p_idx < len(predicted) and 0 <= e_idx < len(expected)):
            continue
        floor = expected[e_idx].get("expected_min_confidence")
        if floor is None:
            continue
        conf = predicted[p_idx].get("confidence")
        try:
            cf = float(conf) if conf is not None else None
        except (TypeError, ValueError):
            cf = None
        if cf is None or cf < float(floor):
            below.append({
                "predicted_title": predicted[p_idx].get("title"),
                "predicted_confidence": cf,
                "expected_floor": floor,
            })
    return {"violations": below}


def _aggregate(expected: list[dict],
               predicted: list[dict],
               judge: dict,
               citations: dict,
               keywords: dict,
               confidence_floor: dict) -> dict:
    classifications = judge["predicted_classifications"]
    missed = judge["missed_expected_indexes"]

    n_pred = len(predicted)
    n_exp = len(expected)
    exact = sum(1 for c in classifications if c.get("kind") == "exact_match")
    partial = sum(1 for c in classifications if c.get("kind") == "partial_match")
    extra = sum(1 for c in classifications if c.get("kind") == "extra")
    matched = exact + 0.5 * partial  # partial counts as half-credit

    precision = (matched / n_pred) if n_pred else 1.0 if n_exp == 0 else 0.0
    recall = (matched / n_exp) if n_exp else 1.0
    f1 = (2 * precision * recall / (precision + recall)
          if (precision + recall) else 0.0)

    confidences = [
        p.get("confidence") for p in predicted
        if isinstance(p, dict) and p.get("confidence") is not None
    ]
    cleaned_conf: list[float] = []
    for c in confidences:
        try:
            cleaned_conf.append(float(c))
        except (TypeError, ValueError):
            continue
    mean_conf = (sum(cleaned_conf) / len(cleaned_conf)) if cleaned_conf else None

    return {
        "predicted_count": n_pred,
        "expected_count": n_exp,
        "exact_match_count": exact,
        "partial_match_count": partial,
        "extra_count": extra,
        "missed_recall_count": len(missed),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "citation_correctness": (round(citations["ratio"], 4)
                                 if citations["ratio"] is not None else None),
        "summary_keyword_coverage": (round(keywords["ratio"], 4)
                                     if keywords["ratio"] is not None else None),
        "mean_predicted_confidence": (round(mean_conf, 4)
                                       if mean_conf is not None else None),
        "confidence_floor_violations": confidence_floor["violations"],
        "classifications": classifications,
        "missed_expected_indexes": missed,
    }


def score_case(expected_doc: dict, predicted_doc: dict) -> dict:
    """Score one case. Sync wrapper around the async judge call."""
    expected = expected_doc.get("expected_requirements") or []
    predicted = predicted_doc.get("requirements") or []

    # Short-circuit: no predictions AND no expected = trivial pass.
    if not expected and not predicted:
        return {
            "predicted_count": 0,
            "expected_count": 0,
            "exact_match_count": 0,
            "partial_match_count": 0,
            "extra_count": 0,
            "missed_recall_count": 0,
            "precision": 1.0,
            "recall": 1.0,
            "f1": 1.0,
            "citation_correctness": None,
            "summary_keyword_coverage": None,
            "mean_predicted_confidence": None,
            "confidence_floor_violations": [],
            "classifications": [],
            "missed_expected_indexes": [],
            "note": "trivial pass (both lists empty)",
        }

    # Short-circuit: predictions but no expected = everything is extra.
    # No need to ask Claude.
    if not expected and predicted:
        classifications = [
            {"predicted_index": i, "kind": "extra",
             "matched_expected_index": None,
             "reasoning": "expected list is empty"}
            for i, _ in enumerate(predicted)
        ]
        return _aggregate(
            expected, predicted,
            {"predicted_classifications": classifications,
             "missed_expected_indexes": []},
            citations={"checked": 0, "satisfied": 0, "ratio": None},
            keywords={"checked": 0, "satisfied": 0, "ratio": None},
            confidence_floor={"violations": []},
        )

    # Short-circuit: expected but no predictions = recall-only failure.
    if expected and not predicted:
        return _aggregate(
            expected, predicted,
            {"predicted_classifications": [],
             "missed_expected_indexes": list(range(len(expected)))},
            citations={"checked": 0, "satisfied": 0, "ratio": None},
            keywords={"checked": 0, "satisfied": 0, "ratio": None},
            confidence_floor={"violations": []},
        )

    judge = anyio.run(_judge_via_claude, expected, predicted)
    classifications = judge["predicted_classifications"]
    citations = _check_citations(expected, predicted, classifications)
    keywords = _check_keywords(expected, predicted, classifications)
    confidence_floor = _check_confidence_floor(expected, predicted, classifications)
    return _aggregate(expected, predicted, judge,
                      citations, keywords, confidence_floor)
