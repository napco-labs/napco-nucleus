"""Multi-agent decomposition of verify_session.

Three sequential Claude calls:

  Stage 1 (Extract):  raw session content -> candidate requirements
                      (no dedup, no critique — generous).
  Stage 2 (Critic):   candidates + client histories + requirements_seen
                      -> final requirement list (deduped, scored,
                      kind-classified).
  Stage 3 (Drafter):  final list -> write_verification_docx +
                      draft_verification_email + remember_requirement.
                      Mechanical execution, no judgment.

Compared to the single-call `agent.py --task verify_session`:

  - Each stage has a single job + a focused prompt.
  - Bad reasoning is more catchable (you can read the Critic's input
    and output independently).
  - Model selection per stage is possible (Haiku for Extract / Sonnet
    for Critic / Opus for Draft) once tier-by-stage is configured.
  - Costs more in API calls but each call is shorter; net usually a
    wash or cheaper, especially with tiered models.

Usage:
    py -3 pipeline.py                          # run the pipeline
    py -3 pipeline.py --session <path>         # custom session doc
    py -3 pipeline.py --dry-run                # no email push / memory write
    py -3 pipeline.py --stage extract          # run only stage 1
    py -3 pipeline.py --stage extract,critique # stages 1 and 2 only
    py -3 pipeline.py --save-intermediates dir # write JSON between stages
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import anyio

# Windows cmd.exe defaults to cp1252; LLM output may include Unicode
# (e.g. ≥, em-dashes, smart quotes). Reconfigure stdout/err to UTF-8
# so streaming print() doesn't crash mid-stage.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, Exception):
        pass

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))

import memory  # noqa: E402
import napco_config as nucleus_config  # noqa: E402
from tools import _session_doc as session_doc  # noqa: E402


_PROMPT_DIR = _HERE / "prompts"
_DEFAULT_SESSION_PATH = session_doc.SESSION_PATH

_VALID_STAGES = ["extract", "critique", "draft"]

# Per-stage model selection — overridable via env. Defaults reflect
# the cost/quality trade-off: Haiku for cheap extraction, Sonnet for
# critique-grade reasoning, Opus for the final synthesis + tool use.
# Set the env var to an empty string to fall back to the CLI default.
_EXTRACT_MODEL = os.environ.get(
    "NUCLEUS_PIPELINE_EXTRACT_MODEL", "claude-haiku-4-5-20251001")
_CRITIQUE_MODEL = os.environ.get(
    "NUCLEUS_PIPELINE_CRITIQUE_MODEL", "claude-sonnet-4-6")
_DRAFT_MODEL = os.environ.get(
    "NUCLEUS_PIPELINE_DRAFT_MODEL", "claude-opus-4-7")

# Per-stage timeouts (seconds). Prevent a hung Whisper / SDK / IMAP
# from blocking the whole pipeline forever. Defaults are generous —
# tune via env if your sessions are unusually long.
_TIMEOUT_EXTRACT = int(os.environ.get("NUCLEUS_TIMEOUT_EXTRACT_S", "300"))
_TIMEOUT_CRITIQUE = int(os.environ.get("NUCLEUS_TIMEOUT_CRITIQUE_S", "300"))
_TIMEOUT_DRAFT = int(os.environ.get("NUCLEUS_TIMEOUT_DRAFT_S", "600"))


# ── Session-doc reading ───────────────────────────────────────────

def _read_session_text(session_path: Path) -> str:
    """Pull all paragraph text out of the session .docx so the
    Extractor can read it as a single string."""
    from docx import Document  # lazy
    doc = Document(str(session_path))
    out: list[str] = []
    for p in doc.paragraphs:
        t = p.text
        if t is not None:
            out.append(t)
    return "\n".join(out)


# ── Prompt loaders ────────────────────────────────────────────────

def _load_prompt(name: str) -> str:
    path = _PROMPT_DIR / f"pipeline_{name}.md"
    raw = path.read_text(encoding="utf-8")
    # Calibration feedback — injected only into stages that emit
    # confidence numbers (extract assigns tentative confidence; critic
    # produces the final confidence). draft is mechanical; skip.
    if name in ("extract", "critique"):
        try:
            advice = memory.calibration_advice(min_decisions=10)
        except Exception:
            advice = ""
        if advice:
            raw += "\n\n---\n\n" + advice
    return raw


# ── Claude SDK helpers ────────────────────────────────────────────

def _extract_text(msg) -> str:
    out: list[str] = []
    content = getattr(msg, "content", None)
    if isinstance(content, list):
        for block in content:
            t = getattr(block, "text", None)
            if isinstance(t, str):
                out.append(t)
    t = getattr(msg, "text", None)
    if isinstance(t, str):
        out.append(t)
    return "\n".join(out)


def _strip_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()


def _build_options(system_prompt: str, *, model: str | None,
                   mcp_servers: dict | None = None,
                   allowed_tools: list[str] | None = None):
    """Construct ClaudeAgentOptions defensively. If the installed SDK
    version doesn't accept a `model` kwarg, falls back silently to the
    CLI default and prints a one-line warning."""
    from claude_agent_sdk import ClaudeAgentOptions  # lazy

    options_kwargs: dict = {"system_prompt": system_prompt}
    if mcp_servers:
        options_kwargs["mcp_servers"] = mcp_servers
    if allowed_tools is not None:
        options_kwargs["allowed_tools"] = allowed_tools
    cli_path = nucleus_config.claude_cli_path()
    if cli_path:
        options_kwargs["cli_path"] = cli_path
    if model:
        options_kwargs["model"] = model

    try:
        return ClaudeAgentOptions(**options_kwargs)
    except TypeError as e:
        if model and "model" in str(e):
            print(f"[warn] SDK doesn't accept model={model!r} — "
                  f"falling back to CLI default.", file=sys.stderr)
            options_kwargs.pop("model", None)
            return ClaudeAgentOptions(**options_kwargs)
        raise


async def _claude_call(system_prompt: str, user_prompt: str, *,
                       model: str | None = None,
                       stage: str = "pipeline") -> str:
    """Single Claude call, no MCP tools. Returns concatenated text
    output. Used by stages 1 and 2."""
    from claude_agent_sdk import ClaudeSDKClient  # lazy
    from tools._cost import CallTelemetry  # lazy

    options = _build_options(system_prompt, model=model)
    if model:
        print(f"  (model: {model})")

    telem = CallTelemetry()
    chunks: list[str] = []
    async with ClaudeSDKClient(options=options) as client:
        await client.query(user_prompt)
        async for msg in client.receive_response():
            telem.observe(msg)
            t = _extract_text(msg)
            if t:
                chunks.append(t)
    telem.log(stage=stage, model=(model or "default"))
    cost = telem.cost(model or "default")
    totals = telem.totals()
    if totals["input_tokens"] or totals["output_tokens"]:
        print(f"  [{stage}] tokens in={totals['input_tokens']} "
              f"out={totals['output_tokens']}  est cost ${cost:.4f}")
    return "".join(chunks)


async def _claude_call_with_tools(system_prompt: str, user_prompt: str, *,
                                  model: str | None = None,
                                  stage: str = "pipeline") -> str:
    """Single Claude call WITH MCP tools wired up — used by stage 3."""
    from claude_agent_sdk import ClaudeSDKClient, create_sdk_mcp_server  # lazy
    from tools import ALL_TOOLS, TOOL_NAMES
    from tools._cost import CallTelemetry  # lazy

    server = create_sdk_mcp_server(
        name="napco-nucleus",
        version="0.1.0",
        tools=ALL_TOOLS,
    )
    allowed = [f"mcp__napco-nucleus__{n}" for n in TOOL_NAMES]
    allowed.extend(["WebSearch", "WebFetch"])

    options = _build_options(
        system_prompt, model=model,
        mcp_servers={"napco-nucleus": server},
        allowed_tools=allowed,
    )
    if model:
        print(f"  (model: {model})")

    telem = CallTelemetry()
    chunks: list[str] = []
    async with ClaudeSDKClient(options=options) as client:
        await client.query(user_prompt)
        async for msg in client.receive_response():
            telem.observe(msg)
            t = _extract_text(msg)
            if t:
                chunks.append(t)
                print(t, end="", flush=True)  # also live-stream to stdout
    telem.log(stage=stage, model=(model or "default"))
    cost = telem.cost(model or "default")
    totals = telem.totals()
    if totals["input_tokens"] or totals["output_tokens"]:
        print(f"\n  [{stage}] tokens in={totals['input_tokens']} "
              f"out={totals['output_tokens']}  est cost ${cost:.4f}")
    return "".join(chunks)


# ── Stage 1: Extract ──────────────────────────────────────────────

async def run_extract(session_text: str) -> list[dict]:
    print("\n" + "=" * 60)
    print("  STAGE 1 / EXTRACT")
    print("=" * 60)
    system = _load_prompt("extract")
    user = (
        "Full pull-session content follows. Extract every candidate "
        "client requirement per the spec.\n\n"
        "----- SESSION DOC -----\n\n"
        f"{session_text}\n\n"
        "----- END SESSION DOC -----\n"
    )
    with anyio.fail_after(_TIMEOUT_EXTRACT):
        raw = await _claude_call(system, user,
                                  model=_EXTRACT_MODEL or None,
                                  stage="extract")
    cleaned = _strip_fences(raw)
    try:
        candidates = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"Extractor returned non-JSON. err={e}. raw[:500]={cleaned[:500]!r}")
    if not isinstance(candidates, list):
        raise RuntimeError(
            f"Extractor returned non-list JSON: {type(candidates).__name__}")
    print(f"\n[extract] {len(candidates)} candidate(s)")
    for i, c in enumerate(candidates, 1):
        title = (c.get("tentative_title") or "?")[:80]
        client = c.get("client_name_guess") or "(no client)"
        print(f"  {i:2d}. {title}   [{client}]")
    return candidates


# ── Stage 2: Critique ─────────────────────────────────────────────

def _gather_critic_context(candidates: list[dict]) -> dict:
    """Pull client histories + open items + requirements_seen rows
    the Critic needs. Best-effort — failures don't block the stage."""
    clients = {(c.get("client_name_guess") or "").strip()
               for c in candidates}
    clients.discard("")
    histories: dict = {}
    open_items: dict = {}
    for cname in clients:
        try:
            histories[cname] = memory.get_client_history(cname, limit=15)
        except Exception as e:
            histories[cname] = {"error": str(e)}
        try:
            open_items[cname] = memory.open_items(
                cname, max_age_days=30, limit=50)
        except Exception as e:
            open_items[cname] = {"error": str(e)}

    # Pull a small batch of seen requirements per candidate for dedup
    # context. Cap per-candidate hits so the prompt doesn't bloat.
    seen_rows: list[dict] = []
    seen_titles: set[str] = set()
    for c in candidates:
        q = (c.get("tentative_title") or "").strip()
        if not q:
            continue
        try:
            hits = memory.search_requirements(q, limit=3)
        except Exception:
            continue
        for h in hits:
            t = (h.get("title") or "").strip().lower()
            if t and t not in seen_titles:
                seen_rows.append(h)
                seen_titles.add(t)
    return {
        "candidates": candidates,
        "client_histories": histories,
        "open_items": open_items,
        "requirements_seen": seen_rows,
    }


