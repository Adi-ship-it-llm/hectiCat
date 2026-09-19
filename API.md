# hectiCat API Reference

This document provides a complete reference for all existing HTTP API endpoints served by the hectiCat local runtime (`app.py`).

- **Base URL:** `http://127.0.0.1:8765`
- **Network Scope:** Binds strictly to `127.0.0.1` (localhost only).
- **Authentication:** None (secured by local-only loopback binding).
- **Interactive Documentation:**
  - Swagger UI: `http://127.0.0.1:8765/docs`
  - ReDoc: `http://127.0.0.1:8765/redoc`
  - OpenAPI Schema: `http://127.0.0.1:8765/openapi.json`

---

## Endpoint Summary

| Method | Path | Summary | Description |
|---|---|---|---|
| `GET` | `/` | Dashboard UI | Serves the HTML dashboard interface for tracking jobs, health, and resumes. |
| `GET` | `/api/health` | Health Check | Reports status of SQLite DB, browser profile, Ollama, Hermes, and LLM model. |
| `POST` | `/api/shutdown` | Server Shutdown | Gracefully terminates the local uvicorn dashboard process. |
| `POST` | `/api/ollama/start` | Start Ollama Daemon | Silently spawns `ollama serve` in the background if not already running. |
| `POST` | `/resumes/upload` | Upload Resume | Uploads a `.pdf`, `.docx`, or `.txt` resume, extracts text, and stores in SQLite. |
| `GET` | `/api/resumes` | List Resumes | Returns JSON array of all stored resumes with text preview and metadata. |
| `GET` | `/api/resumes/{resume_id}` | Get Resume Detail | Returns full JSON details and complete extracted text for a specific resume. |

---

## Endpoint Details

### 1. Health Diagnostics

#### `GET /api/health`
Checks and reports local runtime readiness and automation dependencies.

- **Request:**
  - Method: `GET`
  - Headers: `Accept: application/json`
  - Parameters: None

- **Response (200 OK):**
  ```json
  {
    "ok": true,
    "service": "hectiCat",
    "version": "0.1.0",
    "model": "qwen3.5:9b",
    "ollama": "http://127.0.0.1:11434",
    "database": "/Users/adi/hectiCat/data/hecticat.sqlite3",
    "browser_profile": "/Users/adi/hectiCat/browser-profile",
    "checks": {
      "database": {
        "ok": true,
        "label": "Ready",
        "detail": "/Users/adi/hectiCat/data/hecticat.sqlite3"
      },
      "browser_profile": {
        "ok": true,
        "label": "Ready",
        "detail": "/Users/adi/hectiCat/browser-profile"
      },
      "ollama": {
        "ok": true,
        "label": "Available",
        "detail": "http://127.0.0.1:11434"
      },
      "hermes": {
        "ok": true,
        "label": "Available",
        "detail": "/Users/adi/.local/bin/hermes"
      },
      "model": {
        "ok": true,
        "label": "qwen3.5:9b",
        "detail": "Model is installed."
      }
    }
  }
  ```

- **Example curl:**
  ```bash
  curl -s http://127.0.0.1:8765/api/health
  ```

---

### 2. Process Management

#### `POST /api/shutdown`
Stops the local dashboard server gracefully. A background task sends `SIGTERM` to the process 0.5s after returning the HTTP response.

- **Request:**
  - Method: `POST`
  - Parameters: None

- **Response (200 OK):**
  ```json
  {
    "ok": true,
    "message": "hectiCat dashboard is shutting down."
  }
  ```

- **Example curl:**
  ```bash
  curl -X POST http://127.0.0.1:8765/api/shutdown
  ```

---

#### `POST /api/ollama/start`
Starts `ollama serve` in the background if the Ollama binary is present on `PATH` and not already responding.

- **Request:**
  - Method: `POST`
  - Parameters: None

- **Responses:**
  - **200 OK (Already running):**
    ```json
    {
      "ok": true,
      "started": false,
      "message": "Ollama is already running."
    }
    ```
  - **200 OK (Successfully launched):**
    ```json
    {
      "ok": true,
      "started": true,
      "ready": true,
      "message": "Ollama is running.",
      "log": "/Users/adi/hectiCat/logs/ollama.log"
    }
    ```
  - **200 OK (Binary missing on system):**
    ```json
    {
      "ok": false,
      "started": false,
      "message": "Ollama is not installed or not on PATH."
    }
    ```

- **Example curl:**
  ```bash
  curl -X POST http://127.0.0.1:8765/api/ollama/start
  ```

---

### 3. Resume Library

