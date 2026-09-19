import io
from pathlib import Path

import pytest
from docx import Document
from httpx import ASGITransport, AsyncClient
from pypdf import PdfReader, PdfWriter


@pytest.fixture()
def app_mod(tmp_path, monkeypatch):
    import app as m

    test_base = tmp_path / "hectiCat"
    test_db = test_base / "data" / "hecticat.sqlite3"
    test_browser = test_base / "browser-profile"

    monkeypatch.setattr(m, "BASE", test_base)
    monkeypatch.setattr(m, "DB", test_db)
    monkeypatch.setattr(m, "BROWSER_PROFILE", test_browser)

    test_base.mkdir(parents=True, exist_ok=True)
    test_browser.mkdir(parents=True, exist_ok=True)
    m.resumes_dir().mkdir(parents=True, exist_ok=True)
    m.init_db()
    return m


def create_sample_docx(path: Path, text: str) -> None:
    doc = Document()
    for line in text.split("\n"):
        if line.strip():
            doc.add_paragraph(line)
    doc.save(str(path))


def create_sample_pdf(path: Path, text: str) -> None:
    # Build minimal valid PDF using raw PDF stream syntax
    escaped_text = text.replace("(", "\\(").replace(")", "\\)")
    stream_content = f"BT /F1 12 Tf 72 712 Td ({escaped_text}) Tj ET"
    stream_bytes = stream_content.encode("latin-1")
    length = len(stream_bytes)

    pdf_content = (
        b"%PDF-1.4\n"
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >> >> "
        b"/Contents 4 0 R >> endobj\n"
        b"4 0 obj << /Length " + str(length).encode("ascii") + b" >> stream\n"
        + stream_bytes + b"\nendstream\nendobj\n"
        b"xref\n0 5\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n0000000302 00000 n \n"
        b"trailer << /Size 5 /Root 1 0 R >>\nstartxref\n450\n%%EOF\n"
    )
    path.write_bytes(pdf_content)


def test_extract_text_txt(app_mod, tmp_path):
    txt_file = tmp_path / "resume.txt"
    sample_text = "John Doe\nSoftware Engineer\nPython, FastAPI, SQLite"
    txt_file.write_text(sample_text, encoding="utf-8")

    extracted = app_mod.extract_text(txt_file)
    assert extracted == sample_text


def test_extract_text_docx(app_mod, tmp_path):
    docx_file = tmp_path / "resume.docx"
    sample_text = "Jane Smith\nData Engineer\nETL, Spark, SQL"
    create_sample_docx(docx_file, sample_text)

    extracted = app_mod.extract_text(docx_file)
    assert "Jane Smith" in extracted
    assert "Data Engineer" in extracted
    assert "ETL, Spark, SQL" in extracted


def test_extract_text_pdf(app_mod, tmp_path):
    pdf_file = tmp_path / "resume.pdf"
    sample_text = "Alan Turing - Computer Scientist"
    create_sample_pdf(pdf_file, sample_text)

    extracted = app_mod.extract_text(pdf_file)
    assert "Alan Turing" in extracted


def test_extract_text_unsupported(app_mod, tmp_path):
    img_file = tmp_path / "resume.png"
    img_file.write_bytes(b"\x89PNG\r\n\x1a\n")

    with pytest.raises(ValueError, match="Unsupported resume format"):
        app_mod.extract_text(img_file)