async def run_critique(candidates: list[dict]) -> list[dict]:
    print("\n" + "=" * 60)
    print("  STAGE 2 / CRITIQUE")
    print("=" * 60)
    if not candidates:
        print("[critique] no candidates — skipping LLM call")
        return []
    ctx = _gather_critic_context(candidates)
    open_total = sum(
        (len(v) if isinstance(v, list) else 0)
        for v in (ctx.get("open_items") or {}).values())
    print(f"[critique] context: "
          f"{len(ctx['candidates'])} candidates, "
          f"{len(ctx['client_histories'])} client(s) with history, "
          f"{open_total} open item(s) across those clients, "
          f"{len(ctx['requirements_seen'])} seen-rows for dedup")
    system = _load_prompt("critique")
    user = json.dumps(ctx, ensure_ascii=False, indent=2, default=str)
    with anyio.fail_after(_TIMEOUT_CRITIQUE):
        raw = await _claude_call(system, user,
                                  model=_CRITIQUE_MODEL or None,
                                  stage="critique")
    cleaned = _strip_fences(raw)
    try:
        finalists = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"Critic returned non-JSON. err={e}. raw[:500]={cleaned[:500]!r}")
    if not isinstance(finalists, list):
        raise RuntimeError(
            f"Critic returned non-list JSON: {type(finalists).__name__}")
    print(f"\n[critique] {len(finalists)} final requirement(s) "
          f"(was {len(candidates)} candidates)")
    for i, r in enumerate(finalists, 1):
        title = (r.get("title") or "?")[:70]
        conf = r.get("confidence")
        kind = r.get("kind") or "?"
        client = r.get("client_name") or "?"
        conf_s = f"{conf:.2f}" if isinstance(conf, (int, float)) else "?"
        print(f"  {i:2d}. {title}   [{client} | {kind} | conf={conf_s}]")
    return finalists


