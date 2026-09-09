"""
Homework 2: Test Cases, User Stories, and API Specifications
using Prompt Engineering
------------------------------------------------------------------
Source document: ABC_Health_Care_Outpatient_Scheduling_PRD.pdf

This script does NOT invent requirements. It reads the PRD (already extracted
into PRD_extracted_text.txt as plain text) and inserts that text into three
separate, carefully written prompts. Each prompt asks Gemini for one specific
deliverable, grounded only in what the PRD actually says:

  Prompt A -> A. Test Cases
  Prompt B -> B. User Stories (with acceptance criteria)
  Prompt C -> C. API Specifications

All three prompts and their generated results are saved together into one
organized Markdown file so the prompts and outputs stay easy to trace back to
each other and to the PRD's FR-IDs.

This script reuses the same approach as Homework 1:
  - Read GOOGLE_GENAI_API_KEY from my_test_chat_app/.env.local (read-only,
    never printed).
  - Call Gemini via the plain REST API (no extra pip installs needed).
  - Try Gemini 3.5 Flash first, then fall back to other known-good models,
    reporting each failure before moving to the next model.
"""

import json
import socket
import time
import urllib.error
import urllib.request

PRD_TEXT_FILE = "PRD_extracted_text.txt"
OUTPUT_FILE = "Homework2_TestCases_UserStories_APISpecs.md"

# Read-only reference to the main app's API key file. Nothing in
# my_test_chat_app is ever modified by this script.
ENV_FILE = "/Users/mallikarjunchunduru/Desktop/my_test_chat_app/.env.local"
ENV_KEY_NAME = "GOOGLE_GENAI_API_KEY"

MODEL_CANDIDATES = ["gemini-3.5-flash", "gemini-3-flash-preview", "gemini-3.6-flash"]

GEMINI_URL_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

# Generating a "complete" set of test cases/user stories/API specs from a
# full PRD is a large request - give it more time than a short chat reply.
REQUEST_TIMEOUT_SECONDS = 240


# ---------------------------------------------------------------------------
# Shared helpers (same pattern as Homework 1)
# ---------------------------------------------------------------------------

def load_prd_text(path):
    """Reads the plain-text version of the PRD (already extracted from the PDF)."""
    with open(path, encoding="utf-8") as f:
        return f.read()


def load_api_key(env_path):
    """Reads GOOGLE_GENAI_API_KEY out of a .env-style file. Never prints it."""
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line.startswith(f"{ENV_KEY_NAME}="):
                return line.split("=", 1)[1].strip()
    raise RuntimeError(f"{ENV_KEY_NAME} not found in {env_path}")


def describe_error(http_status, message):
    """Turns a raw HTTP status + error message into a short, friendly reason."""
    if http_status == 429:
        return "rate limit / quota exceeded"
    if http_status == 503:
        return "model temporarily overloaded"
    if http_status == 404:
        return "model not found / not available"
    if http_status == 400:
        return f"request rejected ({message})"
    return f"HTTP {http_status} error ({message})"


def call_gemini(model, api_key, prompt):
    """Sends the prompt to one Gemini model via the REST API and returns the text."""
    url = GEMINI_URL_TEMPLATE.format(model=model)
    body = json.dumps(
        {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
    ).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
    )

    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            data = json.loads(response.read())
    except urllib.error.HTTPError as err:
        error_body = json.loads(err.read().decode("utf-8"))
        message = error_body.get("error", {}).get("message", str(err))
        raise RuntimeError(describe_error(err.code, message)) from err
    except (urllib.error.URLError, socket.timeout) as err:
        # Long, PRD-sized prompts can take a while to generate a complete
        # answer; treat a slow/dropped connection as a retryable failure
        # instead of letting it crash the whole script.
        raise RuntimeError(f"network/timeout error ({err})") from err

    candidates = data.get("candidates", [])
    if not candidates:
        raise RuntimeError("no candidates returned in the response")

    parts = candidates[0].get("content", {}).get("parts", [])
    if not parts or "text" not in parts[0]:
        raise RuntimeError("model returned an empty response")

    return parts[0]["text"]


RETRIES_PER_MODEL = 2
RETRY_DELAY_SECONDS = 12


def generate_with_fallback(prompt, api_key, label):
    """
    Tries each model in MODEL_CANDIDATES in order. Long PRD-sized prompts
    occasionally hit a transient "model overloaded" (503) error, so each
    model gets a few retries with a short pause before moving on to the
    next model. Every failure is reported, so nothing fails silently.
    """
    print(f"\n--- Generating: {label} ---")
    for model in MODEL_CANDIDATES:
        for attempt in range(1, RETRIES_PER_MODEL + 1):
            print(f"Trying model: {model} (attempt {attempt}/{RETRIES_PER_MODEL}) ...")
            try:
                text = call_gemini(model, api_key, prompt)
                print(f"  Success with {model}.")
                return model, text
            except RuntimeError as err:
                print(f"  {model} failed: {err}")
                if attempt < RETRIES_PER_MODEL:
                    time.sleep(RETRY_DELAY_SECONDS)

    raise RuntimeError(f"All Gemini models were unavailable for {label}.")


# ---------------------------------------------------------------------------
# The three prompts (Prompt A, B, C)
# ---------------------------------------------------------------------------

