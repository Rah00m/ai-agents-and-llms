"""Skill-name normalisation shared by the Extractor, Matcher and QA agents.

"sklearn", "scikit-learn" and "Scikit Learn" are the same skill; "React (basics)" is the
skill React at a basic level. Keeping this in one place makes matching consistent.
"""
import re

# canonical name -> aliases (all lower-case)
ALIASES: dict[str, list[str]] = {
    "scikit-learn": ["sklearn", "scikit learn"],
    "javascript": ["js", "ecmascript"],
    "typescript": ["ts"],
    "machine learning": ["ml"],
    "postgresql": ["postgres"],
    "node.js": ["nodejs", "node js", "node"],
    "ci/cd": ["cicd", "ci cd", "continuous integration"],
    "react": ["reactjs", "react.js"],
    "next.js": ["nextjs", "next js"],
    "tailwind": ["tailwind css", "tailwindcss"],
    "kubernetes": ["k8s"],
    "natural language processing": ["nlp"],
    "aws": ["amazon web services"],
    "power bi": ["powerbi"],
    "fastapi": ["fast api"],
    "spring boot": ["springboot"],
}
_ALIAS_TO_CANON = {a: canon for canon, aliases in ALIASES.items() for a in aliases}
_LEVEL_WORDS = {"basic": ("basic", "basics", "beginner", "familiar", "learning", "entry")}
_PAREN = re.compile(r"\(([^)]*)\)")


def key(skill: str) -> str:
    """Canonical comparison key: lower-case, no level qualifier, aliases resolved."""
    s = _PAREN.sub("", skill).strip().lower()
    s = re.sub(r"\s+", " ", s)
    return _ALIAS_TO_CANON.get(s, s)


def level(skill: str) -> str:
    """'basic' if the skill carries a qualifier such as '(basics)', otherwise 'standard'."""
    m = _PAREN.search(skill)
    if m and any(w in m.group(1).lower() for w in _LEVEL_WORDS["basic"]):
        return "basic"
    return "standard"


def search_terms(skill: str) -> list[str]:
    """All spellings to look for when checking whether a CV mentions a skill."""
    k = key(skill)
    terms = {k, *ALIASES.get(k, [])}
    return sorted(terms, key=len, reverse=True)


def mentioned_in(skill: str, text: str) -> bool:
    """Does `text` mention the skill (whole-word, case-insensitive, alias-aware)?"""
    low = text.lower()
    for term in search_terms(skill):
        # \b does not work around symbols like "." or "+", so use look-arounds
        if re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", low):
            return True
    return False