# ── Stage 3: Draft ────────────────────────────────────────────────

async def run_draft(finalists: list[dict], dry_run: bool) -> str:
    print("\n" + "=" * 60)
    print("  STAGE 3 / DRAFT")
    print("=" * 60)
    if not finalists:
        print("[draft] no finalists — nothing to write. Stopping.")
        return ""
    if dry_run:
        os.environ["NAPCO_NUCLEUS_DRY_RUN"] = "1"
    system = _load_prompt("draft")
    if dry_run:
        system += (
            "\n\n---\n\n"
            "**DRY-RUN MODE.** Skip the actual email IMAP push and "
            "skip remember_requirement DB writes. Simulate by printing "
            "what would have happened. Still write the verification "
            ".docx (we need it for inspection)."
        )
    user = (
        "Final requirement list (verbatim from Critic — do not modify):\n\n"
        + json.dumps(finalists, ensure_ascii=False, indent=2, default=str)
    )
    print(f"[draft] passing {len(finalists)} requirement(s) to Claude")
    with anyio.fail_after(_TIMEOUT_DRAFT):
        return await _claude_call_with_tools(system, user,
                                              model=_DRAFT_MODEL or None,
                                              stage="draft")


# ── Orchestrator ─────────────────────────────────────────────────

async def run_pipeline(
    session_path: Path,
    stages: list[str],
    dry_run: bool,
    save_dir: Path | None,
) -> dict:
    started = datetime.now()
    if not session_path.exists():
        raise RuntimeError(f"session doc not found: {session_path}")

    print(f"\nSession doc: {session_path}")
    print(f"Stages:      {', '.join(stages)}")
    if dry_run:
        print("Mode:        DRY-RUN (no email push / no memory writes)")
    if save_dir:
        save_dir.mkdir(parents=True, exist_ok=True)
        print(f"Save dir:    {save_dir}")

    session_text = _read_session_text(session_path)
    print(f"Session length: {len(session_text)} chars\n")

    state: dict = {"session_path": str(session_path),
                   "started_at": started.isoformat(timespec="seconds"),
                   "stages_run": []}

    candidates: list[dict] = []
    if "extract" in stages:
        candidates = await run_extract(session_text)
        state["candidates"] = candidates
        state["stages_run"].append("extract")
        if save_dir:
            (save_dir / "1_candidates.json").write_text(
                json.dumps(candidates, indent=2, ensure_ascii=False,
                           default=str),
                encoding="utf-8")

    finalists: list[dict] = []
    if "critique" in stages:
        finalists = await run_critique(candidates)
        state["finalists"] = finalists
        state["stages_run"].append("critique")
        if save_dir:
            (save_dir / "2_finalists.json").write_text(
                json.dumps(finalists, indent=2, ensure_ascii=False,
                           default=str),
                encoding="utf-8")

    draft_output = ""
    if "draft" in stages:
        draft_output = await run_draft(finalists, dry_run=dry_run)
        state["draft_output_tail"] = draft_output[-2000:]
        state["stages_run"].append("draft")
        if save_dir:
            (save_dir / "3_draft_output.txt").write_text(
                draft_output, encoding="utf-8")

    state["finished_at"] = datetime.now().isoformat(timespec="seconds")
    return state


