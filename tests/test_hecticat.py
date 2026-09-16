import json
import pytest


@pytest.fixture()
def mod(tmp_path, monkeypatch):
    import app as m

    monkeypatch.setattr(m, "BASE", tmp_path / "hectiCat")
    monkeypatch.setattr(m, "DB", tmp_path / "hecticat.sqlite3")
    monkeypatch.setattr(m, "PROFILE_JSON", tmp_path / "profile.json")
    monkeypatch.setattr(m, "BROWSER_PROFILE", tmp_path / "browser-profile")
    m.BROWSER_PROFILE.mkdir(parents=True, exist_ok=True)
    m.init_db()
    return m


def test_database_has_approval_hash(mod):
    c = mod.db()
    cols = {r["name"] for r in c.execute("PRAGMA table_info(applications)")}
    c.close()
    assert "approved_hash" in cols


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Please enter your SSN", "government ID"),
        ("Date of Birth", "date of birth"),
        ("Enter verification code", "2FA / MFA"),
        ("I attest that the above is true", "legal attestation"),
        ("Enter passport number", "government ID"),
    ],
)
def test_safety_reason_detects_high_risk_fields(mod, text, expected):
    assert mod.safety_reason(text) == expected


def test_safety_reason_allows_normal_text(mod):
    assert mod.safety_reason("What programming languages do you use?") is None


def test_form_matching_aliases(mod):
    fields = {
        "full_name": "Ada Lovelace",
        "email": "ada@example.com",
        "phone": "555-0100",
    }
    assert mod.match_form_value("Applicant Full Name", fields) == "Ada Lovelace"
    assert mod.match_form_value("Contact E-mail", fields) == "ada@example.com"
    assert mod.match_form_value("Mobile Telephone", fields) == "555-0100"


def test_form_matching_direct_key(mod):
    fields = {"portfolio": "https://example.com"}
    assert mod.match_form_value("portfolio URL", fields) == "https://example.com"


def test_parse_job_text(mod):
    source, company, title, body = mod.parse_job_text(
        "https://example.com/jobs/123",
        "Senior Data Engineer - Example Corp",
        "Location: New York, NY\nBuild pipelines."
    )
    assert source == "example.com"
    assert company == "Example Corp"
    assert title == "Senior Data Engineer"
    assert "Build pipelines" in body


def test_profile_round_trip(mod):
    path = mod.BASE / "profile.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "full_name": "Test User",
        "target_role": "Data Engineer",
    }))
    mod.set_profile_from_json(path)
    p = mod.profile()
    assert p["full_name"] == "Test User"
    assert p["target_role"] == "Data Engineer"


def _seed_application(mod, fields, status="ready_for_review", approved_hash=None):
    c = mod.db()
    c.execute(
        "INSERT INTO jobs(source,url,title,description,requirements,discovered_at) "
        "VALUES(?,?,?,?,?,?)",
        ("example.com", "https://example.com/job/1", "Data Engineer",
         "desc", "req", mod.now()),
    )
    jid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    c.execute(
        "INSERT INTO resumes(name,filename,text,created_at) VALUES(?,?,?,?)",
        ("r1", "r1.pdf", "resume", mod.now()),
    )
    rid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    c.execute(
        "INSERT INTO applications("
        "job_id,resume_id,status,fields_json,created_at,approved_hash"
        ") VALUES(?,?,?,?,?,?)",
        (jid, rid, status, json.dumps(fields), mod.now(), approved_hash),
    )
    aid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    c.commit()
    c.close()
    return aid


def test_approval_hash_changes_when_fields_change(mod):
    aid = _seed_application(mod, {"full_name": "Test User"})
    first = mod.approval_hash(aid)

    c = mod.db()
    c.execute(
        "UPDATE applications SET fields_json=? WHERE id=?",
        (json.dumps({"full_name": "Changed User"}), aid),
    )
    c.commit()
    c.close()

    second = mod.approval_hash(aid)
    assert first
    assert second
    assert first != second


def test_edit_after_approval_clears_approval_state(mod):
    aid = _seed_application(
        mod,
        {"email": "a@example.com"},
        status="approved_for_submission",
        approved_hash="abc",
    )
    c = mod.db()
    c.execute(
        "UPDATE applications "
        "SET fields_json=?, status='ready_for_review', approved_hash=NULL "
        "WHERE id=?",
        (json.dumps({"email": "b@example.com"}), aid),
    )
    c.commit()
    row = c.execute(
        "SELECT status,approved_hash FROM applications WHERE id=?", (aid,)
    ).fetchone()
    c.close()

    assert row["status"] == "ready_for_review"
    assert row["approved_hash"] is None


@pytest.mark.asyncio
async def test_llm_json_parses_local_response(mod, monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "message": {
                    "content": '{"overall_score":91,"recommendation":"match"}'
                }
            }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(
        mod.httpx,
        "AsyncClient",
        lambda *args, **kwargs: FakeClient(),
    )
    result = await mod.llm_json("system", "user")
    assert result["overall_score"] == 91
    assert result["recommendation"] == "match"
