"""Generate the single-CV evaluation set: 18 CV PDFs + reference_single_cv.json.

Usage (from backend/):  python scripts/generate_eval_cvs.py

HOW THE REFERENCE DECISIONS WERE MADE
  Every decision below was written together with its CV, BEFORE the decision logic of the
  system existed and before the system was ever run on these files. They follow a plain-language
  rubric (RUBRIC) that a recruiter could apply by reading the CV. They must not be edited after
  looking at the system's answers; if you disagree with a label, change it on purpose, say why,
  and re-run the evaluation.

HONEST LIMITS
  * The CVs are fictional and the labels were drafted by the AI assistant that built this project,
    not by an independent human recruiter. Please review them (rationale is next to each case).
  * 18 cases is a small set. The numbers it produces are an indication, not a general accuracy.
  * Layouts differ on purpose: most CVs follow the structured layout the rule-based parser knows
    (A), but some are written as prose (B), use other headings (C) or contain almost no information (D).
"""
import json
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

OUT = Path(__file__).resolve().parent.parent / "data" / "eval"
CVS = OUT / "single_cv"

RUBRIC = {
    "suitable": "The CV shows every required skill of the job (equivalent names count, e.g. JS = JavaScript, "
                "sklearn = scikit-learn) at a working level, and at least the minimum years of experience.",
    "not_suitable": "The CV clearly misses the core of the job: it lacks most of the required skills, "
                    "or its experience is far below the stated minimum.",
    "needs_review": "A human should decide: the CV is close but has a gap (one required skill missing or only "
                    "basic, experience a little below the minimum or not stated), or it contains too little "
                    "information to judge.",
}

