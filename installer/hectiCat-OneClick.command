#!/bin/bash
set -euo pipefail

# hectiCat One-Click Installer + Local Job Application Agent
# Apple Silicon macOS. Installs a local dashboard, Ollama/Qwen3.5-9B,
# Hermes computer-use, persistent Playwright browser profile, job scanning,
# ATS scoring, resume selection, form inspection/filling, and human-gated submit.

APP="$HOME/hectiCat"
VENV="$APP/.venv"
PY="$VENV/bin/python"
PIP="$VENV/bin/pip"

echo "== hectiCat: local job application agent =="
if [[ "$(uname -s)" != "Darwin" ]]; then echo "This installer requires macOS."; exit 1; fi
if [[ "$(uname -m)" != "arm64" ]]; then echo "This build targets Apple Silicon."; exit 1; fi

if ! command -v brew >/dev/null 2>&1; then
  echo "Installing Homebrew..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  eval "$(/opt/homebrew/bin/brew shellenv)"
else
  eval "$(/opt/homebrew/bin/brew shellenv)" || true
fi

brew update >/dev/null 2>&1 || true
brew install python@3.12 sqlite jq git curl uv >/dev/null 2>&1 || true

mkdir -p "$APP"/{data,resumes,jobs,applications,logs,skills,downloads,browser-profile}
python3.12 -m venv "$VENV" 2>/dev/null || python3 -m venv "$VENV"
"$PIP" install --upgrade pip >/dev/null
cat > "$APP/requirements.txt" <<'REQ'
fastapi
uvicorn[standard]
jinja2
python-multipart
httpx
pydantic
pypdf
python-docx
beautifulsoup4
playwright
python-dateutil
REQ
"$PIP" install -r "$APP/requirements.txt" >/dev/null
"$PY" -m playwright install chromium >/dev/null

# Ollama + local model
if ! command -v ollama >/dev/null 2>&1; then brew install ollama >/dev/null; fi
if ! curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  nohup ollama serve >"$APP/logs/ollama.log" 2>&1 &
  sleep 3
fi
ollama pull qwen3.5:9b >/dev/null

# Hermes + Cua computer use
if ! command -v hermes >/dev/null 2>&1; then
  curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
fi
export PATH="$HOME/.local/bin:$HOME/.hermes/bin:/opt/homebrew/bin:$PATH"
hermes computer-use install >/dev/null 2>&1 || true
cua-driver skills install >/dev/null 2>&1 || true

# Browser Use CLI is optional; current CLI is installed through uv.
if ! command -v browser-use >/dev/null 2>&1; then
  uv tool install --python 3.12 browser-use >/dev/null 2>&1 || true
fi
if command -v browser-use >/dev/null 2>&1; then
  browser-use skill install >/dev/null 2>&1 || true
fi

cat > "$APP/app.py" <<'PY'
import asyncio, datetime, json, os, re, sqlite3, subprocess, urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional
from hashlib import sha256
import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, Form, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from pypdf import PdfReader
from docx import Document
from playwright.async_api import async_playwright

BASE = Path.home() / "hectiCat"
DB = BASE / "data" / "hecticat.sqlite3"
PROFILE_JSON = BASE / "profile.json"
BROWSER_PROFILE = BASE / "browser-profile"
MODEL = os.getenv("HECTICAT_MODEL", "qwen3.5:9b")
OLLAMA = os.getenv("HECTICAT_OLLAMA", "http://127.0.0.1:11434")

app = FastAPI(title="hectiCat")
pw = None
context = None

