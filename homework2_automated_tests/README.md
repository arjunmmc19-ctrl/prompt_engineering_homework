# OSCS Scheduling Test Automation (Homework 2 follow-up)

This folder turns the highest-priority **scheduling** test cases from
`Homework2_TestCases_UserStories_APISpecs.md` into executable, self-contained
`pytest` tests, run against synthetic data.

There is no real ABC Health Care application, database, or EHR to connect to.
Instead, `oscs_reference.py` is a small in-memory reference implementation of
the scheduling rules described in `ABC_Health_Care_Outpatient_Scheduling_PRD.pdf`
(appointment booking, conflict detection, lifecycle state machine, waitlist
offers, and role-based access control). The tests exercise that reference
implementation, so they run entirely locally with no network access.

**No real patient or clinic data is used anywhere in this folder** — every
name, ID, and record in `conftest.py` is fabricated for testing purposes only.

## Files

| File | Purpose |
|---|---|
| `oscs_reference.py` | In-memory "system under test": appointment booking, conflict checks, lifecycle state machine, waitlist manager, RBAC. |
| `conftest.py` | Reusable pytest fixtures: synthetic patients, providers, locations, resources, visit types, users/roles, and a deterministic clock. |
| `test_scheduling.py` | The automated test cases (see mapping below). |
| `README.md` | This file. |

## Test case → original Homework 2 test case mapping

| # | pytest test(s) | Homework 2 Test Case ID(s) | PRD FR |
|---|---|---|---|
| 1 | `test_eligible_appointment_booking_succeeds` | TC-FR003-01 | FR-003 |
| 2 | `test_double_booking_is_prevented` | TC-FR003-01 (step 3) | FR-003, FR-104 |
| 3 | `test_reschedule_within_policy_window_succeeds`, `test_reschedule_outside_policy_window_is_rejected` | TC-FR004-01 (variant) | FR-004 |
| 4 | `test_cancellation_with_reason_is_recorded` | TC-FR004-01 | FR-004 |
| 5 | `test_waitlist_offer_sent_when_slot_opens` | TC-FR105-01 | FR-105 |
| 6 | `test_resource_conflict_detection` | TC-FR104-01 | FR-104 |
| 7 | `test_scheduling_eligibility_constraint_failure` | TC-FR107-01 | FR-107 |
| 8 | `test_valid_appointment_lifecycle_transitions` | TC-FR108-01 | FR-108 |
| 9 | `test_invalid_appointment_lifecycle_transition_rejected` | TC-FR108-02 | FR-108 |
| 10 | `test_rbac_denies_unauthorized_role`, `test_rbac_grants_authorized_role`, `test_rbac_report_export_restricted_to_clinic_manager` | TC-SEC-01, TC-FR503-01 | PRD Section 7 (RBAC), FR-603 |

Two tests (#3 and #10) include an extra negative/positive pair beyond the
single required case, for slightly stronger coverage of the same underlying
rule — they still map to the same original test case IDs.

## How to run the tests

A local virtual environment with `pytest` has already been created at
`../.venv` (one level up, at the repo root). From the repo root:

```bash
source .venv/bin/activate
python -m pytest homework2_automated_tests -v
```

Or, without activating the venv:

```bash
./.venv/bin/python -m pytest homework2_automated_tests -v
```

To run just this folder's tests from inside it:

```bash
cd homework2_automated_tests
../.venv/bin/python -m pytest -v
```

### Useful flags

- `-v` — verbose, one line per test with PASS/FAIL.
- `-k "waitlist"` — run only tests matching a keyword (e.g. `waitlist`, `rbac`, `lifecycle`).
- `--tb=short` — shorter tracebacks on failure.

## Notes on design choices

- **No real backend / no external calls**: `oscs_reference.py` stands in for
  the OSCS system so the PRD's business rules can be asserted against
  directly, without needing a live API, database, or EHR connection.
- **Deterministic time**: time-sensitive rules (reschedule/cancel policy
  windows, waitlist offer expiry) take an explicit `now` parameter instead of
  reading the real system clock, so tests are reproducible and don't need
  `sleep()` or a mocking library.
- **Synthetic data only**: all patients/providers/users in `conftest.py` use
  clearly fabricated names and IDs (e.g. `PAT-1001 "Jane Sample"`).