# layout A: structured sections.  B: prose.  C: other headings.  D: almost empty.
CASES = [
    dict(id="S01", job="J1", label="suitable", layout="A", name="Laila Mansour", title="Backend Engineer",
         summary="Backend engineer with 5 years building APIs and data services.",
         skills="Python, FastAPI, SQL, Docker, PostgreSQL, Git", years="5",
         exp=["Backend Engineer, CloudPay (2021-2026): built FastAPI services on PostgreSQL and shipped them as Docker images.",
              "Software Engineer, DataWorks (2020-2021): wrote Python and SQL reports."],
         edu="B.Sc. Computer Science, Cairo University (2020)",
         why="All four required skills are used in the experience lines and 5 years exceed the 3-year minimum."),
    dict(id="S02", job="J1", label="not_suitable", layout="A", name="Tamer Zaki", title="Java Developer",
         summary="Java developer with 6 years in banking systems.",
         skills="Java, Spring Boot, SQL, Maven, Oracle", years="6",
         exp=["Senior Developer, BankSys (2020-2026): built Spring Boot services backed by Oracle and SQL.",
              "Developer, TechNile (2019-2020): maintained Java applications."],
         edu="B.Sc. Computer Engineering, Mansoura University (2019)",
         why="Only SQL out of Python, FastAPI, SQL and Docker. A Java specialist, not a Python API developer."),
    dict(id="S03", job="J2", label="suitable", layout="A", name="Dina Hossam", title="Frontend Developer",
         summary="Frontend developer with 4 years building React interfaces.",
         skills="React, JavaScript, TypeScript, CSS, Tailwind, Git", years="4",
         exp=["Frontend Developer, Shopwave (2022-2026): built a React and TypeScript dashboard styled with Tailwind CSS.",
              "Web Developer, PixelLab (2021-2022): implemented responsive JavaScript and CSS interfaces."],
         edu="B.Sc. Information Systems, Ain Shams University (2021)",
         why="Has React, JavaScript, TypeScript and CSS with real use, plus a preferred skill; 4 years vs 2 required."),
    dict(id="S04", job="J2", label="not_suitable", layout="A", name="Ziad Nabil", title="Junior Web Developer",
         summary="Junior web developer with 1 year of experience.",
         skills="HTML, CSS, JavaScript", years="1",
         exp=["Junior Web Developer, StartHub (2025-2026): built landing pages with HTML, CSS and JavaScript."],
         edu="B.Sc. Computer Science, Helwan University (2025)",
         why="React and TypeScript are the heart of a React developer job and are both missing; 1 year is below the 2 required."),
    dict(id="S05", job="J3", label="suitable", layout="A", name="Mona Adel", title="Machine Learning Engineer",
         summary="Machine learning engineer with 3 years training and deploying models.",
         skills="Python, SQL, Pandas, Machine Learning, scikit-learn, Docker", years="3",
         exp=["ML Engineer, Insightly (2023-2026): trained scikit-learn models for churn prediction using Python and SQL data.",
              "Data Analyst, RetailCo (2022-2023): analysed sales data with Pandas and SQL."],
         edu="M.Sc. Computer Science, Cairo University (2022)",
         why="Has all four required skills (Python, Machine Learning, scikit-learn, SQL); 3 years vs 2 required."),
    dict(id="S06", job="J3", label="not_suitable", layout="A", name="Hazem Fouad", title="BI Analyst",
         summary="Business intelligence analyst with 3 years of reporting experience.",
         skills="SQL, Excel, Power BI, Tableau", years="3",
         exp=["BI Analyst, FinServe (2023-2026): built Power BI and Tableau dashboards from SQL queries."],
         edu="B.Com. Accounting, Cairo University (2022)",
         why="Only SQL of the four required skills. No Python and no machine learning at all."),
    dict(id="S07", job="J1", label="needs_review", layout="A", name="Rania Salem", title="Backend Developer",
         summary="Backend developer with 4 years of Python experience.",
         skills="Python, Flask, SQL, Docker, PostgreSQL", years="4",
         exp=["Backend Developer, ShopCore (2022-2026): built Flask APIs with PostgreSQL and deployed them in Docker.",
              "Junior Developer, WebWorks (2021-2022): wrote Python scripts and SQL queries."],
         edu="B.Sc. Computer Science, Alexandria University (2021)",
         why="Strong Python API profile but FastAPI is missing (Flask is close). A recruiter has to decide."),
    dict(id="S08", job="J2", label="needs_review", layout="A", name="Sherif Ali", title="Junior Frontend Developer",
         summary="Frontend developer with 1 year of experience.",
         skills="React, JavaScript, TypeScript, CSS", years="1",
         exp=["Junior Frontend Developer, AppStudio (2025-2026): built React and TypeScript components with CSS."],
         edu="B.Sc. Computer Science, Tanta University (2025)",
         why="All four skills are present but 1 year is below the 2 required. Close enough that a human should decide."),
    dict(id="S09", job="J2", label="needs_review", layout="A", name="Yasmin Ehab", title="Frontend Developer",
         summary="Frontend developer with 3 years of experience.",
         skills="React (basics), JavaScript, TypeScript, CSS, Next.js", years="3",
         exp=["Frontend Developer, WebWorks (2023-2026): built JavaScript and TypeScript interfaces with CSS; started using React for small widgets."],
         edu="B.Sc. Information Systems, Ain Shams University (2023)",
         why="React is the main required skill and she only claims basics. Experience is fine. Needs a human look."),
    dict(id="S10", job="J1", label="needs_review", layout="D", name="Karim Nasr", title="Software Developer",
         summary="Looking for new opportunities.", skills="", years="", exp=[], edu="",
         why="Almost no information: no skills, no years, no education. Impossible to judge."),
    dict(id="S11", job="J3", label="needs_review", layout="A", name="Heba Magdy", title="Data Scientist",
         summary="Data scientist.", skills="Python, SQL, Machine Learning, scikit-learn", years="",
         exp=["Worked on machine learning projects using Python and scikit-learn."],
         edu="B.Sc. Statistics, Cairo University",
         why="Skills match, but nothing says how many years of experience she has, so the 2-year minimum cannot be checked."),
    dict(id="S12", job="J1", label="suitable", layout="B", name="Nadine Fawzy", title="Backend Engineer",
         prose=["I am a backend engineer with five years of professional experience.",
                "Day to day I build REST APIs in Python with FastAPI, design relational schemas and write SQL against "
                "PostgreSQL, and I package every service in Docker containers for deployment.",
                "Before that I spent a year maintaining internal tools in Python. I studied computer science at "
                "Cairo University and graduated in 2019."],
         why="Written as prose, but it clearly shows all four required skills and five years of experience."),
    dict(id="S13", job="J2", label="suitable", layout="C", name="Omar Gamal", title="Frontend Engineer",
         skills="React, JS, TS, CSS", years="3",
         exp=["Frontend Engineer, Nile Apps (2023-2026): built React interfaces in TS with CSS modules and plain JS utilities."],
         edu="B.Sc. Computer Engineering, Cairo University (2023)",
         why="Uses short names (JS, TS) and other headings, but has all four required skills and 3 years (2 required)."),
    dict(id="S14", job="J3", label="suitable", layout="A", name="Salma Reda", title="Data Scientist",
         summary="Data scientist with 3 years of experience.",
         skills="Python, ML, sklearn, Postgres, SQL", years="3",
         exp=["Data Scientist, MedAI (2023-2026): built ML classifiers with sklearn and queried Postgres with SQL in Python notebooks."],
         edu="B.Sc. Computer Science, Cairo University (2023)",
         why="ML means machine learning and sklearn means scikit-learn, so all four required skills are present; 3 years vs 2."),
    dict(id="S15", job="J1", label="not_suitable", layout="A", name="Adel Samir", title="Software Intern",
         summary="Recent graduate looking for a backend role.",
         skills="Python, FastAPI, SQL, Docker, PostgreSQL, AWS, Kubernetes, Terraform, Redis, Kafka", years="0.5",
         exp=["Intern, StartHub (2026): helped with a Python script."],
         edu="B.Sc. Computer Science, Helwan University (2026)",
         why="Lists ten skills but has six months of experience against a 3-year minimum, and the only evidence is one script."),
    dict(id="S16", job="J1", label="suitable", layout="A", name="Marwan Helal", title="Lead Backend Engineer",
         summary="Lead backend engineer with 8 years of experience.",
         skills="Python, FastAPI, SQL, Docker, AWS, Redis", years="8",
         exp=["Lead Backend Engineer, FinCore (2018-2026): designed FastAPI microservices in Python with SQL storage, deployed as Docker containers on AWS."],
         edu="B.Sc. Computer Engineering, Cairo University (2017)",
         why="Every required skill, a preferred one (AWS), and 8 years vs 3 required."),
    dict(id="S17", job="J3", label="not_suitable", layout="A", name="Farida Younis", title="UI Designer",
         summary="UI designer with 4 years of experience.",
         skills="Figma, Photoshop, HTML, CSS", years="4",
         exp=["UI Designer, PixelLab (2022-2026): designed interfaces in Figma and built static pages with HTML and CSS."],
         edu="B.A. Graphic Design, Helwan University (2021)",
         why="A designer. None of Python, machine learning, scikit-learn or SQL."),
    dict(id="S18", job="J1", label="not_suitable", layout="A", name="Walid Sami", title="DevOps Engineer",
         summary="DevOps engineer with 7 years of experience.",
         skills="Go, Kubernetes, Terraform, Docker, Linux", years="7",
         exp=["DevOps Engineer, CloudNine (2019-2026): ran Kubernetes clusters with Terraform and Docker; wrote Go tooling."],
         edu="B.Sc. Communications Engineering, Cairo University (2019)",
         why="Only Docker out of Python, FastAPI, SQL and Docker. An infrastructure engineer, not an API developer."),
]


