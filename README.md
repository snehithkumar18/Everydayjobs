# 🚀 Autonomous AI Job Hunting & Screening Engine (`Everydayjobs`)

An autonomous, multi-ATS job intelligence and application drafting pipeline. It monitors 100+ top company career boards and remote feeds daily, filters 9,000+ live jobs deterministically, evaluates contextual match with **Google Gemini 3.5** against your profile, drafts tailored resume bullets & cover notes, and dispatches an automated HTML email digest directly to your inbox twice a day.

---

## ⚡ Key Highlights & Architecture

- **100% Free Tier Execution**: Zero infrastructure costs using **Google Gemini 3.5 Flash / Lite** + **GitHub Actions (Ubuntu Runners)** + **Gmail SMTP**.
- **Multi-ATS Integration**: Scrapes public, direct REST endpoints from **Greenhouse**, **Lever**, **Ashby**, and global remote feeds (**Jobicy, RemoteOK, Remotive, Arbeitnow**).
- **Cost-Zero Deterministic Pre-Filtering**: Filters out ~98% of noise (wrong seniority, non-qualifying titles, geo-restricted remote roles) before calling any LLM.
- **Lopsided 2-Stage LLM Evaluation**:
  - **Stage 1 (Screening)**: Evaluates batches of jobs in parallel using `gemini-3.5-flash-lite`.
  - **Stage 2 (Drafting)**: Deeply drafts tailored resume bullets, 120-word cover notes, technical interview questions, and honest gap analyses for top-scoring roles ($\ge 6.5$) using `gemini-3.5-flash`.
- **India Work-Eligibility Geofencing**: Automatically detects and excludes roles requiring US/EU/UK-only citizenship or residency.
- **Fault-Tolerant Reliability**: Built-in exponential backoff on HTTP `429`/`503`, rate-pacing delays, and partial JSON streaming recovery.
- **24/7 Hands-off Cloud Execution**: Runs on GitHub Actions twice daily (6:00 AM & 6:00 PM IST) with persistent `actions/cache` deduplication so you never see the same job twice.

---

## 📁 Project Structure

```
├── .github/workflows/
│   └── daily.yml          # GitHub Actions 2x daily cloud cron schedule
├── jobhunt/
│   ├── cli.py             # CLI commands: run, profile, applied, stats
│   ├── fetch.py           # Multi-threaded ATS scrapers (Greenhouse, Lever, Ashby, feeds)
│   ├── prefilter.py       # Deterministic regex, seniority, and location filter
│   ├── llm.py             # Two-stage screening & application kit drafting
│   ├── providers.py       # Swappable LLM provider backends (Gemini, Claude, Groq, Ollama)
│   ├── digest.py          # Dark-mode HTML email templating (Jinja2)
│   ├── mailer.py          # Secure TLS/SSL SMTP email dispatcher
│   ├── store.py           # Deduplication tracker (seen.json & tracker.csv)
│   └── mock.py            # Local mock fixtures for offline testing
├── tests/                 # 70 unit tests (100% pass) with Pytest
├── config.yaml            # Search rules, title inclusion/exclusion, locations, thresholds
├── companies.yaml         # 100+ verified tech company boards & slugs
├── profile.example.json   # Candidate profile template (skills, projects, domains)
├── requirements.txt       # Python dependencies
└── README.md              # Project documentation
```

---

## 🛠️ Step-by-Step Setup Guide

