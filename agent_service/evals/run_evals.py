"""Offline evaluation harness for the Spade agent and the filings retriever.

    python -m evals.run_evals                      # agent + retrieval, LLM judge on
    python -m evals.run_evals --suite agent --no-judge
    python -m evals.run_evals --only rag,guardrail  # filter by tag
    LLM_PROVIDER=fake python -m evals.run_evals    # plumbing check, no API key

Agent metrics (per case, then aggregated)
  route_accuracy      guardrail category == expected
  tool_recall         expected tools that were actually called
  tool_precision      called tools that were expected (only when expectations are non-empty)
  disclaimer_ok       advice-seeking answers carry the compliance disclaimer
  citation_ok         filing answers cite [S#] sources (skipped when no index is built)
  interrupt_ok        write actions pause for human approval
  groundedness/helpfulness   LLM-as-judge 1-5 against the actual tool outputs
  latency p50/p95, tokens per answer

Retrieval metrics
  hit@k, MRR@k        a top-k chunk is from the right ticker (+ section) and contains a keyword

Writes evals/results/<timestamp>.json and .md, and exits 1 if any gate in
THRESHOLDS fails - that's what the GitHub Actions job keys off.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))

from bullrun_agent.config import get_settings  # noqa: E402
from bullrun_agent.graph import build_graph  # noqa: E402
from bullrun_agent.graph.builder import _text_of  # noqa: E402
from bullrun_agent.graph.prompts import DISCLAIMER  # noqa: E402
from bullrun_agent.llm import get_embeddings, get_router_model, parse_json_loose  # noqa: E402
from bullrun_agent.rag import get_index  # noqa: E402
from bullrun_agent.tools import load_tools  # noqa: E402

THRESHOLDS = {
    "route_accuracy": 0.90,
    "tool_recall": 0.80,
    "disclaimer_ok": 1.00,
    "interrupt_ok": 1.00,
    "citation_ok": 0.80,
    "groundedness": 4.0,
    "retrieval_hit@k": 0.70,
}

JUDGE_PROMPT = """You are grading an AI investing assistant's answer.

USER QUESTION:
{question}

TOOL OUTPUTS THE ASSISTANT SAW (the only allowed source of specific numbers/facts):
{evidence}

ASSISTANT ANSWER:
{answer}

Score 1-5:
- groundedness: 5 = every specific number/claim is supported by the tool outputs or is general
  knowledge; 1 = invents figures or contradicts the tool outputs. If no tools were used, judge
  whether it avoided stating specific current figures it couldn't know.