#### `POST /resumes/upload`
Uploads a resume file (`.pdf`, `.docx`, or `.txt`), saves the file to the local resumes directory (`~/hectiCat/resumes/`), extracts plain text from all pages/paragraphs, and persists the record into the SQLite database.

- **Request:**
  - Method: `POST`
  - Content-Type: `multipart/form-data`
  - Body:
    - `file` (binary, required): The resume document file.
  - Headers:
    - `Accept: application/json` (optional): If present, returns a JSON object instead of an HTTP 303 redirect.

- **Responses:**
  - **303 See Other (Default for browser form submission):**
    - Header: `Location: /`
  - **200 OK (When `Accept: application/json` header is supplied):**
    ```json
    {
      "ok": true,
      "id": 1,
      "name": "Jane_Doe_Resume",
      "filename": "Jane_Doe_Resume.pdf",
      "text_length": 3420
    }
    ```
  - **400 Bad Request (Validation failure):**
    - Missing file or empty filename:
      ```json
      {
        "detail": "No file provided."
      }
      ```
    - Unsupported file extension:
      ```json
      {
        "detail": "Unsupported resume format '.png'. Supported formats: .pdf, .docx, .txt"
      }
      ```
    - Corrupted or unreadable document:
      ```json
      {
        "detail": "Failed to extract text from resume.pdf: [error details]"
      }
      ```

- **Example curl (JSON response):**
  ```bash
  curl -X POST http://127.0.0.1:8765/resumes/upload \
    -H "Accept: application/json" \
    -F "file=@/path/to/my_resume.pdf"
  ```

---

#### `GET /api/resumes`
Retrieves a list of all stored resumes ordered by newest first. Includes text length and a 250-character preview.

- **Request:**
  - Method: `GET`
  - Parameters: None

- **Response (200 OK):**
  ```json
  [
    {
      "id": 2,
      "name": "Alex_Cloud_Resume",
      "filename": "Alex_Cloud_Resume.docx",
      "active": true,
      "created_at": "2026-09-18T10:15:00+00:00",
      "text_length": 2100,
      "text_preview": "Alex Cloud\nSenior Systems Architect\nExperience:\nAWS, Kubernetes, Terraform..."
    },
    {
      "id": 1,
      "name": "Alex_Data_Resume",
      "filename": "Alex_Data_Resume.pdf",
      "active": true,
      "created_at": "2026-09-18T09:00:00+00:00",
      "text_length": 3420,
      "text_preview": "Alex Data\nData Engineer\nExperience:\nPython, Apache Spark, SQL..."
    }
  ]
  ```

- **Example curl:**
  ```bash
  curl -s http://127.0.0.1:8765/api/resumes
  ```

---

#### `GET /api/resumes/{resume_id}`
Retrieves full details and complete extracted text for a specific resume.

- **Request:**
  - Method: `GET`
  - Path Parameter:
    - `resume_id` (integer, required): The ID of the resume in SQLite.

- **Responses:**
  - **200 OK:**
    ```json
    {
      "id": 1,
      "name": "Alex_Data_Resume",
      "filename": "Alex_Data_Resume.pdf",
      "text": "Alex Data\nData Engineer\nLocation: San Francisco, CA\n\nExperience:\nStaff Data Engineer at Example Corp...",
      "active": true,
      "created_at": "2026-09-18T09:00:00+00:00"
    }
    ```
  - **404 Not Found:**
    ```json
    {
      "detail": "Resume not found."
    }
    ```

- **Example curl:**
  ```bash
  curl -s http://127.0.0.1:8765/api/resumes/1
  ```

---

### 4. Web Dashboard Interface

#### `GET /`
Serves the HTML dashboard user interface.

- **Request:**
  - Method: `GET`
  - Parameters: None

- **Response (200 OK):**
  - Content-Type: `text/html; charset=utf-8`
  - Renders:
    - Runtime status indicator (Ready / Needs attention)
    - Application tracker metrics (Tracked jobs, Active resumes, Draft applications, Submitted applications)
    - Quick actions (Refresh, Health link, Start Ollama, Stop dashboard)
    - Local Health dependency checks grid
    - Resume Library (file upload form, table of resumes with character/word metrics and collapsible extracted text preview drawers)
    - Application Pipeline workflow stages
    - Recent Activity & directory paths reference

- **Example curl:**
  ```bash
  curl -s http://127.0.0.1:8765/
  ```

---

### 5. Standard OpenAPI & Documentation Endpoints

FastAPI exposes the following OpenAPI endpoints automatically:

- `GET /openapi.json` — Returns the complete OpenAPI 3.1.0 JSON schema.
- `GET /docs` — Interactive Swagger UI documentation.
- `GET /redoc` — ReDoc visual documentation.