def build(case: dict) -> Path:
    st = getSampleStyleSheet()
    path = CVS / f"{case['id'].lower()}_{case['name'].lower().replace(' ', '_')}.pdf"
    doc = SimpleDocTemplate(str(path), pagesize=A4, title=f"CV - {case['name']}")
    email = f"{case['name'].lower().replace(' ', '.')}@example.com"
    story = [Paragraph(case["name"], st["Title"]), Paragraph(f"Email: {email}", st["Normal"]), Spacer(1, 10)]
    layout = case["layout"]

    def block(heading, lines):
        story.extend([Spacer(1, 8), Paragraph(heading, st["Heading2"]),
                      *[Paragraph(line, st["Normal"]) for line in lines]])

    if layout == "B":
        story.append(Paragraph(case["title"], st["Heading2"]))
        story.extend(Paragraph(p, st["Normal"]) for p in case["prose"])
    elif layout == "D":
        story.append(Paragraph(case["title"], st["Heading2"]))
        story.append(Paragraph(case["summary"], st["Normal"]))
    elif layout == "C":
        story.append(Paragraph(case["title"], st["Heading2"]))
        block("Technical Skills", [case["skills"]])
        block(f"Work Experience ({case['years']} years)", ["- " + e for e in case["exp"]])
        block("Education", [case["edu"]])
    else:  # A: the same structure as the batch CVs
        story.append(Paragraph(case["title"], st["Heading2"]))
        story.append(Paragraph(case["summary"], st["Normal"]))
        block("Skills", [case["skills"]])
        block(f"Experience ({case['years']} years total)" if case["years"] else "Experience",
              ["- " + e for e in case["exp"]])
        block("Education", [case["edu"]])
    doc.build(story)
    return path


def main() -> None:
    CVS.mkdir(parents=True, exist_ok=True)
    for old in CVS.glob("*.pdf"):
        old.unlink()
    cases = []
    for c in CASES:
        path = build(c)
        cases.append({"id": c["id"], "file": path.name, "job_id": c["job"], "reference_decision": c["label"],
                      "layout": c["layout"], "rationale": c["why"]})
    ref = {
        "note": "Reference decisions written before the system was run on these files. See generate_eval_cvs.py.",
        "decisions": ["suitable", "not_suitable", "needs_review"],
        "rubric": RUBRIC,
        "cases": cases,
    }
    (OUT / "reference_single_cv.json").write_text(json.dumps(ref, indent=2, ensure_ascii=False), encoding="utf-8")
    counts = {d: sum(1 for c in cases if c["reference_decision"] == d) for d in ref["decisions"]}
    print(f"Generated {len(cases)} CVs in {CVS}")
    print("Reference decisions:", counts)


if __name__ == "__main__":
    main()
