# hectiCat Test Plan

## Strategy

1. Static/installation tests.
2. Unit tests for deterministic logic.
3. API/integration tests with mocked LLM/browser dependencies.
4. Manual end-to-end ATS tests.

## P0 Test Cases

| ID | Test | Expected |
|---|---|---|
| TC-001 | Apple Silicon installer | Completes without fatal error |
| TC-002 | Generated Python syntax | `py_compile` passes |
| TC-003 | Generated shell scripts | `bash -n` passes |
| TC-004 | Start `run.sh` | Dashboard binds to localhost:8765 |
| TC-005 | `/api/health` | Health JSON is returned |
| TC-006 | Upload PDF resume | Record + extracted text |
| TC-007 | Upload DOCX resume | Record + extracted text |
| TC-008 | Upload TXT resume | Record + exact extracted text |
| TC-009 | Unsupported resume type | HTTP 400 |
| TC-010 | Add valid job URL | Job created |
| TC-011 | Re-add same URL | No duplicate |
| TC-012 | Two resume scores 80/65 | 80-point resume selected |
| TC-013 | Ollama unavailable | Clear error; no fake score |
| TC-014 | Grounded generation | Only supplied facts |
| TC-015 | Unknown fact | Empty, not invented |
| TC-016 | Persistent browser launch | Same browser profile directory |
| TC-017 | Text form input | Correct value filled |
| TC-018 | Resume file input | Selected resume uploaded |
| TC-019 | Select control | Correct known option selected |
| TC-020 | Unknown field | Left untouched |
| TC-021 | CAPTCHA | Blocked |
| TC-022 | MFA/verification code | Blocked |
| TC-023 | Legal attestation | Blocked |
| TC-024 | Background-check authorization | Blocked |
| TC-025 | SSN/government ID | Blocked |
| TC-026 | Date of birth | Blocked |
| TC-027 | Demographic/self-ID | Blocked |
| TC-028 | Payment | Blocked |
| TC-029 | Approve application | Status + approval hash saved |
| TC-030 | Edit after approval | Approval cleared |
| TC-031 | Submit without approval | Blocked |
| TC-032 | Tamper with fields after approval | Hash mismatch blocks |
| TC-033 | Two submit buttons | Blocked |
| TC-034 | No submit button | Blocked |
| TC-035 | One submit button + valid approval | Submit permitted |
| TC-036 | Inspect SQLite | No secrets |
| TC-037 | Inspect logs | No secrets |
| TC-038 | Restart app | DB/browser profile persist |
| TC-039 | Custom role/location | Search templates receive encoded values |
| TC-040 | Duplicate scan results | No duplicate jobs |

## Negative Tests

- Corrupt PDF.
- Corrupt DOCX.
- Empty resume.
- Empty job description.
- Malformed LLM JSON.
- Missing score from LLM.
- Score outside 0–100.
- Browser timeout.
- Login wall.
- Multiple Apply buttons.
- Ambiguous Apply button.
- Missing resume file.
- Missing selected resume.
- Missing job.
- Missing application.
- Missing approval hash.
- Field edit after approval.
- Protected phrase appearing only as irrelevant job-description text.

## Security/Privacy Tests

Verify the application never persists:
- passwords;
- cookies;
- browser storage;
- MFA codes;
- SSN;
- passport numbers;
- driver's license numbers;
- API tokens.

Also test false positives: ordinary text that merely mentions concepts such as “background-check systems” should not automatically block an unrelated application form.

## Manual Browser Matrix

Test:
1. Greenhouse-style form.
2. Lever-style form.
3. Multi-page application.
4. Required select.
5. File upload.
6. One obvious submit button.
7. Multiple submit buttons.
8. CAPTCHA interstitial.
9. MFA prompt.
10. Legal/attestation page.

## Release Gate

All P0 automated tests, safety tests, static checks, and at least one normal + one protected-flow manual browser test must pass before release.

## Commands

```bash
cd ~/hectiCat
python -m pytest -q
bash -n ~/Downloads/hectiCat-OneClick.command
bash -n ~/hectiCat/run.sh
bash -n ~/hectiCat/doctor.sh
bash -n ~/hectiCat/launch.command
```
