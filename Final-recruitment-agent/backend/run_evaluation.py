"""Run the Day 4 evaluation and write the report.

Usage (from backend/):
    python run_evaluation.py                  # rule-based mode (no model needed)
    python run_evaluation.py --mode ollama    # your local LLM (Ollama must be running)
    python run_evaluation.py --mode both      # both, side by side (the LLM part is skipped if Ollama is not ready)
    python run_evaluation.py --repeats 5      # repeat each batch run for steadier latency numbers

Writes outputs/evaluation/results.json and ../docs/EVALUATION_REPORT.md. Every number in the report comes from
this run; nothing in it is typed in by hand.
"""
import argparse
import asyncio
from pathlib import Path

from app.config import BACKEND_DIR, settings
from evaluation.report import render
from evaluation.runner import evaluate, save


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["mock", "ollama", "both"], default="mock")
    ap.add_argument("--repeats", type=int, default=3, help="batch runs per job in rule-based mode (default 3)")
    ap.add_argument("--report", default=str(BACKEND_DIR.parent / "docs" / "EVALUATION_REPORT.md"))
    args = ap.parse_args()

    print(f"Evaluating ({args.mode}) ... this can take a few minutes with a real model.")
    result = await evaluate(args.mode, args.repeats)
    save(result, settings.outputs_dir / "evaluation" / "results.json")
    report = Path(args.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render(result), encoding="utf-8")
    print(f"Report: {report}")
    if "aborted" in result:
        print("ABORTED:", result["aborted"])
    for name, m in result["modes"].items():
        s = m["single"]["classification"]
        print(f"[{name}] workflow success {m['workflow']['success_rate']:.0%} | mean NDCG@3 {m['batch_summary']['ndcg_mean']:.3f} "
              f"| single-CV accuracy {s['correct']}/{s['total']}")
    print("Error handling:", f"{result['error_handling_summary']['handled']}/{result['error_handling_summary']['total']}")
    for k, v in result["skipped"].items():
        print(f"[{k}] {v}")


if __name__ == "__main__":
    asyncio.run(main())