@pytest.mark.asyncio
async def test_upload_txt_resume(app_mod):
    client = AsyncClient(
        transport=ASGITransport(app=app_mod.app),
        base_url="http://127.0.0.1:8765",
    )
    file_content = b"Alex Developer\nStaff Engineer\nPython, Rust, AWS"
    files = {"file": ("my_resume.txt", io.BytesIO(file_content), "text/plain")}

    response = await client.post("/resumes/upload", files=files, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"

    # Verify database persistence
    c = app_mod.db()
    row = c.execute("SELECT * FROM resumes WHERE filename = 'my_resume.txt'").fetchone()
    c.close()

    assert row is not None
    assert row["name"] == "my_resume"
    assert "Alex Developer" in row["text"]
    assert row["active"] == 1

    # Verify stored on disk
    saved_file = app_mod.resumes_dir() / "my_resume.txt"
    assert saved_file.exists()
    assert saved_file.read_bytes() == file_content


@pytest.mark.asyncio
async def test_upload_json_response(app_mod):
    client = AsyncClient(
        transport=ASGITransport(app=app_mod.app),
        base_url="http://127.0.0.1:8765",
    )
    file_content = b"Grace Hopper\nCompiler Pioneer"
    files = {"file": ("hopper.txt", io.BytesIO(file_content), "text/plain")}

    response = await client.post(
        "/resumes/upload",
        files=files,
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["name"] == "hopper"
    assert data["filename"] == "hopper.txt"
    assert data["text_length"] > 0


@pytest.mark.asyncio
async def test_upload_docx_resume(app_mod, tmp_path):
    docx_file = tmp_path / "uploaded.docx"
    create_sample_docx(docx_file, "Ada Lovelace\nAlgorithm Designer")

    client = AsyncClient(
        transport=ASGITransport(app=app_mod.app),
        base_url="http://127.0.0.1:8765",
    )
    files = {
        "file": (
            "uploaded.docx",
            io.BytesIO(docx_file.read_bytes()),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    }

    response = await client.post("/resumes/upload", files=files, follow_redirects=False)
    assert response.status_code == 303

    c = app_mod.db()
    row = c.execute("SELECT * FROM resumes WHERE filename = 'uploaded.docx'").fetchone()
    c.close()

    assert row is not None
    assert "Ada Lovelace" in row["text"]


@pytest.mark.asyncio
async def test_upload_pdf_resume(app_mod, tmp_path):
    pdf_file = tmp_path / "uploaded.pdf"
    create_sample_pdf(pdf_file, "Claude Shannon - Information Theorist")

    client = AsyncClient(
        transport=ASGITransport(app=app_mod.app),
        base_url="http://127.0.0.1:8765",
    )
    files = {
        "file": (
            "uploaded.pdf",
            io.BytesIO(pdf_file.read_bytes()),
            "application/pdf",
        )
    }

    response = await client.post("/resumes/upload", files=files, follow_redirects=False)
    assert response.status_code == 303

    c = app_mod.db()
    row = c.execute("SELECT * FROM resumes WHERE filename = 'uploaded.pdf'").fetchone()
    c.close()

    assert row is not None
    assert "Claude Shannon" in row["text"]


@pytest.mark.asyncio
async def test_upload_unsupported_format_returns_400(app_mod):
    client = AsyncClient(
        transport=ASGITransport(app=app_mod.app),
        base_url="http://127.0.0.1:8765",
    )
    files = {"file": ("malicious.exe", io.BytesIO(b"MZ..."), "application/octet-stream")}

    response = await client.post("/resumes/upload", files=files)
    assert response.status_code == 400
    assert "Unsupported resume format" in response.text


@pytest.mark.asyncio
async def test_upload_updates_existing_filename(app_mod):
    client = AsyncClient(
        transport=ASGITransport(app=app_mod.app),
        base_url="http://127.0.0.1:8765",
    )
    files_v1 = {"file": ("profile.txt", io.BytesIO(b"Version 1"), "text/plain")}
    await client.post("/resumes/upload", files=files_v1)

    files_v2 = {"file": ("profile.txt", io.BytesIO(b"Version 2 Updated"), "text/plain")}
    await client.post("/resumes/upload", files=files_v2)

    c = app_mod.db()
    rows = c.execute("SELECT * FROM resumes WHERE filename = 'profile.txt'").fetchall()
    c.close()

    assert len(rows) == 1
    assert "Version 2 Updated" in rows[0]["text"]


def test_auto_import_resumes(app_mod):
    # Drop files directly into the resumes directory
    rdir = app_mod.resumes_dir()
    (rdir / "external_lead.txt").write_text("Lead Engineer external resume")

    docx_path = rdir / "external_consultant.docx"
    create_sample_docx(docx_path, "Consultant Resume")

    pdf_path = rdir / "external_director.pdf"
    create_sample_pdf(pdf_path, "Director Resume")

    imported = app_mod.auto_import_resumes()
    assert imported == 3

    # Re-running auto-import should not duplicate
    assert app_mod.auto_import_resumes() == 0

    c = app_mod.db()
    rows = c.execute("SELECT name, filename FROM resumes ORDER BY name").fetchall()
    c.close()

    names = {r["name"] for r in rows}
    assert "external_lead" in names
    assert "external_consultant" in names
    assert "external_director" in names


@pytest.mark.asyncio
async def test_api_resumes_endpoints(app_mod):
    c = app_mod.db()
    c.execute(
        "INSERT INTO resumes(name, filename, text, active, created_at) VALUES(?, ?, ?, 1, ?)",
        ("API Resume", "api_resume.txt", "API Developer with FastAPI skills", app_mod.now()),
    )
    c.commit()
    rid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    c.close()

    client = AsyncClient(
        transport=ASGITransport(app=app_mod.app),
        base_url="http://127.0.0.1:8765",
    )

    # List endpoint
    list_res = await client.get("/api/resumes")
    assert list_res.status_code == 200
    resumes_list = list_res.json()
    assert len(resumes_list) >= 1
    assert any(r["id"] == rid for r in resumes_list)

    # Detail endpoint
    detail_res = await client.get(f"/api/resumes/{rid}")
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["name"] == "API Resume"
    assert "FastAPI" in detail["text"]

    # Missing detail
    missing_res = await client.get("/api/resumes/99999")
    assert missing_res.status_code == 404


@pytest.mark.asyncio
async def test_workspace_renders_resume_library(app_mod):
    """GET / (user workspace) should display the Resume Library section."""
    c = app_mod.db()
    c.execute(
        "INSERT INTO resumes(name, filename, text, active, created_at) VALUES(?, ?, ?, 1, ?)",
        ("DevOps Specialist", "devops.txt", "Kubernetes, Terraform, CI/CD", app_mod.now()),
    )
    c.commit()
    c.close()

    client = AsyncClient(
        transport=ASGITransport(app=app_mod.app),
        base_url="http://127.0.0.1:8765",
    )

    # User workspace at /
    res = await client.get("/")
    assert res.status_code == 200
    content = res.text
    assert "Resume Library" in content
    assert "DevOps Specialist" in content
    assert "devops.txt" in content
    assert "Kubernetes, Terraform, CI/CD" in content
    assert "Upload &amp; Extract Text" in content
    assert "hectiCat — Workspace" in content

    # Admin dashboard at /admin
    admin_res = await client.get("/admin")
    assert admin_res.status_code == 200
    admin_content = admin_res.text
    assert "System Admin" in admin_content
    assert "Local Health" in admin_content
    assert "Resume Library" in admin_content