def _parse_stages(raw: str) -> list[str]:
    parts = [s.strip().lower() for s in raw.split(",") if s.strip()]
    if not parts:
        return list(_VALID_STAGES)
    for p in parts:
        if p not in _VALID_STAGES:
            raise ValueError(
                f"unknown stage {p!r}; choose from {_VALID_STAGES}")
    # Preserve canonical ordering: extract -> critique -> draft.
    ordered = [s for s in _VALID_STAGES if s in parts]
    return ordered


# ── Main ─────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session", default=str(_DEFAULT_SESSION_PATH),
                    help=f"Path to the session .docx. Default: "
                         f"{_DEFAULT_SESSION_PATH}")
    ap.add_argument("--stage", default="extract,critique,draft",
                    help="Comma-separated list of stages to run. "
                         "Choices: extract, critique, draft. "
                         "Default: all three.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Stage 3 skips email IMAP push and memory writes.")
    ap.add_argument("--save-intermediates", default=None,
                    help="Directory to write 1_candidates.json, "
                         "2_finalists.json, 3_draft_output.txt for "
                         "inspection between runs.")
    args = ap.parse_args()

    try:
        stages = _parse_stages(args.stage)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    save_dir = Path(args.save_intermediates) if args.save_intermediates else None

    try:
        state = anyio.run(
            run_pipeline,
            Path(args.session),
            stages,
            args.dry_run,
            save_dir,
        )
    except Exception as e:
        print(f"\npipeline error: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    print("\n" + "=" * 60)
    print("  PIPELINE COMPLETE")
    print("=" * 60)
    print(f"Stages run: {', '.join(state['stages_run'])}")
    if "candidates" in state:
        print(f"Candidates: {len(state['candidates'])}")
    if "finalists" in state:
        print(f"Finalists:  {len(state['finalists'])}")
    return 0


def _main_with_lock() -> int:
    """Wrap main() in the same cross-process lock collect_central uses.
    Two pipeline.py invocations (or pipeline + collect_central) can't
    write to current.docx and verification artifacts simultaneously."""
    from tools._lock import file_lock  # lazy
    try:
        with file_lock("collect_central", block=False) as got:
            if not got:
                print("\n[lock] another collect_central / pipeline run is "
                      "in flight — aborting to avoid duplicate writes.",
                      file=sys.stderr)
                return 75  # EX_TEMPFAIL
            return main()
    except RuntimeError as e:
        print(f"\n[lock] {e}", file=sys.stderr)
        return 75


if __name__ == "__main__":
    sys.exit(_main_with_lock())
