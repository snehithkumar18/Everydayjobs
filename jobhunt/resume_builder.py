"""Resume Builder: Dynamically tailors and compiles a 1-page Overleaf LaTeX resume.

For each high-scoring job:
1. Analyzes the target Job Description.
2. Selects the top 3 most relevant projects from master_portfolio.json.
3. Reorders technical skills to highlight matching keywords.
4. Generates a tailored Summary and JD-aligned bullet points (strictly grounded in master facts).
5. Renders the LaTeX template and compiles to PDF.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .fetch import Job
from .llm import parse_json
from .providers import Provider, resolve

ROOT = Path(__file__).resolve().parent.parent
MASTER_PORTFOLIO_PATH = ROOT / "master_portfolio.json"
TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "resume_template.tex"
OUT_RESUMES_DIR = ROOT / "out" / "resumes"


def _load_master_portfolio() -> dict[str, Any]:
    if not MASTER_PORTFOLIO_PATH.exists():
        raise FileNotFoundError(f"Master portfolio not found at {MASTER_PORTFOLIO_PATH}")
    return json.loads(MASTER_PORTFOLIO_PATH.read_text(encoding="utf-8"))


def _escape_latex(text: str) -> str:
    """Escapes special LaTeX characters while preserving intended LaTeX markup like \\textbf{}."""
    # Don't escape if text contains backslashes indicating LaTeX commands
    if "\\" in text:
        return text
    # Standard LaTeX escaping
    chars = {
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    pattern = re.compile("|".join(re.escape(k) for k in chars.keys()))
    return pattern.sub(lambda m: chars[m.group(0)], text)


RESUME_TAILOR_SYSTEM = """You are an expert technical resume architect.
Your task is to select and tailor a strict 1-page software engineering resume for a candidate applying to a specific Job Description.

Hard rules:
1. Select EXACTLY 3 most relevant projects from the candidate's master portfolio that best demonstrate skills for this specific JD.
2. Never invent experience, companies, or tools. Use ONLY authentic facts, metrics, and technologies from the master portfolio.
3. Tailor the Summary (2-3 sentences, 40-55 words) to directly align with the target role and company.
4. Optimize the 3 project bullet points to highlight matching technologies and metrics.
5. Highlight key technologies using Markdown **bold** (e.g. **Python**, **FastAPI**). Do NOT write raw LaTeX backslashes in JSON strings.