- helpfulness: 5 = directly and clearly answers the question; 1 = evasive or wrong.
Return ONLY JSON: {{"groundedness": int, "helpfulness": int, "issues": "short note"}}"""


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


async def judge(question: str, evidence: str, answer: str) -> dict:
    model = get_router_model()
    msg = await model.ainvoke([SystemMessage("You are a strict, fair evaluator."),
                               HumanMessage(JUDGE_PROMPT.format(question=question, evidence=evidence[:12000],
                                                                answer=answer))])
    try:
        return parse_json_loose(_text_of(msg.content))
    except Exception:
        return {"groundedness": None, "helpfulness": None, "issues": "judge returned unparsable output"}


async def run_agent_case(graph, case: dict, use_judge: bool, has_index: bool) -> dict:
    cfg = {"configurable": {"thread_id": f"eval-{case['id']}-{time.time()}", "user_email": "eval@bullrun.ai",
                            "user_name": "Eval User"}, "tags": ["eval"], "metadata": {"case": case["id"]}}
    t0 = time.perf_counter()
    out = await graph.ainvoke({"messages": [HumanMessage(case["input"])]}, cfg)
    interrupted = "__interrupt__" in out
    latency = time.perf_counter() - t0

    msgs = out["messages"]
    called = [tc["name"] for m in msgs if isinstance(m, AIMessage) for tc in (m.tool_calls or [])]
    evidence = "\n".join(f"[{m.name}] {_text_of(m.content)[:2000]}" for m in msgs if isinstance(m, ToolMessage))
    answer = _text_of(msgs[-1].content) if isinstance(msgs[-1], AIMessage) else ""
    tokens = sum((m.usage_metadata or {}).get("total_tokens", 0) for m in msgs if isinstance(m, AIMessage))

    exp = set(case.get("expected_tools", []))
    r: dict = {"id": case["id"], "tags": case.get("tags", []), "input": case["input"],
               "category": out.get("category"), "tools_called": called, "latency_s": round(latency, 2),
               "tokens": tokens, "answer": answer[:1200]}
    r["route_ok"] = out.get("category") == case["category"]
    if exp:
        r["tool_recall"] = len(exp & set(called)) / len(exp)
    else:  # no tools expected: off-topic/unsafe turns must not call any
        r["tool_recall"] = 1.0 if not called or case["category"] == "finance" else 0.0
    if exp and called:
        r["tool_precision"] = len(set(called) & exp) / len(set(called))
    if case.get("min_tool_calls"):
        r["parallel_ok"] = len(called) >= case["min_tool_calls"]
    if case.get("require_disclaimer"):
        r["disclaimer_ok"] = DISCLAIMER.strip()[:40] in answer
    if case.get("expect_interrupt"):
        r["interrupt_ok"] = interrupted
    if case.get("require_citation"):
        r["citation_ok"] = bool(re.search(r"\[S\d+\]", answer)) if has_index else None
    if use_judge and case["category"] == "finance" and not interrupted and answer:
        r["judge"] = await judge(case["input"], evidence or "(no tools used)", answer)
    return r


def run_retrieval(cases: list[dict], k: int) -> dict:
    idx = get_index()
    if idx is None:
        return {"skipped": "no filings index (run python -m bullrun_agent.rag.ingest)"}
    emb = get_embeddings()
    rows, hits, rr = [], 0, 0.0
    for c in cases:
        if c["ticker"] not in idx.tickers:
            rows.append({"id": c["id"], "skipped": f"{c['ticker']} not indexed"})
            continue
        res = idx.search(c["query"], emb, k=k, ticker=c["ticker"])
        rank = None
        for i, h in enumerate(res):
            sec_ok = c.get("section") is None or h.meta.get("section") == c["section"]
            kw_ok = any(kw.lower() in h.text.lower() for kw in c["keywords"])
            if sec_ok and kw_ok:
                rank = i + 1
                break
        hits += rank is not None
        rr += 1 / rank if rank else 0
        rows.append({"id": c["id"], "rank": rank, "top_sections": [h.meta.get("section") for h in res[:3]]})
    n = sum(1 for r in rows if "skipped" not in r) or 1
    return {"k": k, "hit@k": round(hits / n, 3), "mrr": round(rr / n, 3), "evaluated": n, "cases": rows}


def is_rate_limit(msg: str) -> bool:
    return "429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower()


def retry_after(msg: str) -> float | None:
    m = re.search(r"retry in ([\d.]+)s", msg)
    return float(m.group(1)) + 2 if m else None


def aggregate(all_results: list[dict]) -> dict:
    results = [r for r in all_results if not r.get("error")]

    def mean(key, rows=results):
        vals = [r[key] for r in rows if r.get(key) is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    lat = sorted(r["latency_s"] for r in results) or [0.0]
    judged = [r["judge"] for r in results if r.get("judge") and r["judge"].get("groundedness")]
    agg = {
        "cases": len(all_results),
        "errored": len(all_results) - len(results),
        "route_accuracy": mean("route_ok"),
        "tool_recall": mean("tool_recall"),
        "tool_precision": mean("tool_precision"),
        "parallel_ok": mean("parallel_ok"),
        "disclaimer_ok": mean("disclaimer_ok"),
        "interrupt_ok": mean("interrupt_ok"),
        "citation_ok": mean("citation_ok"),
        "latency_p50_s": round(statistics.median(lat), 2) if lat else None,
        "latency_p95_s": round(lat[min(len(lat) - 1, int(0.95 * len(lat)))], 2) if lat else None,
        "avg_tokens": round(statistics.mean(r["tokens"] for r in results)) if results else None,
    }
    if judged:
        agg["groundedness"] = round(statistics.mean(j["groundedness"] for j in judged), 2)
        agg["helpfulness"] = round(statistics.mean(j["helpfulness"] for j in judged), 2)
    return agg


def gates(summary: dict) -> list[str]:
    failures = []
    if summary.get("agent", {}).get("errored"):
        failures.append(f"{summary['agent']['errored']} cases errored (see report)")
    flat = {**summary.get("agent", {}), **{f"retrieval_{k}": v for k, v in summary.get("retrieval", {}).items()}}
    for key, floor in THRESHOLDS.items():
        val = flat.get(key)
        if val is not None and val < floor:
            failures.append(f"{key}={val} < {floor}")
    return failures


def to_markdown(summary: dict, results: list[dict], failures: list[str]) -> str:
    s = get_settings()
    lines = [f"# Spade eval report ({summary['timestamp']})", "",
             f"Model: `{s.llm_provider}/{s.llm_model}` | judge: `{s.router_model or s.llm_model}`", "",
             "## Agent", "", "| metric | value | gate |", "|---|---|---|"]
    for k, v in summary.get("agent", {}).items():
        gate = THRESHOLDS.get(k)
        lines.append(f"| {k} | {v} | {'>= ' + str(gate) if gate else ''} |")
    ret = summary.get("retrieval", {})
    lines += ["", "## Retrieval", "", f"`{json.dumps({k: v for k, v in ret.items() if k != 'cases'})}`", "",
              "## Failing cases", ""]
    errored = [r for r in results if r.get("error")]
    bad = [r for r in results if not r.get("error") and (not r["route_ok"] or r["tool_recall"] < 1
           or r.get("disclaimer_ok") is False or r.get("interrupt_ok") is False or r.get("citation_ok") is False)]
    lines += [f"- **{r['id']}**: category={r['category']} tools={r['tools_called']}" for r in bad] or ["- none"]
    if errored:
        lines += ["", "## Errored cases", ""]
        lines += [f"- **{r['id']}**: {r['error'][:160]}" for r in errored]
    lines += ["", f"**Gates:** {'FAILED: ' + '; '.join(failures) if failures else 'all passed'}"]
    return "\n".join(lines)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", choices=["all", "agent", "retrieval"], default="all")
    ap.add_argument("--only", default=None, help="comma-separated tags to include")
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--pace", type=float, default=0.0, help="seconds to wait after each case (free tier: ~20)")
    args = ap.parse_args()

    s = get_settings()
    use_judge = not args.no_judge and s.llm_provider != "fake"
    summary: dict = {"timestamp": datetime.now().isoformat(timespec="seconds"),
                     "provider": s.llm_provider, "model": s.llm_model}
    results: list[dict] = []

    if args.suite in ("all", "agent"):
        cases = load_jsonl(ROOT / "datasets" / "agent_golden.jsonl")
        if args.only:
            want = set(args.only.split(","))
            cases = [c for c in cases if want & set(c.get("tags", []))]
        graph = build_graph(await load_tools(), InMemorySaver(), s)
        has_index = get_index() is not None
        sem = asyncio.Semaphore(args.concurrency)

        async def guarded(c):
            async with sem:
                for attempt in range(4):
                    try:
                        r = await run_agent_case(graph, c, use_judge, has_index)
                        await asyncio.sleep(args.pace)
                        return r
                    except Exception as e:  # one bad case shouldn't kill the run
                        msg = str(e)
                        if "per day" in msg.lower() or "PerDay" in msg:
                            err = "daily quota exhausted"
                            break
                        if not is_rate_limit(msg) or attempt == 3:
                            err = msg
                            break
                        wait = retry_after(msg) or 20 * (attempt + 1)
                        print(f"  {c['id']}: rate limited, retrying in {wait:.0f}s", flush=True)
                        await asyncio.sleep(wait)
                return {"id": c["id"], "error": err[:300], "route_ok": None, "tool_recall": None,
                        "latency_s": 0.0, "tokens": 0, "category": None, "tools_called": [], "tags": c.get("tags", [])}

        results = await asyncio.gather(*(guarded(c) for c in cases))
        summary["agent"] = aggregate(results)

    if args.suite in ("all", "retrieval"):
        summary["retrieval"] = run_retrieval(load_jsonl(ROOT / "datasets" / "retrieval_golden.jsonl"), args.k)

    failures = gates(summary)
    summary["gates_failed"] = failures
    out_dir = ROOT / "results"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (out_dir / f"{stamp}.json").write_text(json.dumps({"summary": summary, "cases": results}, indent=2, default=str))
    md = to_markdown(summary, results, failures)
    (out_dir / f"{stamp}.md").write_text(md)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(md + "\n")
    print(md)
    if s.llm_provider == "fake":
        # The scripted model is a keyword baseline (roughly the old regex router);
        # it checks the harness plumbing, so quality gates only apply to real models.
        print("\n(fake provider: quality gates reported but not enforced)")
        return 0
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
