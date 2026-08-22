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

    raw = provider.complete(
        model=model,
        system=RESUME_TAILOR_SYSTEM,
        user=user_prompt,
        max_tokens=2200,
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


def build_resume_for_job(job: Job, provider: Provider | None = None, model: str | None = None) -> tuple[str, Path]:
    """Main function: tailors LaTeX and compiles a PDF resume for a specific job."""
    if provider is None or model is None:
        provider, model = resolve("draft")

    portfolio = _load_master_portfolio()
    tailored_data = tailor_resume_data(job, portfolio, provider, model)
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