def db():
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    c = db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS resumes(
      id INTEGER PRIMARY KEY, name TEXT, filename TEXT, text TEXT, active INTEGER DEFAULT 1,
      created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS jobs(
      id INTEGER PRIMARY KEY, source TEXT, url TEXT UNIQUE, company TEXT, title TEXT, location TEXT,
      salary TEXT, description TEXT, requirements TEXT, status TEXT DEFAULT 'new',
      ats_score REAL, fit_score REAL, selected_resume_id INTEGER, discovered_at TEXT
    );
    CREATE TABLE IF NOT EXISTS evaluations(
      id INTEGER PRIMARY KEY, job_id INTEGER, resume_id INTEGER, result_json TEXT,
      created_at TEXT, UNIQUE(job_id,resume_id)
    );
    CREATE TABLE IF NOT EXISTS applications(
      id INTEGER PRIMARY KEY, job_id INTEGER, resume_id INTEGER, status TEXT,
      fields_json TEXT, notes TEXT, created_at TEXT, submitted_at TEXT, approved_hash TEXT
    );
    CREATE TABLE IF NOT EXISTS profile(key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS workflows(
      id INTEGER PRIMARY KEY, site TEXT, name TEXT, steps_json TEXT, created_at TEXT
    );
    """)
    try:
        c.execute("ALTER TABLE applications ADD COLUMN approved_hash TEXT")
    except sqlite3.OperationalError:
        pass
    c.commit(); c.close()

def now(): return datetime.datetime.now().isoformat(timespec="seconds")

def profile() -> Dict[str, Any]:
    p = {}
    c = db()
    for r in c.execute("SELECT key,value FROM profile"):
        try: p[r["key"]] = json.loads(r["value"])
        except: p[r["key"]] = r["value"]
    c.close()
    if PROFILE_JSON.exists():
        try:
            raw = json.loads(PROFILE_JSON.read_text())
            for k,v in raw.items():
                if v not in ("", [], None): p.setdefault(k,v)
        except: pass
    return p

def set_profile_from_json(path: Path):
    raw = json.loads(path.read_text())
    c = db()
    for k,v in raw.items():
        c.execute("INSERT OR REPLACE INTO profile(key,value) VALUES(?,?)",(k,json.dumps(v)))
    c.commit(); c.close()

def extract_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        return "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)
    if path.suffix.lower() == ".docx":
        d=Document(str(path)); return "\n".join(x.text for x in d.paragraphs)
    return path.read_text(errors="ignore")

async def llm_json(system: str, user: str) -> Dict[str, Any]:
    payload = {
      "model": MODEL, "stream": False, "format": "json",
      "options": {"temperature": 0.1},
      "messages": [{"role":"system","content":system},{"role":"user","content":user}]
    }
    async with httpx.AsyncClient(timeout=180) as x:
        r=await x.post(f"{OLLAMA}/api/chat", json=payload); r.raise_for_status()
        return json.loads(r.json()["message"]["content"])

ATS_SYSTEM = """You are a strict ATS evaluator. Compare one job listing against one resume.
Return JSON only with:
overall_score (0-100), required_score (0-100), keyword_score (0-100),
experience_score (0-100), seniority_score (0-100),
matched_keywords [], missing_keywords [], hard_failures [],
recommendation ("strong_match"|"match"|"weak_match"|"reject"),
confidence (0-1), evidence [].
Do not infer facts not in the supplied text. Treat explicit required qualifications as hard constraints."""
async def evaluate(job, resume):
    return await llm_json(ATS_SYSTEM, f"JOB:\n{job}\n\nRESUME:\n{resume}")

async def choose_resume(job_id: int):
    c=db(); job=c.execute("SELECT * FROM jobs WHERE id=?",(job_id,)).fetchone()
    resumes=c.execute("SELECT * FROM resumes WHERE active=1").fetchall()
    if not job or not resumes: c.close(); return None
    best=None
    for r in resumes:
        result=await evaluate((job["title"],job["company"],job["description"],job["requirements"]),r["text"])
        score=float(result.get("overall_score",0))
        c.execute("""INSERT OR REPLACE INTO evaluations(job_id,resume_id,result_json,created_at)
                     VALUES(?,?,?,?)""",(job_id,r["id"],json.dumps(result),now()))
        if best is None or score > best[0]: best=(score,r["id"],result)
    c.execute("UPDATE jobs SET ats_score=?,selected_resume_id=? WHERE id=?",(best[0],best[1],job_id))
    c.commit(); c.close()
    return best

def parse_job_text(url, title, body):
    host=urllib.parse.urlparse(url).netloc.lower()
    source=host.replace("www.","")
    company=""
    t=title.strip()
    if " - " in t:
        bits=[x.strip() for x in t.split(" - ") if x.strip()]
        if len(bits)>=2: t=bits[0]; company=bits[-1]
    return source, company, t, body[:50000]

async def ensure_browser():
    global pw, context
    if pw is None:
        pw = await async_playwright().start()
    if context is None:
        context = await pw.chromium.launch_persistent_context(
            str(BROWSER_PROFILE), headless=False, viewport={"width": 1440, "height": 1000}
        )
    return context

async def scrape(url):
    ctx = await ensure_browser()
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(1200)
    title = await page.title()
    body = await page.locator("body").inner_text(timeout=15000)
    return parse_job_text(url, title, body)

async def search_site(url):
    ctx = await ensure_browser()
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(1200)
    links = await page.locator("a").evaluate_all("""els => els.map(a => ({t:(a.innerText||'').trim(),h:a.href})).filter(x => x.h)""")
    return urllib.parse.urlparse(url).netloc.lower().replace("www.", ""), links[:500]

async def open_application_page(page, job_url):
    await page.goto(job_url, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(1200)
    candidates=[]
    loc=page.locator("a,button").filter(has_text=re.compile(r"^(apply|apply now|easy apply|start application)$", re.I))
    for i in range(await loc.count()):
        try:
            txt=(await loc.nth(i).inner_text()).strip()
            href=await loc.nth(i).get_attribute("href")
            candidates.append((txt,href,i))
        except Exception:
            pass
    if len(candidates)==1:
        _, href, idx = candidates[0]
        if href and href.startswith("http"):
            await page.goto(href, wait_until="domcontentloaded", timeout=60000)
        else:
            await loc.nth(idx).click()
            await page.wait_for_timeout(1200)
    return page


def approval_hash(aid: int) -> str:
    c=db(); row=c.execute("SELECT * FROM applications WHERE id=?",(aid,)).fetchone(); c.close()
    if not row: return ""
    payload=f"{row['job_id']}|{row['resume_id']}|{row['fields_json'] or '{}'}"
    return sha256(payload.encode()).hexdigest()

def match_form_value(hay: str, fields: Dict[str, Any]):
    aliases={
      "full_name":["full name","legal name"], "first_name":["first name","given name","firstname"],
      "last_name":["last name","surname","family name","lastname"], "email":["email","e-mail"],
      "phone":["phone","mobile","telephone"], "linkedin":["linkedin"],
      "portfolio":["portfolio","personal website","website","github"], "city":["city"],
      "state":["state","province"], "country":["country"],
      "work_authorization":["work authorization","authorized to work"],
      "sponsorship_required":["sponsorship","visa sponsorship"],
      "years_experience":["years of experience","years experience"],
      "education":["education","degree","school","university","college"],
      "cover_letter":["cover letter","coverletter"],
    }
    for key,value in fields.items():
        k=str(key).lower()
        if k in aliases and any(a in hay for a in aliases[k]): return value
        if k in hay: return value
    return None

def safety_reason(text: str) -> Optional[str]:
    s=text.lower()
    patterns=[
      ("CAPTCHA","captcha"),("2FA / MFA","two-factor"),("2FA / MFA","verification code"),
      ("legal attestation","attest that"),("background-check authorization","background check"),
      ("demographic/self-ID","gender identity"),("demographic/self-ID","veteran status"),
      ("disability/self-ID","disability status"),("payment","credit card"),
      ("government ID","social security"),("government ID","ssn"),("government ID","driver's license"),
      ("government ID","passport number"),("date of birth","date of birth"),("date of birth","birth date")
    ]
    for label,p in patterns:
        if p in s: return label
    return None

async def inspect_form(url: str):
    global pw, context
    if pw is None: pw=await async_playwright().start()
    if context is None:
        context=await pw.chromium.launch_persistent_context(str(BROWSER_PROFILE), headless=False)
    page=context.pages[0] if context.pages else await context.new_page()
    await page.goto(url,wait_until="domcontentloaded",timeout=60000)
    await page.wait_for_timeout(1000)
    fields=await page.locator("input,textarea,select").evaluate_all("""els => els.map((e,i)=>({
      i,tag:e.tagName,type:e.type||'',name:e.name||'',id:e.id||'',
      placeholder:e.placeholder||'',aria:e.getAttribute('aria-label')||'',
      required:!!e.required, value:e.value||'',
      options:e.tagName==='SELECT'?[...e.options].map(o=>({text:o.text,value:o.value})):[],
      label:(e.labels&&e.labels[0])?e.labels[0].innerText:''
    }))""")
    return page.url, fields

async def fill_application(aid: int, submit: bool=False):
    global pw, context
    c=db(); a=c.execute("SELECT * FROM applications WHERE id=?",(aid,)).fetchone()
    if not a: c.close(); return {"ok":False,"error":"application not found"}
    job=c.execute("SELECT * FROM jobs WHERE id=?",(a["job_id"],)).fetchone()
    resume=c.execute("SELECT * FROM resumes WHERE id=?",(a["resume_id"],)).fetchone()
    fields=json.loads(a["fields_json"] or "{}"); c.close()
    reason=safety_reason(json.dumps(fields))
    if reason: return {"ok":False,"blocked":reason}
    if pw is None: pw=await async_playwright().start()
    if context is None:
        context=await pw.chromium.launch_persistent_context(str(BROWSER_PROFILE), headless=False)
    page=context.pages[0] if context.pages else await context.new_page()
    await open_application_page(page, job["url"])
    await page.wait_for_timeout(800)
    inputs=await page.locator("input,textarea,select").all()
    changed=[]
    for i,el in enumerate(inputs):
        try:
            meta=await el.evaluate("""e=>({tag:e.tagName,type:e.type||'',name:e.name||'',id:e.id||'',ph:e.placeholder||'',aria:e.getAttribute('aria-label')||'',label:(e.labels&&e.labels[0])?e.labels[0].innerText:'',accept:e.accept||''})""")
            hay=" ".join(str(meta.get(k,"")) for k in ("name","id","ph","aria","label")).lower()
            val=match_form_value(hay, fields)
            if val is None: continue
            if meta["type"]=="file":
                if resume and resume["filename"]:
                    path=str(BASE/"resumes"/resume["filename"])
                    if os.path.exists(path): await el.set_input_files(path); changed.append(meta["name"] or meta["id"] or f"field-{i}")
            elif meta["tag"]=="SELECT":
                try: await el.select_option(label=str(val))
                except: await el.select_option(str(val))
                changed.append(meta["name"] or meta["id"] or f"field-{i}")
            elif meta["type"] in ("checkbox","radio"):
                if bool(val): await el.check()
                changed.append(meta["name"] or meta["id"] or f"field-{i}")
            else:
                await el.fill(str(val)); changed.append(meta["name"] or meta["id"] or f"field-{i}")
        except Exception:
            continue
    # Never submit implicitly.
    if submit:
        if a["status"] != "approved_for_submission":
            return {"ok":False,"blocked":"explicit approval required"}
        if a["approved_hash"] != approval_hash(aid):
            return {"ok":False,"blocked":"approved application changed; review and approve again"}
        reason=safety_reason(await page.locator("body").inner_text())
        if reason: return {"ok":False,"blocked":reason}
        buttons=page.locator("button,input[type=submit]")
        candidates=[]
        for j in range(await buttons.count()):
            if await buttons.nth(j).evaluate("(e)=>e.tagName==='BUTTON'"):
                txt=await buttons.nth(j).inner_text()
            else:
                txt=await buttons.nth(j).get_attribute("value")
            if txt and re.search(r"submit|apply|send application",txt,re.I): candidates.append(j)
        if len(candidates)!=1: return {"ok":False,"blocked":"could not uniquely identify submit button"}
        await buttons.nth(candidates[0]).click()
        c=db(); c.execute("UPDATE applications SET status='submitted',submitted_at=? WHERE id=?",(now(),aid)); c.commit(); c.close()
        return {"ok":True,"submitted":True,"changed":changed}
    c=db(); c.execute("UPDATE applications SET status='filled_for_review' WHERE id=?",(aid,)); c.commit(); c.close()
    return {"ok":True,"submitted":False,"changed":changed}

async def prepare(aid:int):
    c=db(); a=c.execute("SELECT * FROM applications WHERE id=?",(aid,)).fetchone()
    if not a: c.close(); return
    j=c.execute("SELECT * FROM jobs WHERE id=?",(a["job_id"],)).fetchone()
    r=c.execute("SELECT * FROM resumes WHERE id=?",(a["resume_id"],)).fetchone()
    p=profile(); c.close()
    sys="""Create only grounded job-application field suggestions. Return JSON object.
Keys should be common application concepts such as full_name,email,phone,city,state,linkedin,
portfolio,work_authorization,sponsorship_required,years_experience,education,cover_letter.
Never invent facts. If a value is unknown, use an empty string. Cover letter must be concise and
based only on the supplied resume/profile/job."""
    result=await llm_json(sys, f"PROFILE:{json.dumps(p)}\nRESUME:{r['text']}\nJOB:{j['title']} {j['company']}\n{j['description'][:25000]}")
    c=db(); c.execute("UPDATE applications SET fields_json=?,status='ready_for_review' WHERE id=?",(json.dumps(result),aid)); c.commit(); c.close()

@app.on_event("startup")
async def startup():
    BASE.joinpath("data").mkdir(parents=True,exist_ok=True); init_db()
    if PROFILE_JSON.exists():
        try: set_profile_from_json(PROFILE_JSON)
        except: pass
    # auto-import resumes from folder
    c=db()
    known={r["filename"] for r in c.execute("SELECT filename FROM resumes")}
    for f in (BASE/"resumes").glob("*"):
        if f.suffix.lower() in (".pdf",".docx",".txt") and f.name not in known:
            try:
                c.execute("INSERT INTO resumes(name,filename,text,created_at) VALUES(?,?,?,?)",(f.stem,f.name,extract_text(f),now()))
            except: pass
    c.commit(); c.close()

@app.get("/",response_class=HTMLResponse)
async def home():
    c=db()
    jobs=c.execute("SELECT j.*,r.name resume_name FROM jobs j LEFT JOIN resumes r ON r.id=j.selected_resume_id ORDER BY j.id DESC").fetchall()
    resumes=c.execute("SELECT * FROM resumes ORDER BY id DESC").fetchall()
    apps=c.execute("""SELECT a.*,j.title,j.company FROM applications a JOIN jobs j ON j.id=a.job_id ORDER BY a.id DESC""").fetchall()
    c.close()
    rows="".join(f"""<tr><td>{x['id']}</td><td>{x['title']}</td><td>{x['company']}</td><td>{x['ats_score'] or ''}</td><td>{x['resume_name'] or ''}</td>
    <td><a href="/jobs/{x['id']}/prepare">prepare</a> · <a href="{x['url']}" target="_blank">open</a></td></tr>""" for x in jobs)
    rr="".join(f"<tr><td>{r['name']}</td><td>{r['filename']}</td></tr>" for r in resumes)
    aa="".join(f"<tr><td>{a['id']}</td><td>{a['title']}</td><td>{a['company']}</td><td>{a['status']}</td><td><a href='/applications/{a['id']}'>review</a></td></tr>" for a in apps)
    return HTMLResponse(f"""<!doctype html><html><head><meta charset=utf-8><title>hectiCat</title>
    <style>body{{font:15px system-ui;margin:32px;max-width:1200px}}input,button,textarea{{padding:9px;margin:4px}}table{{border-collapse:collapse;width:100%;margin:12px 0 30px}}td,th{{border:1px solid #ddd;padding:8px;text-align:left}}.warn{{padding:12px;border:1px solid #d99;background:#fff8e8}}.card{{padding:16px;border:1px solid #ddd;margin:12px 0;border-radius:10px}}</style></head>
    <body><h1>hectiCat</h1><div class=warn><b>Human-gated:</b> the agent may inspect and fill forms, but it will not submit until you explicitly approve that specific application. It stops for CAPTCHA/2FA/legal/self-ID/payment questions.</div>
    <div class=card><h2>Add job</h2><form method=post action=/jobs/add><input name=url size=90 placeholder="Paste a job URL"><button>Add + score</button></form>
    <h3>Scan jobs</h3><form method=get action=/scan><input name=role value="data engineer" placeholder="Role"><input name=location value="United States" placeholder="Location"><button>Scan</button></form>
    <h3>Resume</h3><form method=post action=/resumes/upload enctype="multipart/form-data"><input type=file name=file accept=".pdf,.docx,.txt"><button>Upload resume</button></form>
    <p><a href="/browser/login">Open login browser</a> · <a href="/profile">Profile</a> · <a href="/api/health">Health</a></p></div>
    <h2>Jobs</h2><table><tr><th>ID</th><th>Title</th><th>Company</th><th>ATS</th><th>Resume</th><th>Actions</th></tr>{rows}</table>
    <h2>Resumes</h2><table><tr><th>Name</th><th>File</th></tr>{rr}</table>
    <h2>Applications</h2><table><tr><th>ID</th><th>Title</th><th>Company</th><th>Status</th><th></th></tr>{aa}</table>
    </body></html>""")

@app.post("/jobs/add")
async def jobs_add(url:str=Form(...)):
    await add_job(url.strip()); return RedirectResponse("/",303)

@app.post("/resumes/upload")
async def resume_upload(file: UploadFile = File(...)):
    safe=Path(file.filename or "resume").name
    if Path(safe).suffix.lower() not in (".pdf",".docx",".txt"):
        return HTMLResponse("Unsupported resume format",400)
    dest=BASE/"resumes"/safe
    dest.write_bytes(await file.read())
    c=db(); c.execute("INSERT INTO resumes(name,filename,text,created_at) VALUES(?,?,?,?)",(dest.stem,dest.name,extract_text(dest),now())); c.commit(); c.close()
    return RedirectResponse("/",303)

@app.get("/jobs/{jid}/prepare")
async def job_prepare(jid:int):
    c=db(); j=c.execute("SELECT * FROM jobs WHERE id=?",(jid,)).fetchone(); r=c.execute("SELECT * FROM resumes WHERE id=?",(j["selected_resume_id"],)).fetchone() if j and j["selected_resume_id"] else None
    if not j or not r: c.close(); return HTMLResponse("No selected resume",400)
    c.execute("INSERT INTO applications(job_id,resume_id,status,fields_json,created_at) VALUES(?,?,?,?,?)",(jid,r["id"],"draft","{}",now())); aid=c.execute("SELECT last_insert_rowid()").fetchone()[0]; c.commit(); c.close()
    await prepare(aid); return RedirectResponse(f"/applications/{aid}",303)

@app.get("/applications/{aid}",response_class=HTMLResponse)
async def application(aid:int):
    c=db(); a=c.execute("""SELECT a.*,j.title,j.company,j.url,r.name resume_name FROM applications a JOIN jobs j ON j.id=a.job_id JOIN resumes r ON r.id=a.resume_id WHERE a.id=?""",(aid,)).fetchone(); c.close()
    if not a: return HTMLResponse("Not found",404)
    fields=json.loads(a["fields_json"] or "{}")
    items="".join(f"<tr><td>{k}</td><td><textarea name='{k}' rows=2 cols=80>{str(v)}</textarea></td></tr>" for k,v in fields.items())
    return HTMLResponse(f"""<html><body style='font:15px system-ui;margin:30px;max-width:1100px'><h1>Review application #{aid}</h1>
    <p><b>{a['title']}</b> — {a['company']}<br>Resume: {a['resume_name']}<br>Status: {a['status']}</p>
    <form method=post action="/applications/{aid}/save"><table>{items}</table><button>Save fields</button></form>
    <form method=post action="/applications/{aid}/fill"><button>Open browser and fill for review</button></form>
    <form method=post action="/applications/{aid}/approve"><button>Approve this exact application for submission</button></form>
    <form method=post action="/applications/{aid}/submit"><button>SUBMIT NOW</button></form>
    <p><b>SUBMIT NOW only works after the approval above and only if the page has exactly one obvious submit button and no safety stop condition.</b></p>
    </body></html>""")

@app.post("/applications/{aid}/save")
async def app_save(aid:int, request:Request):
    data=await request.form(); fields={k:v for k,v in data.items() if k not in ("submit",)}
    c=db(); c.execute("UPDATE applications SET fields_json=?,status='ready_for_review',approved_hash=NULL WHERE id=?",(json.dumps(fields),aid)); c.commit(); c.close()
    return RedirectResponse(f"/applications/{aid}",303)

@app.post("/applications/{aid}/fill")
async def app_fill(aid:int):
    result=await fill_application(aid,False)
    return JSONResponse(result)

@app.post("/applications/{aid}/approve")
async def app_approve(aid:int):
    h=approval_hash(aid)
    c=db(); c.execute("UPDATE applications SET status='approved_for_submission',approved_hash=? WHERE id=?",(h,aid)); c.commit(); c.close()
    return RedirectResponse(f"/applications/{aid}",303)

@app.post("/applications/{aid}/submit")
async def app_submit(aid:int):
    result=await fill_application(aid,True)
    return JSONResponse(result)

@app.get("/browser/login")
async def browser_login(request:Request):
    target=request.query_params.get("url","https://www.linkedin.com/jobs/")
    global pw,context
    if pw is None: pw=await async_playwright().start()
    if context is None: context=await pw.chromium.launch_persistent_context(str(BROWSER_PROFILE),headless=False)
    page=context.pages[0] if context.pages else await context.new_page()
    await page.goto(target,wait_until="domcontentloaded",timeout=60000)
    return HTMLResponse("<h2>Login browser opened.</h2><p>Log in yourself in the dedicated hectiCat browser profile. Credentials stay in the browser.</p><p><a href='/'>Back</a></p>")

@app.get("/scan",response_class=HTMLResponse)
async def scan(request:Request):
    role=request.query_params.get("role",str(profile().get("target_role","data engineer")))
    location=request.query_params.get("location",str(profile().get("target_location","United States")))
    sites=json.loads((BASE/"sites.json").read_text())["sites"]
    found=[]
    for s in sites:
        if not s.get("enabled"): continue
        for template in s.get("search_urls",[]):
            u=template.replace("{role}",urllib.parse.quote_plus(role)).replace("{location}",urllib.parse.quote_plus(location))
            try:
                _,links=await search_site(u)
                for l in links:
                    h=l["h"]
                    if h.startswith("http") and not any(x in h for x in ("google.com/search","google.com/url")) and re.search(r"greenhouse|lever|jobs|careers|job",h,re.I):
                        found.append((l["t"][:120],h))
            except Exception: pass
    added=0
    for _,u in list(dict.fromkeys(found))[:20]:
        try: await add_job(u); added+=1
        except Exception: pass
    return HTMLResponse(f"<h2>Scan complete</h2><p>Role: {role}<br>Location: {location}<br>Added/scored: {added}</p><p><a href='/'>Back</a></p>")

@app.get("/profile",response_class=HTMLResponse)
async def profile_page():
    p=profile()
    rows="".join(f"<tr><td>{k}</td><td><textarea name='{k}' rows=2 cols=80>{json.dumps(v) if isinstance(v,(dict,list)) else v}</textarea></td></tr>" for k,v in p.items())
    return HTMLResponse(f"""<html><body style='font:15px system-ui;margin:30px'><h1>Profile</h1>
    <form method=post action=/profile/save><table>{rows}</table><button>Save profile</button></form>
    <p>For sensitive credentials, use the browser password manager rather than putting passwords here.</p><a href='/'>Back</a></body></html>""")

@app.post("/profile/save")
async def profile_save(request:Request):
    data=await request.form(); c=db()
    for k,v in data.items():
        try: val=json.loads(v)
        except: val=v
        c.execute("INSERT OR REPLACE INTO profile(key,value) VALUES(?,?)",(k,json.dumps(val)))
    c.commit(); c.close(); return RedirectResponse("/",303)

@app.get("/api/jobs")
async def api_jobs():
    c=db(); rows=[dict(x) for x in c.execute("SELECT * FROM jobs ORDER BY id DESC")]; c.close(); return rows

@app.get("/api/health")
async def health():
    checks={}
    try:
        async with httpx.AsyncClient(timeout=3) as x: checks["ollama"]=x.get(f"{OLLAMA}/api/tags").status_code==200
    except: checks["ollama"]=False
    checks["hermes"]=subprocess.run(["bash","-lc","command -v hermes >/dev/null"],capture_output=True).returncode==0
    checks["browser_profile"]=BROWSER_PROFILE.exists()
    return {"ok":all(checks.values()),"checks":checks,"model":MODEL}

init_db()
PY

cat > "$APP/sites.json" <<'JSON'
{
  "sites": [
    {"name":"Greenhouse","enabled":true,"search_urls":["https://www.google.com/search?q=site%3Aboards.greenhouse.io+%7Brole%7D+%7Blocation%7D"]},
    {"name":"Lever","enabled":true,"search_urls":["https://www.google.com/search?q=site%3Ajobs.lever.co+%7Brole%7D+%7Blocation%7D"]},
    {"name":"LinkedIn","enabled":false,"search_urls":["https://www.linkedin.com/jobs/search/?keywords={role}&location={location}"]},
    {"name":"Indeed","enabled":false,"search_urls":["https://www.indeed.com/jobs?q={role}&l={location}"]}
  ]
}
JSON

cat > "$APP/profile.example.json" <<'JSON'
{
  "full_name":"Your Name","email":"you@example.com","phone":"","city":"","state":"","country":"United States",
  "linkedin":"","portfolio":"","work_authorization":"","sponsorship_required":"","years_experience":"","education":"",
  "skills":[],"work_history":[],"target_role":"Data Engineer","target_location":"United States","salary_min":"","salary_max":""
}
JSON
if [ ! -f "$APP/profile.json" ]; then cp "$APP/profile.example.json" "$APP/profile.json"; fi

cat > "$APP/skills/hecticat-apply.md" <<'SKILL'
# hectiCat application skill

Use the dedicated browser profile, grounded facts only, and deterministic browser automation where possible.
Never invent application answers. Never type passwords, cookies, session tokens, MFA codes, SSNs, government IDs, or other secrets.
Stop at CAPTCHA, MFA/2FA, legal attestations, background-check authorization, demographic/self-ID, payment, or ambiguous factual questions.
A specific application must be reviewed and explicitly approved before submission. Any change after approval invalidates approval.
Never bypass anti-bot controls or site restrictions.
SKILL

cat > "$APP/README.md" <<'MD'
# hectiCat

Local-first job application assistant for Apple Silicon Macs.

Run: `~/hectiCat/run.sh`
Dashboard: `http://127.0.0.1:8765`

Workflow: upload resumes → log into job sites in the dedicated browser → scan/paste jobs → local ATS scoring → select resume → prepare answers → inspect/fill application → review → explicit approval → optional submit.

Browser profile: `~/hectiCat/browser-profile`.

Hermes Computer Use is installed for tasks needing desktop-level interaction. Grant Accessibility and Screen Recording to the identity reported by `hermes computer-use doctor`.

Safety: hectiCat fails closed on CAPTCHA/MFA, anti-bot controls, legal attestations, government-ID fields, and ambiguous factual questions. It never stores passwords in its database.
MD

cat > "$APP/run.sh" <<'SH'
#!/bin/bash
set -e
export PATH="$HOME/.local/bin:$HOME/.hermes/bin:/opt/homebrew/bin:$PATH"
if ! curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  nohup ollama serve >"$HOME/hectiCat/logs/ollama.log" 2>&1 &
  sleep 3
fi
cd "$HOME/hectiCat"
exec "$HOME/hectiCat/.venv/bin/uvicorn" app:app --host 127.0.0.1 --port 8765
SH
chmod +x "$APP/run.sh"

cat > "$APP/doctor.sh" <<'SH'
#!/bin/bash
set +e
export PATH="$HOME/.local/bin:$HOME/.hermes/bin:/opt/homebrew/bin:$PATH"
echo "macOS: $(sw_vers -productVersion)"
echo "CPU: $(uname -m)"
echo "Ollama: $(command -v ollama || echo missing)"
curl -sf http://127.0.0.1:11434/api/tags >/dev/null && echo "Ollama API: OK" || echo "Ollama API: NOT READY"
echo "Hermes: $(command -v hermes || echo missing)"
command -v hermes >/dev/null && hermes computer-use status || true
command -v hermes >/dev/null && hermes computer-use doctor || true
echo "Browser Use: $(command -v browser-use || echo optional/not installed)"
echo "Dashboard: http://127.0.0.1:8765"
SH
chmod +x "$APP/doctor.sh"

cat > "$APP/launch.command" <<'SH'
#!/bin/bash
cd "$HOME/hectiCat"
exec "$HOME/hectiCat/run.sh"
SH
chmod +x "$APP/launch.command"

echo
echo "== hectiCat installation complete =="
echo "App: $APP"
echo "Run: $APP/run.sh"
echo "Dashboard: http://127.0.0.1:8765"
echo
echo "Next:"
echo "  1) Edit $APP/profile.json or use Profile in the dashboard."
echo "  2) Upload your resumes."
echo "  3) Use Open login browser and sign in yourself."
echo "  4) Scan jobs or paste job URLs."
echo "  5) Review ATS scoring, resume choice, and every application field."
echo "  6) Explicitly approve the exact application before submission."
echo
echo "Hermes Computer Use:"
echo "  hermes computer-use doctor"
echo "  hermes computer-use permissions grant"
echo
"$APP/run.sh"
