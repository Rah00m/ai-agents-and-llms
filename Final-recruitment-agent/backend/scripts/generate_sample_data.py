"""Generate demo data: 8 CV PDFs, jobs.csv, github_mock.json and ground_truth.json.

Usage (from backend/):  python scripts/generate_sample_data.py
The candidates are fictional. ground_truth.json is the "human recruiter" ranking
that Day 4's evaluation compares the AI's ranking against.
"""
import csv
import json
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

DATA = Path(__file__).resolve().parent.parent / "data"
CVS = DATA / "cvs"

CANDIDATES = [
    dict(id="01", name="Sara Ahmed", email="sara.ahmed@example.com", gh="sara-ahmed-dev", years=4,
         title="Backend Engineer",
         summary="Backend engineer with 4 years building REST APIs and data pipelines for fintech products.",
         skills="Python, FastAPI, PostgreSQL, SQL, Docker, Redis, AWS, Git",
         experience=["Backend Engineer, PayLink (2022-2026): built FastAPI microservices handling 2M requests/day; cut query time 40% with PostgreSQL indexing.",
                     "Junior Developer, DataHub (2021-2022): wrote Python ETL jobs and Docker images for deployment."],
         education="B.Sc. Computer Engineering, Cairo University (2021)",
         repos=[("payments-api", "Python", 41, "FastAPI payments service"), ("etl-toolkit", "Python", 12, "ETL helpers"), ("dockerized-stack", "Shell", 5, "Compose templates")]),
    dict(id="02", name="Omar Hassan", email="omar.hassan@example.com", gh="omar-hassan-ui", years=3,
         title="Frontend Developer",
         summary="Frontend developer with 3 years crafting accessible React interfaces and design systems.",
         skills="React, TypeScript, JavaScript, HTML, CSS, Tailwind, Next.js, Vite, Jest",
         experience=["Frontend Developer, Shopwave (2023-2026): led migration of a dashboard to React + TypeScript; built a reusable component library.",
                     "Web Developer Intern, PixelLab (2022-2023): implemented responsive landing pages with Tailwind CSS."],
         education="B.Sc. Information Systems, Ain Shams University (2022)",
         repos=[("ui-kit", "TypeScript", 88, "React component library"), ("next-blog", "TypeScript", 17, "Blog with Next.js"), ("css-playground", "CSS", 6, "Animations")]),
    dict(id="03", name="Nour Khaled", email="nour.khaled@example.com", gh="nour-k-ml", years=3,
         title="Machine Learning Engineer",
         summary="ML engineer with 3 years training and deploying classification and NLP models.",
         skills="Python, Machine Learning, scikit-learn, PyTorch, SQL, Pandas, NLP, Docker",
         experience=["ML Engineer, Insightly (2023-2026): built a churn prediction model (AUC 0.91) and an NLP ticket classifier deployed with Docker.",
                     "Data Science Intern, MedAI (2022-2023): feature engineering with scikit-learn and SQL."],
         education="M.Sc. Computer Science (AI), Cairo University (2022)",
         repos=[("churn-model", "Python", 33, "Churn prediction with scikit-learn"), ("ticket-nlp", "Python", 21, "Transformer-based classifier"), ("ml-serving", "Python", 9, "Model serving in Docker")]),
    dict(id="04", name="Youssef Ali", email="youssef.ali@example.com", gh="youssef-ali-fs", years=5,
         title="Full-Stack Developer",
         summary="Full-stack developer with 5 years across React front ends and Python/Node back ends.",
         skills="React, JavaScript, TypeScript, Node.js, Python, Django, FastAPI, SQL, Docker, CSS",
         experience=["Full-Stack Developer, Tasklify (2021-2026): shipped a React + FastAPI SaaS product; introduced Docker-based CI.",
                     "Web Developer, Agency X (2020-2021): built client sites with React and Node.js."],
         education="B.Sc. Computer Science, Alexandria University (2020)",
         repos=[("tasklify-web", "TypeScript", 52, "React front end"), ("tasklify-api", "Python", 38, "FastAPI back end"), ("node-utils", "JavaScript", 7, "Utilities")]),
    dict(id="05", name="Mariam Tarek", email="mariam.tarek@example.com", gh="mariam-tarek-web", years=1,
         title="Junior Frontend Developer",
         summary="Junior developer with 1 year of experience building static and small React sites.",
         skills="HTML, CSS, JavaScript, React (basics), Git, Figma",
         experience=["Junior Web Developer, StartHub (2025-2026): built landing pages in HTML/CSS and small React widgets.",
                     "Freelance (2024-2025): portfolio sites for local businesses."],
         education="B.Sc. Computer Science, Helwan University (2024)",
         repos=[("portfolio", "JavaScript", 3, "Personal site"), ("react-todo", "JavaScript", 2, "Practice app")]),
    dict(id="06", name="Karim Mostafa", email="karim.mostafa@example.com", gh="karim-m-java", years=6,
         title="Java Backend Engineer",
         summary="Backend engineer with 6 years of Java and Spring experience in banking systems.",
         skills="Java, Spring Boot, SQL, Oracle, Docker, Kafka, Maven, Git",
         experience=["Senior Backend Engineer, BankSys (2020-2026): designed Spring Boot services and Kafka event flows.",
                     "Software Engineer, TechNile (2019-2020): maintained Oracle-backed Java applications."],
         education="B.Sc. Computer Engineering, Mansoura University (2019)",
         repos=[("spring-ledger", "Java", 27, "Ledger service"), ("kafka-demos", "Java", 10, "Event streaming samples")]),
    dict(id="07", name="Hana Samir", email="hana.samir@example.com", gh="hana-samir-data", years=2,
         title="Data Analyst",
         summary="Data analyst with 2 years turning business data into dashboards and insights.",
         skills="SQL, Python, Pandas, Power BI, Excel, Statistics, Matplotlib",
         experience=["Data Analyst, RetailCo (2024-2026): built Power BI dashboards and automated weekly SQL reports with Python.",
                     "Reporting Intern, FinServe (2023-2024): cleaned and analyzed sales data with Pandas."],
         education="B.Sc. Statistics, Cairo University (2023)",
         repos=[("sales-dashboard", "Python", 14, "Sales analytics"), ("sql-recipes", "SQL", 8, "Reusable queries")]),
    dict(id="08", name="Ahmed Fathy", email="ahmed.fathy@example.com", gh="ahmed-fathy-ops", years=5,
         title="DevOps Engineer",
         summary="DevOps engineer with 5 years automating cloud infrastructure and CI/CD pipelines.",
         skills="Docker, Kubernetes, AWS, Terraform, Python, Bash, CI/CD, Linux, SQL",
         experience=["DevOps Engineer, CloudNine (2021-2026): managed Kubernetes clusters on AWS; wrote Python automation scripts.",
                     "Systems Administrator, NetCo (2019-2021): Linux servers and monitoring."],
         education="B.Sc. Communications Engineering, Cairo University (2019)",
         repos=[("terraform-modules", "HCL", 30, "AWS modules"), ("k8s-tools", "Python", 19, "Cluster automation scripts")]),
]

