"""Turns the evaluation result dict into docs/EVALUATION_REPORT.md. Only numbers from the run are printed."""
from evaluation.metrics import LABELS

NICE = {"suitable": "Suitable", "needs_review": "Needs review", "not_suitable": "Not suitable", "error": "Error"}


def pct(v) -> str:
    return "n/a" if v is None else f"{v:.0%}"


def num(v, d=3) -> str:
    return "n/a" if v is None else f"{v:.{d}f}"


def sec(v) -> str:
    if v is None:
        return "n/a"
    return f"{v * 1000:.0f} ms" if v < 0.1 else f"{v:.2f} s"


def table(head: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    lines += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(lines)


def method(name: str, m: dict) -> str:
    return "rule-based parser (no AI model)" if name == "mock" else f"local LLM `{m['model']}` via Ollama"


def render(r: dict) -> str:
    o = [f"# Evaluation report", "",
         f"Generated {r['generated']} by `python run_evaluation.py`. Every number below was produced by that run.", ""]
    env = r["environment"]
    o += ["## 1. What was measured, and how far to trust it", "",
          f"- **Data:** {r['data']['candidates']} fictional candidates, {r['data']['jobs']} jobs, "
          f"{r['data']['single_cv_cases']} extra single-CV test cases. All synthetic, written for this project.",
          "- **References:** `data/ground_truth.json` (batch ranking) and `data/eval/reference_single_cv.json` "
          "(single-CV decisions) were drafted by the AI assistant that helped build the project, before the "
          "decision rules were run on them. They were **not** made by an independent human recruiter. Review them before relying on any number.",
          f"- **Environment:** Python {env['python']}, {env['platform']}; GitHub mode `{env['github_mode']}`.",
          "- **Methods evaluated:** " + (", ".join(f"`{n}` = {method(n, m)}" for n, m in r['modes'].items()) or "none") + ".",
          ]
    for k, v in r["skipped"].items():
        o.append(f"- **`{k}` mode: {v}** No LLM numbers are reported. Run `python run_evaluation.py --mode both` on a computer with Ollama.")
    if "ollama" not in r["modes"] and "ollama" not in r["skipped"]:
        o.append("- **LLM mode was not part of this run.** Every number below describes the rule-based parser, which is not an AI model. "
                 "Run `python run_evaluation.py --mode both` on a computer with Ollama to add the LLM and the comparison.")
    o += ["- With this little data a single candidate moves a metric by 10 to 30 points. Read the numbers as a smoke test, not as accuracy.", ""]
    if "aborted" in r:
        return "\n".join(o + ["## Stopped", "", r["aborted"], ""])

    # ---------------------------------------------------------------- ground truth
    o += ["## 2. Ground truth validation and the meaning of \"suitable\"", ""]
    rows = []
    for job_id, v in r["ground_truth"].items():
        rows.append([job_id, "valid" if v["ok"] else "**INVALID**", " > ".join(v["ranking"]), ", ".join(v["accepted"]),
                     "; ".join(v["errors"] + v["warnings"]) or "none"])
    o += [table(["Job", "Status", "Reference ranking", "Accepted (suitable)", "Problems / warnings"], rows), ""]
    o += ["Definition used for each job (and checked against the raw CV text, independent of the Skill Extractor):", ""]
    o += [f"- {v['definition']}" for v in r["ground_truth"].values()]
    o += ["", "Checks: every job has an entry; ids exist; no duplicates; accepted candidates are the top of the ranking; "
          "accepted candidates mention every required skill and state enough years; nobody who meets the definition is left out of `accepted`.", ""]

    # ---------------------------------------------------------------- per mode
    for name, m in r["modes"].items():
        o += [f"## 3. Batch results, {method(name, m)}", ""]
        rows = []
        for job_id, b in m["batch"].items():
            if "ndcg" not in b:
                rows.append([job_id, "run failed", "", "", "", "", "", "; ".join(b.get("run_errors", []))])
                continue
            rows.append([f"{job_id} {b['title']}", " > ".join(b["system_ranking"][:5]), " > ".join(b["reference_ranking"]),
                         num(b["ndcg"]["@3"]), *(pct(b["precision"][f"@{k}"]) for k in (1, 2, 3)),
                         f"{b['candidates_failed']} failed, {b['candidates_needs_review']} needs review"])
        o += [table(["Job", "System top 5", "Reference", "NDCG@3", "P@1", "P@2", "P@3", "Not ranked"], rows), "",
              f"Mean over jobs: NDCG@3 = {num(m['batch_summary']['ndcg_mean'])}, "
              + ", ".join(f"Precision{k} = {pct(v)}" for k, v in m['batch_summary']['precision_mean'].items()) + ".", "",
              "How to read: NDCG@3 is 1.0 when the system's top 3 equal the reference's top 3 in the same order. Reference "
              "gains are n, n-1, ..., 1 by reference position; candidates outside the reference ranking get 0. Precision@K = suitable "
              "candidates in the system's top K divided by K (always K, so a job with only 1 suitable candidate cannot exceed 1/K at K=3).", ""]
        scores = []
        for job_id, b in m["batch"].items():
            if "scores" in b:
                scores.append([job_id, ", ".join(f"{c} {s:g}" for c, s in sorted(b["scores"].items(), key=lambda x: -x[1]))])
        o += ["Scores of all 8 candidates per job (last run):", "", table(["Job", "Candidate score"], scores), ""]

        w = m["workflow"]
        o += [f"### Workflow metrics ({name})", "",
              table(["Metric", "Value", "Meaning"],
                    [["Workflow success rate", f"{w['succeeded']}/{w['runs']} = {pct(w['success_rate'])}",
                      "runs where every stage finished (retrieval, extraction, matching, QA, ranking, report)"],
                     ["Output validity (batch)", f"{m['validity']['valid']}/{m['validity']['outputs']}",
                      "results that re-validate against the Pydantic schema, with unique ids, ranks 1..n and scores in 0-100"],
                     ["Output validity (single CV)", f"{m['single']['validity']['valid']}/{m['single']['validity']['outputs']}",
                      "same check plus a known decision label and an explanation"],
                     ["Report = dashboard data", f"{m['csv_consistency']['consistent']}/{m['csv_consistency']['reports']}",
                      "CSV reports whose rows, ranks and scores equal the saved results the dashboard shows"]]), ""]
        lat = [[f"Batch {j} ({b['latency']['n']} runs)", sec(b["latency"]["mean"]), sec(b["latency"]["median"]), sec(b["latency"]["max"])]
               for j, b in m["batch"].items()]
        sl = m["single"]["latency"]
        lat.append([f"Single CV ({sl['n']} CVs)", sec(sl["mean"]), sec(sl["median"]), sec(sl["max"])])
        o += ["Latency (wall-clock, includes reading the PDFs):", "", table(["Operation", "Mean", "Median", "Max"], lat), ""]
        if name == "mock":
            o += ["Rule-based latency is tiny because no model is involved. It says nothing about how long a local LLM takes.", ""]
        if "llm_calls" in m:
            c = m["llm_calls"]
            o += [f"LLM answers: {c['calls']} requests, {c['valid_first_try']} valid on the first try, {c['repaired']} valid after a repair request, "
                  f"{c['failed']} failed. (This is the LLM's own JSON validity.)", ""]

        # ---------------------------------------------------------------- single CV
        s = m["single"]
        cl = s["classification"]
        o += [f"## 4. Single-CV decisions vs reference, {method(name, m)}", "",
              f"Agreement: **{cl['correct']}/{cl['total']} = {pct(cl['accuracy'])}**, macro-F1 {num(cl['macro_f1'])}. "
              f"False accepts (reference not suitable, system suitable): {cl['false_accepts']}. "
              f"False rejects (reference suitable, system not suitable): {cl['false_rejects']}.", ""]
        head = ["Reference \\ System"] + [NICE[c] for c in cl["columns"]]
        o += [table(head, [[NICE[l]] + [cl["matrix"][l][c] for c in cl["columns"]] for l in LABELS]), ""]
        o += [table(["Class", "Precision", "Recall", "F1", "Support"],
                    [[NICE[l], pct(v["precision"]), pct(v["recall"]), num(v["f1"]), v["support"]] for l, v in cl["per_class"].items()]), ""]
        o += ["Precision = of the CVs the system put in this class, how many the reference also put there. "
              "Recall = of the CVs the reference put in this class, how many the system found.", ""]
        o += ["By CV layout (A = structured like the batch CVs, B = prose, C = other headings and short skill names, D = almost empty): "
              + ", ".join(f"{k}: {v['agree']}/{v['total']}" for k, v in s["by_layout"].items()) + ".", ""]
        o += ["### Every case", "", table(["Case", "Job", "Reference", "System", "Score", "Why the system said so"],
              [[c["id"], c["job_id"], NICE[c["reference"]], ("✅ " if c["agree"] else "❌ ") + NICE[c["system"]],
                c.get("score", "-"), c.get("summary", c.get("error", ""))] for c in s["cases"]]), ""]
        diffs = [c for c in s["cases"] if not c["agree"]]
        if diffs:
            o += ["### Disagreements, one by one", ""]
            for c in diffs:
                o += [f"- **{c['id']}** ({c['job_id']}, layout {c['layout']}): reference *{NICE[c['reference']]}*, system *{NICE[c['system']]}*. "
                      f"Reference reasoning: {c['rationale']} System: {c.get('summary', c.get('error'))} "
                      f"Years read: {c.get('years')}; QA: {c.get('qa')}."]
            o.append("")

    # ---------------------------------------------------------------- comparison
    if "mock" in r["modes"] and "ollama" in r["modes"]:
        a, b = r["modes"]["mock"], r["modes"]["ollama"]
        o += ["## 5. Rule-based vs local LLM", "",
              table(["Metric", "Rule-based", f"LLM ({b['model']})"],
                    [["Mean NDCG@3", num(a["batch_summary"]["ndcg_mean"]), num(b["batch_summary"]["ndcg_mean"])],
                     ["Single-CV agreement", pct(a["single"]["classification"]["accuracy"]), pct(b["single"]["classification"]["accuracy"])],
                     ["Workflow success rate", pct(a["workflow"]["success_rate"]), pct(b["workflow"]["success_rate"])],
                     ["Single-CV mean latency", sec(a["single"]["latency"]["mean"]), sec(b["single"]["latency"]["mean"])]]), ""]
        diff = [(x, y) for x, y in zip(a["single"]["cases"], b["single"]["cases"]) if x["system"] != y["system"]]
        o += ["Cases where the two methods decided differently: " + (", ".join(f"{x['id']} ({NICE[x['system']]} vs {NICE[y['system']]}, reference {NICE[x['reference']]})" for x, y in diff) or "none") + ".", ""]
    else:
        o += ["## 5. Rule-based vs local LLM", "", "Not available in this run (see section 1).", ""]

    # ---------------------------------------------------------------- error handling
    eh = r["error_handling"]
    es = r["error_handling_summary"]
    o += ["## 6. Error handling", "",
          f"**Error handling rate: {es['handled']}/{es['total']} = {pct(es['rate'])}.** A scenario is *handled* when the system gives a clear, "
          "specific error (or finishes the run without the bad item) instead of crashing, hanging or answering from nothing. "
          "LLM failures were produced by a fake Ollama server, so they test the reaction, not how often a real model fails.", "",
          table(["Group", "Scenario", "Expected", "Handled", "Observed"],
                [[e["group"], e["name"], e["expected"], "✅" if e["handled"] else "❌", e["observed"].replace("|", "/").replace("\n", " ")[:140]] for e in eh]), ""]
    o += ["## 7. Related documents", "", "- `docs/BUGS_AND_FIXES.md`: problems found and how they were fixed", "- `docs/LIMITATIONS.md`: what these numbers do not show", ""]
    return "\n".join(o)
