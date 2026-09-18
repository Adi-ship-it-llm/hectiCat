# hectiCat Product Requirements Document (PRD)

**Version:** 0.1 MVP  
**Platform:** macOS, Linux, Windows (core dashboard, and Hermes detection). Browser automation (Playwright) is not yet part of the shipped app; hectiCat's own one-click install of Hermes/Ollama remains macOS/Homebrew-only (`installer/hectiCat-OneClick.command`), though Hermes itself ships separate installers for macOS/Linux and Windows.  
**Product type:** Local-first AI job discovery and application assistant

## 1. Product Summary

hectiCat is a local-first job application assistant that helps a user discover jobs, compare them against a personal resume library using a local LLM, select the most relevant resume, prepare application answers, inspect/fill application forms in a persistent browser profile, and optionally submit an individual application after explicit human approval.

Core flow:

**resume ingestion → job ingestion/scanning → local ATS evaluation → resume selection → application preparation → browser form inspection/fill → user review → explicit approval → optional submission**

The application is intentionally fail-closed around CAPTCHA/MFA, legal attestations, sensitive government-ID fields, payment, demographic/self-ID questions, and ambiguous factual questions.

## 2. Problem

Job applications are repetitive and time-consuming. Users commonly need to maintain several resume variants, identify which resume best matches a role, repeatedly answer similar questions, navigate different ATS interfaces, preserve browser sessions, and avoid fabricating application data.

hectiCat reduces repetitive work while preserving user control over factual claims and final submission.

## 3. Goals

### P0
1. Provide a local dashboard on localhost.
2. Maintain a reusable PDF/DOCX/TXT resume library.
3. Extract and persist resume text.
4. Ingest job URLs and retain job descriptions.
5. Score all active resumes with a local model.
6. Select and persist the highest-scoring resume.
7. Store profile facts locally.
8. Generate grounded application-field suggestions.
9. Use a persistent browser profile.
10. Inspect and fill ordinary HTML forms using known facts.
11. Require explicit approval for each application before submission.
12. Invalidate approval whenever application fields change.
13. Stop on protected/high-risk questions.
14. Never store passwords or MFA/session secrets in the application database.

### P1
1. Scan configurable job-search sources using role and location.
2. Deduplicate discovered jobs.
3. Provide operational health checks.
4. Support controlled learned workflows.
5. Provide auditable application state transitions.

## 4. Non-Goals

hectiCat will not:
- bypass CAPTCHA, MFA, rate limits, robots controls, paywalls, or anti-bot mechanisms;
- extract or persist passwords, cookies, session tokens, or MFA codes;
- invent employment history, education, authorization, compensation, dates, skills, or legal answers;
- autonomously decide demographic/self-identification answers;
- submit without explicit per-application approval;
- guarantee compatibility with every ATS;
- claim its heuristic ATS score equals an employer's ATS.

## 5. Personas

**Job seeker:** maintains multiple resume variants and wants faster, safer applications.

**Power user:** wants local inference, inspectable automation, configurable sources, and local data ownership.

## 6. Core User Journeys

### Resume onboarding
Upload/place a PDF, DOCX, or TXT resume → extract text → add it to the library → allow multiple active variants.

### Job evaluation
Paste a job URL or scan → open with Playwright → extract metadata/body → create the job record → evaluate every active resume locally → select the highest-scoring resume.

### Application preparation
Create application draft → generate grounded field suggestions using profile + resume + job → allow user edits.

### Browser fill
Open the dedicated browser profile → user logs in → hectiCat opens the job → navigate through one unambiguous Apply control → map known facts to ordinary inputs/selects/file uploads → leave unknown fields untouched.

### Submission
User reviews → explicitly approves the exact application → hectiCat stores an approval hash → any later field change invalidates approval → submit only with current approval, matching hash, no safety stop, and one obvious submit button.

## 7. Functional Requirements

### FR-01 Local runtime
- Target macOS, Linux, and Windows for the core dashboard and resume workflow.
- Install into the user's home directory under `hectiCat` (`HECTICAT_HOME` overrides).
- Dashboard on `127.0.0.1:8765`.

### FR-02 Resume ingestion
- PDF, DOCX, TXT supported.
- Extracted text persisted.
- Duplicate handling must be explicit and safe.

### FR-03 Job ingestion
- Accept a job URL.
- Persist source, URL, company, title, location, description, requirements, timestamp.
- URL is unique.

### FR-04 Resume matching
- Evaluate every active resume.
- Persist structured evaluation JSON.
- Required score fields: overall, required, keyword, experience, seniority.
- Persist matched keywords, missing keywords, hard failures, recommendation, confidence, and evidence.
- Select the highest-scoring active resume.