JOBS = [
    dict(job_id="J1", title="Backend Python Developer", required_skills="Python;FastAPI;SQL;Docker",
         preferred_skills="PostgreSQL;AWS", min_years_experience=3,
         description="Build and maintain REST APIs and data services in Python."),
    dict(job_id="J2", title="Frontend React Developer", required_skills="React;JavaScript;TypeScript;CSS",
         preferred_skills="Tailwind;Next.js", min_years_experience=2,
         description="Build accessible, high-quality user interfaces with React."),
    dict(job_id="J3", title="Machine Learning Engineer", required_skills="Python;Machine Learning;scikit-learn;SQL",
         preferred_skills="PyTorch;Docker", min_years_experience=2,
         description="Train, evaluate and deploy machine learning models."),
]

# What a human recruiter decided (used by Day 4 evaluation).
GROUND_TRUTH = {
    "J1": {"ranking": ["C01", "C04", "C08", "C06", "C03"], "accepted": ["C01", "C04"]},
    "J2": {"ranking": ["C02", "C04", "C05"], "accepted": ["C02", "C04"]},
    "J3": {"ranking": ["C03", "C07", "C01"], "accepted": ["C03"]},
}


def build_pdf(c: dict) -> None:
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(CVS / f"cv_{c['id']}_{c['name'].lower().replace(' ', '_')}.pdf"),
                            pagesize=A4, title=f"CV - {c['name']}")
    story = [
        Paragraph(c["name"], styles["Title"]),
        Paragraph(f"Email: {c['email']}", styles["Normal"]),
        Paragraph(f"GitHub: {c['gh']}", styles["Normal"]),
        Spacer(1, 12),
        Paragraph(c["title"], styles["Heading2"]),
        Paragraph(c["summary"], styles["Normal"]),
        Spacer(1, 8),
        Paragraph("Skills", styles["Heading2"]),
        Paragraph(c["skills"], styles["Normal"]),
        Spacer(1, 8),
        Paragraph(f"Experience ({c['years']} years total)", styles["Heading2"]),
        *[Paragraph("- " + line, styles["Normal"]) for line in c["experience"]],
        Spacer(1, 8),
        Paragraph("Education", styles["Heading2"]),
        Paragraph(c["education"], styles["Normal"]),
    ]
    doc.build(story)


def main() -> None:
    CVS.mkdir(parents=True, exist_ok=True)
    for old in CVS.glob("*.pdf"):
        old.unlink()
    for c in CANDIDATES:
        build_pdf(c)

    with open(DATA / "jobs.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(JOBS[0].keys()))
        w.writeheader()
        w.writerows(JOBS)

    mock = {c["gh"]: {"repos": [{"name": n, "language": l, "stars": s, "description": d}
                                for n, l, s, d in c["repos"]]} for c in CANDIDATES}
    (DATA / "github_mock.json").write_text(json.dumps(mock, indent=2), encoding="utf-8")
    (DATA / "ground_truth.json").write_text(json.dumps(GROUND_TRUTH, indent=2), encoding="utf-8")
    print(f"Generated {len(CANDIDATES)} CVs, {len(JOBS)} jobs, github_mock.json, ground_truth.json in {DATA}")


if __name__ == "__main__":
    main()