### 1. Prerequisites
- **Python 3.11+** installed ([python.org](https://www.python.org/downloads/))
- **Git** installed ([git-scm.com](https://git-scm.com/))
- A free **Google Gemini API Key** ([aistudio.google.com](https://aistudio.google.com/))
- A **Gmail App Password** ([myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords))

---

### 2. Local Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/snehithkumar18/Everydayjobs.git
   cd Everydayjobs
   ```

2. **Create and activate a virtual environment**:
   - **Windows (PowerShell)**:
     ```powershell
     python -m venv .venv
     .\.venv\Scripts\Activate.ps1
     ```
   - **macOS / Linux**:
     ```bash
     python3 -m venv .venv
     source .venv/bin/activate
     ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

---

### 3. Environment Configuration (`.env`)

Create a `.env` file in the root directory:

```ini
# LLM Provider Configuration
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_gemini_api_key_here
SCREEN_MODEL=gemini-3.5-flash-lite
DRAFT_MODEL=gemini-3.5-flash

# Email Dispatcher Configuration (Gmail SMTP)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASS=your_16_character_gmail_app_password
MAIL_TO=your_email@gmail.com
```

---

### 4. Candidate Profile Configuration (`profile.json`)

Copy the template and fill in your technical projects, skills, and target roles:

```bash
cp profile.example.json profile.json
```

Edit `profile.json` with your real portfolio:
```json
{
  "name": "Your Name",
  "current_title": "Software Engineer / Applied AI Engineer",
  "years_experience": 0,
  "seniority": "junior",
  "location": "India",
  "work_authorization": "India (Eligible for India and Worldwide Remote)",
  "education": "B.E. Computer Science",
  "core_skills": ["Python", "FastAPI", "PyTorch", "Computer Vision", "PostgreSQL", "Docker"],
  "notable_projects": [
    "AI Crop Doctor: Computer vision plant pathology diagnostic platform using PyTorch and YOLOv8",
    "QRAVE: Full-stack backend system with FastAPI, PostgreSQL, Redis, and BullMQ"
  ],
  "target_titles": [
    "Software Engineer", "Backend Developer", "AI Engineer", "Python Developer"
  ]
}
```

---

### 5. Run & Test Locally

- **Run without emailing (Dry Run)**:
  ```bash
  python -m jobhunt run
  ```
  *Outputs the formatted digest to `out/digest.html` and tracking data to `out/tracker.csv`.*

- **Run and send live email digest**:
  ```bash
  python -m jobhunt run --send
  ```

- **Run offline unit tests**:
  ```bash
  python -m pytest
  ```

---

## ☁️ 24/7 Cloud Automation (GitHub Actions)

The repository includes a pre-configured GitHub Actions workflow in [`.github/workflows/daily.yml`](.github/workflows/daily.yml) that executes twice every day (**6:00 AM & 6:00 PM IST**).

### Setting Up GitHub Repository Secrets
Go to your GitHub repository: **Settings → Secrets and variables → Actions → New repository secret** and add:

1. `GEMINI_API_KEY`: Your Google AI Studio Gemini API Key
2. `SMTP_USER`: Your Gmail address (e.g. `your_email@gmail.com`)
3. `SMTP_PASS`: Your 16-character Gmail App Password
4. `MAIL_TO`: Recipient email address
5. `PROFILE_JSON`: The complete JSON content of your `profile.json`

Once set, GitHub will automatically run the pipeline, screen new postings, and deliver the email digest to your inbox even when your computer is completely shut down.

---

## 💻 Local Windows Task Scheduler (Optional)

To run automatically in the background on your local machine:
```powershell
# Morning Task (6:00 AM IST)
$action = New-ScheduledTaskAction -Execute "$PWD\.venv\Scripts\python.exe" -Argument "-m jobhunt run --send" -WorkingDirectory "$PWD"
$trigger = New-ScheduledTaskTrigger -Daily -At 6:00AM
Register-ScheduledTask -TaskName "JobHunt_Morning_6AM" -Action $action -Trigger $trigger -Description "Autonomous Job Hunt Morning Run"

# Evening Task (6:00 PM IST)
$trigger2 = New-ScheduledTaskTrigger -Daily -At 6:00PM
Register-ScheduledTask -TaskName "JobHunt_Evening_6PM" -Action $action -Trigger $trigger2 -Description "Autonomous Job Hunt Evening Run"
```

---

## 📊 Application Tracking & Audit

- Every processed job is indexed in `seen.json` to prevent duplicates.
- All evaluated jobs with their match scores and AI reasoning are recorded in `out/tracker.csv`.
- Mark jobs you've applied to via CLI:
  ```bash
  python -m jobhunt applied "greenhouse:gitlab:8556658002"
  ```
- View application funnel stats:
  ```bash
  python -m jobhunt stats
  ```

---

## 📄 License
MIT License. Built for autonomous, high-efficiency job intelligence.
