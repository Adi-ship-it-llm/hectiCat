# hectiCat Feature Roadmap

## Product direction

hectiCat should first earn trust as a **local, safe application-preparation
tool**, then reduce discovery and browser friction, and only afterwards learn
reusable workflows. Every release keeps the human in control: it never
fabricates facts, crosses a protected question, or submits without a current,
per-application approval.

This roadmap is organized by delivery dependencies rather than calendar dates.
An increment ships only when its exit criteria and the safety rules beneath it
are satisfied.

## Release sequence

| Increment | Outcome | Key features | Exit criteria |
|---|---|---|---|
| **0.1 — Trusted MVP** | A user can safely prepare and submit one standard application. | Local dashboard; PDF/DOCX/TXT resume library; job-URL ingestion; local resume scoring and selection; profile facts; grounded field suggestions; persistent browser profile; normal form inspection/fill; explicit approval hash; guarded submission; health view. | All P0 acceptance criteria and automated safety tests pass; one normal and one protected browser flow pass manually; no secrets are present in the DB or logs. |
| **0.1.x — Trust hardening** | The MVP is dependable enough for repeated personal use. | Better error states and recovery; validation of LLM response schema and score ranges; explicit duplicate resolution; job/application audit events; backup/export guidance; diagnostics for browser, Ollama, Hermes, and model availability. | Repeated job failures leave data intact; approval invalidation is verified through UI and API paths; diagnostics identify every missing prerequisite; critical workflows have actionable error messages. |
| **0.2 — Discovery at scale** | A user can build and prioritize a pipeline from configurable searches. | Role/location source scanning; source adapters; URL and content-based job deduplication; background queue with job progress, retries, and cancellation; application history; richer field ontology. | Long scans do not block the dashboard; re-running a scan does not create duplicate jobs; queued failures are visible and retryable; scoring and selection remain deterministic for a fixed input. |
| **0.3 — Controlled reuse** | Users can reuse reviewed site-specific steps without turning automation into a black box. | Reviewed learned workflows; browser diagnostics; stronger cross-source deduplication; advanced search filters and saved searches; expanded audit trail for application state transitions. | A learned workflow is reviewable, editable, versioned, and disabled by default until approved; an unexpected DOM or safety stop halts the workflow; every transition can be traced to its actor and input. |
| **0.4 — Personal operating system** | hectiCat becomes a polished local workspace for an active job search. | Native desktop UX; reusable answer library with source attribution; outcome tracking and score calibration; optional, clearly labeled model routing; richer application analytics. | Answer reuse never overrides job/resume/profile grounding; calibration reports uncertainty and does not present heuristic scores as employer ATS scores; users can inspect or disable every routing decision. |

## Delivery order inside the MVP

1. **Foundation and safety boundary** — local install/runtime, SQLite schema,
   migrations, localhost-only binding, structured logging with secret redaction,
   and health checks.
2. **Reliable inputs** — resume ingestion and extraction, profile editor, job
   URL ingestion, explicit duplicate handling, and data validation.
3. **Decision support** — local-model evaluation, persisted evidence, stable
   tie-breaking, selected-resume display, and grounded application drafts.
4. **Human-supervised browser work** — persistent profile, login handoff,
   deterministic form inspection, conservative value mapping, and a clear
   review screen.
5. **Irreversible-action guardrail** — protected-question detection,
   immutable approval payload/hash, approval invalidation on every edit, and
   unique-submit-button enforcement.

## Cross-release guardrails

- Keep all resume, profile, evaluation, and application data local by default.
- Treat unknown or ambiguous facts as blank; never infer them from a model.
- Stop rather than bypass CAPTCHA, MFA, legal attestations, background checks,
  payment, government-ID, date-of-birth, or self-ID flows.
- Require a new approval whenever the job, selected resume, or fields change.
- Make automation explainable: retain matching evidence, planned form values,
  safety stops, and state transitions.
- Prefer a safe halt over broad site compatibility. New ATS support is added
  only through tested, reviewable adapters or workflows.

## Success measures

Track these from 0.1 onward, segmented by source and workflow version:

- Job ingestion and scoring success rate.
- Percentage of scored jobs with a selected resume.
- Percentage of ordinary fields filled without a user correction.
- Rate of protected flows stopped safely and false-positive safety stops.
- Median time from job ingestion to review-ready application.
- Submission-block rate by cause (missing approval, hash mismatch, safety
  stop, ambiguous submit control).
- For 0.4 calibration: relationship between fit recommendation and user-recorded
  outcomes, reported with uncertainty rather than as a hiring prediction.

## Near-term backlog priorities

The first work after the 0.1 MVP should be: durable audit events, clear
recovery from browser and model failures, background scan jobs, and source
deduplication. These improve repeat-use reliability without weakening the
product's approval and safety model.