PROMPT_A_TEMPLATE = """You are a senior QA engineer at ABC Health Care Company, writing test cases for
the Outpatient Patient Scheduling & Care System (OSCS) described in the PRD below.

PRD:
{prd_text}

Task:
Generate a structured set of test cases covering the system's core workflows and
functional requirements (FR-001 through FR-704), including both happy-path and
exception/edge cases (no-shows, overbooking, waitlist expiry, eligibility
failures, invalid state transitions, RBAC violations).

For each test case, output a table with these columns:
- Test Case ID (e.g., TC-FR003-01)
- Related FR ID(s)
- Title
- Preconditions
- Test Steps (numbered)
- Test Data (example values)
- Expected Result
- Priority (High/Medium/Low)

Prioritize the MVP scope workflows first (staff scheduling, patient
self-scheduling, waitlist, intake/check-in, care tasks, audit logs, baseline EHR
sync) before Phase 2 features.

Only use requirements stated in the PRD above. Do not invent features that are
not mentioned in the PRD."""


PROMPT_B_TEMPLATE = """You are a product manager at ABC Health Care Company writing user stories for
the Outpatient Patient Scheduling & Care System (OSCS) described in the PRD below.

PRD:
{prd_text}

Task:
Generate user stories for each of these personas: Patient, Front desk/Scheduling
staff, Clinician, Nurse/Care coordinator, Clinic manager, System admin/IT, and
Billing staff. Cover every functional requirement group (Patient Portal,
Scheduling, Intake/Check-in, Care Management, Communication, Reporting, Admin,
Integrations).

For each user story, use the format:
"As a [persona], I want to [action], so that [benefit]."

Follow each story with:
- Acceptance Criteria (as a bulleted list, in Given/When/Then form where
  applicable)
- Related FR ID(s)

Group the stories by feature module (matching PRD Section 4), and mark which
stories belong to MVP scope vs. Phase 2, based on PRD Section 8.

Only use requirements stated in the PRD above. Do not invent features that are
not mentioned in the PRD."""


PROMPT_C_TEMPLATE = """You are a backend/API architect at ABC Health Care Company designing the API
surface for the Outpatient Patient Scheduling & Care System (OSCS) described in
the PRD below.

PRD:
{prd_text}

Task:
Generate API specifications for the system's core resources, based on the
functional requirements and the data entities in PRD Section 6 (Patient,
Provider, Location, Resource, Appointment, Visit Type, Schedule Template,
Encounter, Intake Form, Consent Document, Care Plan, Task, Message/Notification,
Audit Log, User/Role/Permission).

For each API endpoint, output:
- HTTP Method + Path (e.g., POST /appointments)
- Description
- Related FR ID(s)
- Request parameters/body (with field names, types, required/optional)
- Response schema (success case)
- Key error responses (e.g., 400 eligibility failure, 403 RBAC denial, 409
  scheduling conflict) with status codes and example error bodies
- Auth/role requirements (which persona(s) can call this endpoint)

Organize endpoints into logical groups: Auth, Patient Profile, Availability
Search, Appointments, Waitlist, Provider Schedule, Resources, Visit Types,
Intake/Consents, Check-in, Status Board, Care Plans/Tasks, Notifications,
Messaging, Reporting, Audit Log, Admin/Config, and Integrations. Note that
security requirements (TLS 1.2+, RBAC, audit logging on PHI actions) apply
system-wide, per PRD Section 7.

Only use requirements stated in the PRD above. Do not invent features that are
not mentioned in the PRD."""


def readable_prompt(template):
    """Returns the prompt template with the PRD placeholder shown clearly,
    instead of dumping the entire PRD text into the saved file three times."""
    return template.replace(
        "{prd_text}",
        "<FULL PRD TEXT inserted here at run time - see PRD_extracted_text.txt "
        "or ABC_Health_Care_Outpatient_Scheduling_PRD.pdf for the source>",
    )


if __name__ == "__main__":
    prd_text = load_prd_text(PRD_TEXT_FILE)
    api_key = load_api_key(ENV_FILE)

    prompt_a = PROMPT_A_TEMPLATE.format(prd_text=prd_text)
    prompt_b = PROMPT_B_TEMPLATE.format(prd_text=prd_text)
    prompt_c = PROMPT_C_TEMPLATE.format(prd_text=prd_text)

    model_a, result_a = generate_with_fallback(prompt_a, api_key, "A. Test Cases")
    model_b, result_b = generate_with_fallback(prompt_b, api_key, "B. User Stories")
    model_c, result_c = generate_with_fallback(prompt_c, api_key, "C. API Specifications")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("# Homework 2: Test Cases, User Stories, and API Specifications\n\n")
        f.write("Source PRD: ABC_Health_Care_Outpatient_Scheduling_PRD.pdf\n\n")
        f.write(
            "All three prompts below embed the full PRD text as context, so "
            "the results stay grounded in the actual document instead of "
            "inventing requirements.\n\n"
        )
        f.write("---\n\n")

        f.write("## Prompt A (used to generate Test Cases)\n\n")
        f.write("```\n" + readable_prompt(PROMPT_A_TEMPLATE) + "\n```\n\n")
        f.write(f"## A. Test Cases (generated by {model_a})\n\n")
        f.write(result_a.strip() + "\n\n---\n\n")

        f.write("## Prompt B (used to generate User Stories)\n\n")
        f.write("```\n" + readable_prompt(PROMPT_B_TEMPLATE) + "\n```\n\n")
        f.write(f"## B. User Stories (generated by {model_b})\n\n")
        f.write(result_b.strip() + "\n\n---\n\n")

        f.write("## Prompt C (used to generate API Specifications)\n\n")
        f.write("```\n" + readable_prompt(PROMPT_C_TEMPLATE) + "\n```\n\n")
        f.write(f"## C. API Specifications (generated by {model_c})\n\n")
        f.write(result_c.strip() + "\n")

    print(f"\nSaved combined prompts + results to {OUTPUT_FILE}")