### FR-05 Application generation
- Use only supplied profile, resume, and job.
- Unknown facts become empty values.
- Never invent facts.

### FR-06 Browser session
- Persistent Chromium profile at `~/hectiCat/browser-profile`.
- User performs authentication.
- Credentials remain in browser/password manager.

### FR-07 Form inspection
- Inspect `input`, `textarea`, and `select`.
- Match using labels, names, IDs, placeholders, and ARIA labels.
- Support resume file upload and ordinary select/checkbox/radio controls.
- Leave unknown fields untouched.

### FR-08 Safety stops
Must stop on:
- CAPTCHA;
- MFA/2FA or verification code;
- legal attestation;
- background-check authorization;
- demographic/self-ID;
- disability/self-ID;
- payment;
- SSN/social security number;
- driver's license/passport number;
- date of birth;
- ambiguous factual questions.

### FR-09 Approval
- Approval is per application.
- Hash covers job ID, resume ID, and application fields.
- Editing fields clears approval.
- Changing job/resume selection invalidates approval.
- Submission without current approval is blocked.

### FR-10 Submission
Requires:
- current approval;
- matching approval hash;
- no safety stop;
- unique obvious submit button.

### FR-11 Health
Report Ollama availability, Hermes availability, browser-profile existence, and model name.

## 8. Data Model

**resumes:** id, name, filename, text, active, created_at

**jobs:** id, source, url, company, title, location, salary, description, requirements, status, ats_score, fit_score, selected_resume_id, discovered_at

**evaluations:** id, job_id, resume_id, result_json, created_at

**applications:** id, job_id, resume_id, status, fields_json, notes, created_at, submitted_at, approved_hash

**profile:** key, value

**workflows:** id, site, name, steps_json, created_at

## 9. State Model

Job states: `new → scored`

Application states:
`draft → ready_for_review → filled_for_review → approved_for_submission → submitted`

Editing after approval must return to `ready_for_review` and clear `approved_hash`.

## 10. Non-Functional Requirements

### Security
- Localhost by default.
- No password storage.
- No credential extraction.
- No secrets in logs.
- Fail closed on protected/sensitive fields.

### Privacy
Resume/profile/evaluation/application data stays local by default. ATS and application-generation inference uses the local model.

### Reliability
Job failures must not corrupt the DB. Submission must fail closed if any precondition is unmet.

### Explainability
Persist structured ATS evidence and show application values to the user before submission.

## 11. UI Requirements

MVP should provide:
- job URL input;
- role/location scan controls;
- resume upload;
- jobs table;
- resumes table;
- applications table;
- profile editor;
- browser-login action;
- application review page;
- fill-for-review action;
- explicit approve action;
- explicit submit action;
- health/status view.

## 12. Acceptance Criteria

A release candidate must demonstrate:
1. Fresh install succeeds on supported macOS, Linux, and Windows systems.
2. Dashboard starts on localhost.
3. PDF resume import works.
4. Job URL ingestion works.
5. Multiple resume scoring and deterministic selection work.
6. Generated fields contain no unsupported facts.
7. Persistent browser profile survives restart.
8. Standard forms can be inspected and filled.
9. Unknown fields are not guessed.
10. Safety conditions block progression.
11. Approval creates a reproducible hash.
12. Editing data invalidates approval.
13. Submission without approval is blocked.
14. Multiple/ambiguous submit controls are blocked.
15. Secrets are not persisted in the application DB.
16. Health diagnostics identify missing prerequisites.

## 13. Risks and Mitigations

**LLM hallucination** → grounded prompting + empty unknowns + review.

**ATS-score overconfidence** → call it heuristic; retain evidence.

**ATS UI variability** → deterministic DOM mapping; leave unknown controls alone.

**Anti-bot defenses** → stop instead of bypassing.

**Accidental submission** → explicit approval + hash + unique submit-button requirement.

**Long-running scans** → future background queue; current MVP is synchronous.

## 14. Roadmap

**v0.2:** background queue, better ATS adapters, application history, richer field ontology.

**v0.3:** reviewed learned workflows, browser diagnostics, stronger deduplication, advanced search filters.

**v0.4:** native desktop UX, reusable answer library, calibration against actual outcomes, optional model routing.

## 15. Success Metrics

- % of jobs successfully scored.
- % with a selected resume.
- % of standard forms successfully populated.
- % requiring factual correction.
- % of protected flows stopped safely.
- Time saved per application.
- Zero unauthorized submissions.
