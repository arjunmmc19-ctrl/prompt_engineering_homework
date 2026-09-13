"""
conftest.py
------------------------------------------------------------------
Reusable synthetic data fixtures for the OSCS scheduling test suite.

Everything here is fabricated for testing purposes only:
- No real patient names, phone numbers, or medical information.
- No real provider, clinic, or organization data.

Fixtures are intentionally small and readable so each test can be
traced back to the PRD requirement / original test case it exercises.
"""

from datetime import datetime, timedelta

import pytest

from oscs_reference import (
    Location,
    Patient,
    Provider,
    Resource,
    Scheduler,
    User,
    VisitType,
    WaitlistManager,
)


# ---------------------------------------------------------------------------
# A fixed synthetic "now" so all time-window math in the tests is
# deterministic instead of depending on the real wall clock.
# ---------------------------------------------------------------------------

@pytest.fixture
def now():
    return datetime(2026, 1, 15, 9, 0, 0)


# ---------------------------------------------------------------------------
# Locations / Providers / Resources / Visit Types
# ---------------------------------------------------------------------------

@pytest.fixture
def locations():
    return {
        "downtown": Location(id="LOC-1", name="Downtown Test Clinic"),
        "uptown": Location(id="LOC-2", name="Uptown Test Clinic"),
    }


@pytest.fixture
def providers():
    return {
        "adams": Provider(id="PROV-1", name="Dr. Sample Adams"),
        "lee": Provider(id="PROV-2", name="Dr. Sample Lee"),
    }


@pytest.fixture
def resources():
    return {
        "room_101": Resource(id="RES-ROOM-101", name="Room 101", kind="room"),
        "ultrasound_a": Resource(id="RES-EQUIP-US-A", name="Ultrasound Unit A", kind="equipment"),
    }


@pytest.fixture
def visit_types():
    return {
        "routine_checkup": VisitType(
            id="VT-ROUTINE", name="Routine Checkup", duration_minutes=30,
            staff_only=False, requires_referral=False,
        ),
        "complex_care": VisitType(
            id="VT-COMPLEX", name="Complex Care Consultation", duration_minutes=60,
            staff_only=True, requires_referral=False,
        ),
        "new_patient_consult": VisitType(
            id="VT-NEWPATIENT", name="New Patient Consultation", duration_minutes=45,
            staff_only=False, requires_referral=True,
        ),
    }


# ---------------------------------------------------------------------------
# Patients (synthetic only)
# ---------------------------------------------------------------------------

@pytest.fixture
def established_patient():
    return Patient(id="PAT-1001", name="Jane Sample", is_new_patient=False, referral_on_file=False)


@pytest.fixture
def new_patient_no_referral():
    return Patient(id="PAT-1002", name="John Synthetic", is_new_patient=True, referral_on_file=False)


@pytest.fixture
def waitlisted_patient_a():
    return Patient(id="PAT-2001", name="Priority One Testuser", is_new_patient=False, referral_on_file=False)


@pytest.fixture
def waitlisted_patient_b():
    return Patient(id="PAT-2002", name="Priority Two Testuser", is_new_patient=False, referral_on_file=False)


# ---------------------------------------------------------------------------
# Users / Roles (synthetic staff accounts for RBAC tests)
# ---------------------------------------------------------------------------

@pytest.fixture
def users():
    return {
        "clinician": User(id="USR-1", name="Dr. Test Clinician", role="CLINICIAN"),
        "billing": User(id="USR-2", name="Test Billing Staff", role="BILLING"),
        "clinic_manager": User(id="USR-3", name="Test Clinic Manager", role="CLINIC_MANAGER"),
        "front_desk": User(id="USR-4", name="Test Front Desk", role="FRONT_DESK"),
    }


# ---------------------------------------------------------------------------
# System-under-test instances
# ---------------------------------------------------------------------------

@pytest.fixture
def scheduler():
    return Scheduler()


@pytest.fixture
def waitlist_manager():
    return WaitlistManager(default_expiry_minutes=15)


# ---------------------------------------------------------------------------
# Convenience: a standard 30-minute slot starting well beyond any
# reschedule/cancel policy window (used by most booking tests).
# ---------------------------------------------------------------------------

@pytest.fixture
def standard_slot(now):
    start = now + timedelta(days=2, hours=1)  # 49 hours out
    end = start + timedelta(minutes=30)
    return start, end
