1. Local runtime, installer, SQLite database, localhost dashboard.
2. Health checks for Ollama, Hermes, browser profile, and configured model.
3. Resume library: upload PDF, DOCX, TXT; extract and persist text.
4. Resume management: activate/deactivate variants and safely handle duplicates.
5. Profile editor for reusable, user-supplied facts.
6. Job URL ingestion: extract and store company, title, location, description, requirements.
7. Job duplicate detection.
8. Local LLM resume scoring with structured evidence.
9. Deterministic best-resume selection and fit explanation.
10. Application draft creation using only profile, resume, and job facts.
11. Field review and editing UI; unknown values remain blank.
12. Persistent Chromium browser profile and user login handoff.
13. Safe form inspection for standard inputs, selects, radios, checkboxes, and resume uploads.
14. Conservative field mapping and fill-for-review action.
15. Protected-field detection and stop states: CAPTCHA, MFA, legal, self-ID, government ID, payment, DOB, ambiguous questions.
16. Application state machine and audit events.
17. Per-application approval hash.
18. Automatic approval invalidation when fields, job, or resume changes.
19. Submission guard: current approval, matching hash, no safety stop, one obvious submit button.
20. Application/job/resume tables and review screens.
21. Error recovery, validation, redacted logs, and backup/export guidance.
22. Configurable role/location job scanning.
23. Background queue for scans, scoring, retries, progress, and cancellation.
24. Source-specific ATS adapters and stronger deduplication.
25. Application history and richer answer/field ontology.
26. Reviewed, versioned learned workflows.
27. Browser diagnostics, advanced filters, and saved searches.
28. Native desktop UX.
29. Reusable answer library with source attribution.
30. Outcome tracking, fit-score calibration, analytics, and optional model routing.

