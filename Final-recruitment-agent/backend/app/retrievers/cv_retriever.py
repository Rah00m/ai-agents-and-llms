"""Retriever #1: read candidate CVs from PDF files."""
import asyncio
import re
from pathlib import Path
from io import BytesIO

from app.config import settings
from pypdf import PdfReader

from app.models import CandidateCV

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
GITHUB_RE = re.compile(r"github(?:\.com/|:\s*)([A-Za-z0-9][A-Za-z0-9-]{0,38})", re.I)

class CvError(ValueError):
    """A user-facing error while reading a single uploaded CV."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def parse_cv_bytes(data: bytes, filename: str) -> CandidateCV:
    """Parse one uploaded PDF without changing the batch retriever."""

    if not filename.lower().endswith(".pdf"):
        raise CvError("unsupported_type", "Please upload a PDF file.")

    if not data:
        raise CvError("empty_file", "The uploaded file is empty.")

    max_bytes = int(settings.max_upload_mb * 1024 * 1024)
    if len(data) > max_bytes:
        raise CvError(
            "too_large",
            f"The uploaded file exceeds the {settings.max_upload_mb} MB limit.",
        )

    try:
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted:
            raise CvError(
                "invalid_pdf",
                "The PDF is password-protected and cannot be read.",
            )

        text = "\n".join(
            (page.extract_text() or "") for page in reader.pages
        ).strip()

    except CvError:
        raise
    except Exception as exc:
        raise CvError(
            "invalid_pdf",
            "The uploaded file is not a valid readable PDF.",
        ) from exc

    if not text:
        raise CvError(
            "no_extractable_text",
            "The PDF contains no extractable text. It may be a scanned document.",
        )

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    email = EMAIL_RE.search(text)
    gh = GITHUB_RE.search(text)

    return CandidateCV(
        candidate_id="UPLOAD",
        name=lines[0],
        email=email.group(0) if email else None,
        github_username=gh.group(1) if gh else None,
        raw_text=text,
        source_file=filename,
    )


def _read_pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages).strip()


def _parse_cv(path: Path) -> CandidateCV:
    text = _read_pdf_text(path)
    if not text:
        raise ValueError("no extractable text (scanned PDF?)")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    email = EMAIL_RE.search(text)
    gh = GITHUB_RE.search(text)
    # filename like cv_01_sara_ahmed.pdf -> candidate id "C01"
    m = re.match(r"cv_(\d+)", path.stem)
    cid = f"C{m.group(1)}" if m else path.stem
    return CandidateCV(
        candidate_id=cid,
        name=lines[0],
        email=email.group(0) if email else None,
        github_username=gh.group(1) if gh else None,
        raw_text=text,
        source_file=path.name,
    )


async def retrieve_cvs(cv_dir: Path) -> tuple[list[CandidateCV], list[str]]:
    """Parse every PDF in cv_dir concurrently. Bad files are reported, not fatal."""
    files = sorted(cv_dir.glob("*.pdf"))
    results = await asyncio.gather(
        *(asyncio.to_thread(_parse_cv, f) for f in files), return_exceptions=True
    )
    cvs, errors = [], []
    for f, res in zip(files, results):
        if isinstance(res, Exception):
            errors.append(f"CV {f.name}: {res}")
        else:
            cvs.append(res)
    if not files:
        errors.append(f"No PDF files found in {cv_dir}")
    return cvs, errors