Return ONLY a JSON object:
{
  "summary": str,
  "skills": {
    "languages": str,
    "cs": str,
    "backend": str,
    "frontend": str,
    "databases": str,
    "engineering": str,
    "aiml": str
  },
  "selected_project_ids": ["proj_id1", "proj_id2", "proj_id3"],
  "projects": [
    {
      "id": str,
      "bullets": [str, str, str]
    },
    {
      "id": str,
      "bullets": [str, str, str]
    },
    {
      "id": str,
      "bullets": [str, str, str]
    }
  ]
}"""


def tailor_resume_data(job: Job, portfolio: dict, provider: Provider, model: str) -> dict[str, Any]:
    """Uses LLM to select top 3 projects and generate tailored resume text."""
    projects_summary = {
        pid: {
            "name": p["name"],
            "subtitle": p.get("subtitle", ""),
            "tech_stack": p["tech_stack"],
            "domain_tags": p.get("domain_tags", []),
            "metrics": p.get("metrics", {}),
            "bullet_variants": p.get("bullet_variants", {}),
        }
        for pid, p in portfolio.get("projects", {}).items()
    }

    user_prompt = (
        f"CANDIDATE NAME: {portfolio['personal_info']['name']}\n"
        f"AVAILABLE PROJECTS:\n{json.dumps(projects_summary, ensure_ascii=False, indent=2)}\n\n"
        f"TARGET JOB:\n"
        f"Title: {job.title}\n"
        f"Company: {job.company}\n"
        f"Location: {job.location}\n"
        f"Job Description Excerpt:\n{job.description[:2500]}"
    )

    max_t = 4000 if provider and provider.name == "gemini" else 2200
    raw = provider.complete(
        model=model,
        system=RESUME_TAILOR_SYSTEM,
        user=user_prompt,
        max_tokens=max_t,
        json_mode=True,
    )

    data = parse_json(raw)
    if not isinstance(data, dict):
        raise ValueError("Resume tailoring did not return a valid JSON object")
    return data


def render_latex(tailored: dict[str, Any], portfolio: dict[str, Any]) -> str:
    """Renders the LaTeX source code using tailored data and the template."""
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    
    # 1. Summary
    summary = tailored.get("summary") or (
        "Software Engineer with hands-on experience building full-stack applications, "
        "backend services, and AI systems with strong foundations in Data Structures, "
        "Algorithms, and distributed architectures."
    )
    
    # 2. Skills
    skills = tailored.get("skills", {})
    skills_languages = skills.get("languages", "Java, Python, JavaScript, TypeScript, SQL, C++")
    skills_cs = skills.get("cs", "Data Structures & Algorithms, OOP, DBMS, Operating Systems, Computer Networks, SDLC")
    skills_backend = skills.get("backend", "Node.js, Express.js, FastAPI, Flask, REST APIs, WebSockets")
    skills_frontend = skills.get("frontend", "React, TypeScript, JavaScript, HTML5, CSS3, Tailwind CSS")
    skills_databases = skills.get("databases", "PostgreSQL, MySQL, Supabase, Redis")
    skills_engineering = skills.get("engineering", "Git, GitHub, Docker, Linux, GitHub Actions, Pytest, Debugging")
    skills_aiml = skills.get("aiml", "PyTorch, OpenCV, YOLOv8, LLMs, Generative AI, RAG, Hugging Face")

    # 3. Experience Bullets
    exp_bullets = portfolio.get("experience", [{}])[0].get("bullets", [])

    # 4. Selected Projects (Top 3)
    selected_pids = tailored.get("selected_project_ids") or ["qrave", "snehith_gpt", "ai_crop_doctor"]
    selected_pids = selected_pids[:3]

    # Map project details
    tailored_projects_map = {p["id"]: p for p in tailored.get("projects", []) if isinstance(p, dict)}
    
    rendered_projects = []
    for pid in selected_pids:
        master_proj = portfolio.get("projects", {}).get(pid)
        if not master_proj:
            continue
        
        # Get tailored bullets or fallback to first variant
        t_proj = tailored_projects_map.get(pid, {})
        bullets = t_proj.get("bullets")
        if not bullets or len(bullets) < 2:
            variants = master_proj.get("bullet_variants", {})
            first_variant = next(iter(variants.values())) if variants else []
            bullets = first_variant[:3]

        proj_entry = {
            "name": master_proj["name"],
            "subtitle": master_proj.get("subtitle", ""),
            "tech_stack": master_proj.get("tech_stack", ""),
            "url": master_proj.get("live_url") or master_proj.get("github_url", ""),
            "url_label": master_proj.get("url_label", "Link"),
            "bullets": bullets[:3],  # Keep strictly 3 bullets for 1-page fit
        }
        rendered_projects.append(proj_entry)

    def _to_latex(s: str) -> str:
        s = re.sub(r"\*\*([^*]+)\*\*", r"\\textbf{\1}", s)
        s = re.sub(r"\*([^*]+)\*", r"\\textit{\1}", s)
        s = s.replace("%", r"\%").replace("&", r"\&").replace("$", r"\$").replace("_", r"\_")
        return s

    # Summary
    summary = _to_latex(summary)

    # Skills
    skills_languages = _to_latex(skills_languages)
    skills_cs = _to_latex(skills_cs)
    skills_backend = _to_latex(skills_backend)
    skills_frontend = _to_latex(skills_frontend)
    skills_databases = _to_latex(skills_databases)
    skills_engineering = _to_latex(skills_engineering)
    skills_aiml = _to_latex(skills_aiml)

    tex = template
    tex = tex.replace("{{ summary }}", summary)
    tex = tex.replace("{{ skills_languages }}", skills_languages)
    tex = tex.replace("{{ skills_cs }}", skills_cs)
    tex = tex.replace("{{ skills_backend }}", skills_backend)
    tex = tex.replace("{{ skills_frontend }}", skills_frontend)
    tex = tex.replace("{{ skills_databases }}", skills_databases)
    tex = tex.replace("{{ skills_engineering }}", skills_engineering)
    tex = tex.replace("{{ skills_aiml }}", skills_aiml)

    # Replace Experience Bullets block
    exp_block = "\n".join(f"    \\item {_to_latex(b)}" for b in exp_bullets)
    tex = re.sub(r"\{% for bullet in experience_bullets %\}.*?\{% endfor %\}", lambda m: exp_block, tex, flags=re.DOTALL)

    # Build and replace Projects block
    proj_blocks = []
    for p in rendered_projects:
        link_str = f"\\hfill \\href{{{p['url']}}}{{\\textbf{{{p['url_label']}}}}}" if p['url'] else ""
        sub_str = f"--- {_to_latex(p['subtitle'])}" if p['subtitle'] else ""
        b_str = "\n".join(f"    \\item {_to_latex(b)}" for b in p['bullets'])
        block = (
            f"\\textbf{{{p['name']} {sub_str}}} {link_str}\n\n"
            f"\\textit{{{_to_latex(p['tech_stack'])}}}\n\n"
            f"\\begin{{itemize}}\n{b_str}\n\\end{{itemize}}"
        )
        proj_blocks.append(block)

    all_projs_str = "\n\n".join(proj_blocks)
    tex = re.sub(r"\{% for proj in selected_projects %\}.*?\{% endfor %\}", lambda m: all_projs_str, tex, flags=re.DOTALL)

    return tex


def compile_latex_to_pdf(tex_content: str, output_pdf_path: Path) -> bool:
    """Compiles LaTeX code to a PDF using pdflatex, xelatex, or tectonic."""
    output_pdf_path.parent.mkdir(parents=True, exist_ok=True)
    job_stem = output_pdf_path.stem
    work_dir = output_pdf_path.parent / f"_tmp_{job_stem}"
    work_dir.mkdir(parents=True, exist_ok=True)

    tex_file = work_dir / f"{job_stem}.tex"
    tex_file.write_text(tex_content, encoding="utf-8")

    # Check available compilers
    compiler = None
    for candidate in ["tectonic", "pdflatex", "xelatex"]:
        if shutil.which(candidate):
            compiler = candidate
            break

    if not compiler:
        # If no local LaTeX compiler installed, preserve the .tex file for cloud / online compilation
        fallback_tex = output_pdf_path.with_suffix(".tex")
        fallback_tex.write_text(tex_content, encoding="utf-8")
        shutil.rmtree(work_dir, ignore_errors=True)
        return False

    try:
        if compiler == "tectonic":
            cmd = ["tectonic", "-o", str(work_dir), str(tex_file)]
        else:
            cmd = [compiler, "-interaction=nonstopmode", f"-output-directory={work_dir}", str(tex_file)]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        compiled_pdf = work_dir / f"{job_stem}.pdf"
        if compiled_pdf.exists():
            shutil.copy2(compiled_pdf, output_pdf_path)
            shutil.rmtree(work_dir, ignore_errors=True)
            return True
    except Exception as e:
        print(f"  ! LaTeX compilation failed: {e}")

    shutil.rmtree(work_dir, ignore_errors=True)
    return False


COVER_LETTER_TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "cover_letter_template.tex"
OUT_COVER_LETTERS_DIR = ROOT / "out" / "cover_letters"


def render_cover_letter_latex(job: Job, portfolio: dict[str, Any], cover_note: str) -> str:
    """Renders LaTeX cover letter matching resume styling."""
    template = COVER_LETTER_TEMPLATE_PATH.read_text(encoding="utf-8")
    
    from datetime import datetime
    today_str = datetime.now().strftime("%B %d, %Y")
    
    def _to_latex(s: str) -> str:
        s = re.sub(r"\*\*([^*]+)\*\*", r"\\textbf{\1}", s)
        s = re.sub(r"\*([^*]+)\*", r"\\textit{\1}", s)
        s = s.replace("%", r"\%").replace("&", r"\&").replace("$", r"\$").replace("_", r"\_")
        return s

    # Convert paragraphs in cover note to LaTeX paragraphs
    paragraphs = [p.strip() for p in cover_note.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [cover_note.strip()]

    formatted_paras = []
    for p in paragraphs:
        # replace inner single newlines with spaces
        p_clean = " ".join(p.splitlines())
        formatted_paras.append(_to_latex(p_clean))

    body_latex = "\n\n".join(formatted_paras)

    tex = template
    tex = tex.replace("{{ date }}", today_str)
    tex = tex.replace("{{ company }}", _to_latex(job.company))
    tex = tex.replace("{{ title }}", _to_latex(job.title))
    tex = tex.replace("{{ letter_body }}", body_latex)
    return tex


def build_cover_letter_for_job(job: Job, portfolio: dict[str, Any] | None = None) -> tuple[str, Path]:
    """Generates and compiles a tailored LaTeX cover letter for a job."""
    if portfolio is None:
        portfolio = _load_master_portfolio()

    # Use the tailored cover note drafted by the pipeline, or fallback
    cover_note = (job.draft or {}).get("cover_note") or (
        f"I am writing to express my strong interest in the {job.title} position at {job.company}. "
        f"With hands-on experience architecting high-performance backend systems, agentic AI platforms, "
        f"and scalable full-stack applications, I am eager to contribute to your engineering goals.\n\n"
        f"In my previous work, I have engineered distributed real-time platforms handling high concurrency, "
        f"built multi-tool AI systems with vector databases, and deployed production CI/CD pipelines. "
        f"I look forward to discussing how my technical background aligns with your team's needs."
    )

    latex_code = render_cover_letter_latex(job, portfolio, cover_note)

    safe_company = re.sub(r"\W+", "_", job.company.lower()).strip("_")
    safe_title = re.sub(r"\W+", "_", job.title.lower()).strip("_")
    pdf_filename = f"Cover_Letter_Snehith_{safe_company}_{safe_title}.pdf"
    pdf_path = OUT_COVER_LETTERS_DIR / pdf_filename

    compile_latex_to_pdf(latex_code, pdf_path)

    # Save .tex alongside PDF
    tex_path = pdf_path.with_suffix(".tex")
    tex_path.write_text(latex_code, encoding="utf-8")

    return latex_code, pdf_path


def build_resume_for_job(job: Job, provider: Provider | None = None, model: str | None = None) -> tuple[str, Path]:
    """Main function: tailors LaTeX and compiles a PDF resume for a specific job."""
    portfolio = _load_master_portfolio()
    try:
        if provider is None or model is None:
            provider, model = resolve("draft")
        tailored_data = tailor_resume_data(job, portfolio, provider, model)
    except Exception as e:
        print(f"    ! LLM tailoring fallback for {job.company}: {e}")
        tailored_data = {
            "selected_project_ids": ["qrave", "snehith_gpt", "ai_crop_doctor"],
            "summary": (
                "Software Engineer with hands-on experience architecting high-concurrency backend services, "
                "real-time distributed platforms, and agentic AI systems with strong foundations in Data Structures and Algorithms."
            ),
            "skills": {
                "languages": "Java, Python, JavaScript, TypeScript, SQL, C++",
                "cs": "Data Structures & Algorithms, OOP, DBMS, Operating Systems, Computer Networks, SDLC",
                "backend": "Node.js, Express.js, FastAPI, Flask, REST APIs, WebSockets",
                "frontend": "React, TypeScript, JavaScript, HTML5, CSS3, Tailwind CSS",
                "databases": "PostgreSQL, MySQL, Supabase, Redis",
                "engineering": "Git, GitHub, Docker, Linux, GitHub Actions, Pytest, Debugging",
                "aiml": "PyTorch, OpenCV, YOLOv8, LLMs, Generative AI, RAG, Hugging Face",
            },
        }

    latex_code = render_latex(tailored_data, portfolio)

    safe_company = re.sub(r"\W+", "_", job.company.lower()).strip("_")
    safe_title = re.sub(r"\W+", "_", job.title.lower()).strip("_")
    pdf_filename = f"Resume_Snehith_{safe_company}_{safe_title}.pdf"
    pdf_path = OUT_RESUMES_DIR / pdf_filename

    compile_latex_to_pdf(latex_code, pdf_path)
    
    # Save .tex alongside PDF
    tex_path = pdf_path.with_suffix(".tex")
    tex_path.write_text(latex_code, encoding="utf-8")

    return latex_code, pdf_path


def build_application_kit_for_job(job: Job, provider: Provider | None = None, model: str | None = None) -> dict[str, Any]:
    """Builds both tailored 1-page Resume AND Cover Letter PDFs for a job."""
    portfolio = _load_master_portfolio()
    resume_tex, resume_pdf = build_resume_for_job(job, provider=provider, model=model)
    cover_tex, cover_pdf = build_cover_letter_for_job(job, portfolio=portfolio)

    return {
        "resume_tex_path": str(resume_pdf.with_suffix(".tex")),
        "resume_pdf_path": str(resume_pdf) if resume_pdf.exists() else None,
        "cover_letter_tex_path": str(cover_pdf.with_suffix(".tex")),
        "cover_letter_pdf_path": str(cover_pdf) if cover_pdf.exists() else None,
    }

