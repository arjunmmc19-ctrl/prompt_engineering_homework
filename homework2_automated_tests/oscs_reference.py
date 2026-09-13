"""
oscs_reference.py
------------------------------------------------------------------
A small, self-contained, in-memory reference implementation of the
scheduling-related business rules described in the PRD
(ABC_Health_Care_Outpatient_Scheduling_PRD.pdf) and exercised by the
test cases in Homework2_TestCases_UserStories_APISpecs.md.

There is no real OSCS application, database, or EHR to test against,
so this module plays the role of "the system under test": it
implements just enough logic (appointment booking, conflict
detection, lifecycle state transitions, waitlist offers, and RBAC)
for the pytest suite in test_scheduling.py to make real,
non-trivial PASS/FAIL assertions against.

Only synthetic data is ever constructed here; nothing in this file
touches a real patient, real PHI, or any external service.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import count
from typing import Optional


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class SchedulingConflictError(Exception):
    """Raised when a provider is already booked for the requested time (FR-003)."""


class ResourceConflictError(Exception):
    """Raised when a required room/equipment resource is already in use (FR-104)."""


class ReschedulePolicyViolation(Exception):
    """Raised when a reschedule/cancel is attempted outside the policy window (FR-004)."""


class InvalidStateTransitionError(Exception):
    """Raised when an appointment lifecycle transition is not allowed (FR-108)."""


class RBACDeniedError(Exception):
    """Raised when a user's role lacks the permission for an action (PRD Section 7 / FR-603)."""


# ---------------------------------------------------------------------------
# Appointment lifecycle state machine (FR-108)
# ---------------------------------------------------------------------------

REQUESTED = "Requested"
SCHEDULED = "Scheduled"
CONFIRMED = "Confirmed"
CHECKED_IN = "Checked-in"
IN_ROOM = "In-room"
COMPLETED = "Completed"
CANCELLED = "Cancelled"
NO_SHOW = "No-show"

VALID_TRANSITIONS = {
    REQUESTED: {SCHEDULED, CANCELLED},
    SCHEDULED: {CONFIRMED, CANCELLED, NO_SHOW},
    CONFIRMED: {CHECKED_IN, CANCELLED, NO_SHOW},
    CHECKED_IN: {IN_ROOM, CANCELLED},
    IN_ROOM: {COMPLETED},
    COMPLETED: set(),
    CANCELLED: set(),
    NO_SHOW: set(),
}


# ---------------------------------------------------------------------------
# Synthetic domain entities
# ---------------------------------------------------------------------------

@dataclass
class Location:
    id: str
    name: str


@dataclass
class Provider:
    id: str
    name: str


@dataclass
class Resource:
    id: str
    name: str
    kind: str  # "room" or "equipment"


@dataclass
class VisitType:
    id: str
    name: str
    duration_minutes: int
    staff_only: bool = False
    requires_referral: bool = False


@dataclass
class Patient:
    id: str
    name: str
    is_new_patient: bool = False
    referral_on_file: bool = False


@dataclass
class User:
    id: str
    name: str
    role: str  # PATIENT, FRONT_DESK, CLINICIAN, NURSE, CLINIC_MANAGER, SYS_ADMIN, BILLING


@dataclass
class AuditLogEntry:
    actor_id: str
    action: str
    timestamp: datetime
    detail: str = ""


_appointment_ids = count(1)


@dataclass
class Appointment:
    patient_id: str
    provider_id: str
    location_id: str
    visit_type_id: str
    start: datetime
    end: datetime
    resource_ids: list = field(default_factory=list)
    state: str = REQUESTED
    pending_review: bool = False
    review_reason: Optional[str] = None
    cancellation_reason_code: Optional[str] = None
    cancellation_free_text: Optional[str] = None
    id: str = field(default_factory=lambda: f"APT-{next(_appointment_ids)}")
    audit_log: list = field(default_factory=list)

    def _log(self, actor_id: str, action: str, timestamp: datetime, detail: str = "") -> None:
        self.audit_log.append(AuditLogEntry(actor_id, action, timestamp, detail))


@dataclass
class WaitlistEntry:
    patient_id: str
    provider_id: str
    priority: int  # lower number = higher priority


@dataclass
class WaitlistOffer:
    patient_id: str
    provider_id: str
    offered_at: datetime
    expiry_minutes: int
    status: str = "Offered"  # Offered, Accepted, Expired


# ---------------------------------------------------------------------------
# Scheduler: booking, conflicts, reschedule, cancel, lifecycle transitions
# ---------------------------------------------------------------------------

class Scheduler:
    """Holds the currently booked appointments and enforces PRD scheduling rules."""

    def __init__(self):
        self.appointments: list[Appointment] = []

    def _overlaps(self, start_a, end_a, start_b, end_b) -> bool:
        return start_a < end_b and start_b < end_a

    def _provider_conflict(self, provider_id, start, end, exclude_id=None) -> bool:
        for appt in self.appointments:
            if appt.id == exclude_id or appt.state == CANCELLED:
                continue
            if appt.provider_id == provider_id and self._overlaps(start, end, appt.start, appt.end):
                return True
        return False

    def _resource_conflict(self, resource_ids, start, end, exclude_id=None) -> Optional[str]:
        if not resource_ids:
            return None
        for appt in self.appointments:
            if appt.id == exclude_id or appt.state == CANCELLED:
                continue
            if not self._overlaps(start, end, appt.start, appt.end):
                continue
            clash = set(resource_ids) & set(appt.resource_ids)
            if clash:
                return next(iter(clash))
        return None

    def check_eligibility(self, patient: Patient, visit_type: VisitType) -> tuple[bool, Optional[str]]:
        """FR-107: new-patient-without-referral fails eligibility for referral-gated visit types."""
        if visit_type.requires_referral and patient.is_new_patient and not patient.referral_on_file:
            return False, "New patient requires a physician referral on file before booking."
        return True, None

    def book_appointment(
        self,
        patient: Patient,
        provider: Provider,
        location: Location,
        visit_type: VisitType,
        start: datetime,
        end: datetime,
        resource_ids: Optional[list] = None,
        actor_id: str = "SYSTEM",
    ) -> Appointment:
        resource_ids = resource_ids or []

        if self._provider_conflict(provider.id, start, end):
            raise SchedulingConflictError(
                f"Provider {provider.id} already has an appointment overlapping {start}-{end}."
            )

        clash = self._resource_conflict(resource_ids, start, end)
        if clash:
            raise ResourceConflictError(f"Resource {clash} is already booked for {start}-{end}.")

        eligible, reason = self.check_eligibility(patient, visit_type)

        appt = Appointment(
            patient_id=patient.id,
            provider_id=provider.id,
            location_id=location.id,
            visit_type_id=visit_type.id,
            start=start,
            end=end,
            resource_ids=list(resource_ids),
            state=SCHEDULED if eligible else REQUESTED,
            pending_review=not eligible,
            review_reason=reason,
        )
        appt._log(actor_id, "BOOKED", start, detail="eligible" if eligible else f"routed_to_review: {reason}")
        self.appointments.append(appt)
        return appt

    def reschedule_appointment(
        self,
        appt: Appointment,
        new_start: datetime,
        new_end: datetime,
        now: datetime,
        policy_hours: int = 24,
        actor_id: str = "PATIENT",
    ) -> Appointment:
        if appt.start - now < timedelta(hours=policy_hours):
            raise ReschedulePolicyViolation(
                f"Reschedule must occur more than {policy_hours}h before the appointment start."
            )
        if self._provider_conflict(appt.provider_id, new_start, new_end, exclude_id=appt.id):
            raise SchedulingConflictError("Requested reschedule time conflicts with another appointment.")

        old_start = appt.start
        appt.start, appt.end = new_start, new_end
        appt._log(actor_id, "RESCHEDULED", now, detail=f"from {old_start} to {new_start}")
        return appt

    def cancel_appointment(
        self,
        appt: Appointment,
        reason_code: str,
        now: datetime,
        free_text: str = "",
        policy_hours: int = 24,
        actor_id: str = "PATIENT",
        waitlist_manager: Optional["WaitlistManager"] = None,
    ) -> Optional[WaitlistOffer]:
        if appt.start - now < timedelta(hours=policy_hours):
            raise ReschedulePolicyViolation(
                f"Cancellation must occur more than {policy_hours}h before the appointment start."
            )

        appt.state = CANCELLED
        appt.cancellation_reason_code = reason_code
        appt.cancellation_free_text = free_text
        appt._log(actor_id, "CANCELLED", now, detail=reason_code)

        if waitlist_manager is not None:
            return waitlist_manager.offer_slot(appt.provider_id, now)
        return None

    def transition_state(
        self, appt: Appointment, new_state: str, now: datetime, actor_id: str = "STAFF"
    ) -> Appointment:
        allowed = VALID_TRANSITIONS.get(appt.state, set())
        if new_state not in allowed:
            raise InvalidStateTransitionError(
                f"Invalid state transition from {appt.state} to {new_state}."
            )
        old_state = appt.state
        appt.state = new_state
        appt._log(actor_id, "STATE_CHANGE", now, detail=f"{old_state} -> {new_state}")
        return appt


# ---------------------------------------------------------------------------
# Waitlist (FR-105)
# ---------------------------------------------------------------------------

class WaitlistManager:
    def __init__(self, default_expiry_minutes: int = 15):
        self.entries: list[WaitlistEntry] = []
        self.default_expiry_minutes = default_expiry_minutes
        self.offers: list[WaitlistOffer] = []

    def add_entry(self, patient: Patient, provider: Provider, priority: int) -> WaitlistEntry:
        entry = WaitlistEntry(patient_id=patient.id, provider_id=provider.id, priority=priority)
        self.entries.append(entry)
        return entry

    def offer_slot(self, provider_id: str, now: datetime) -> Optional[WaitlistOffer]:
        """Offers the freed slot to the highest-priority (lowest number) waiting patient."""
        candidates = sorted(
            (e for e in self.entries if e.provider_id == provider_id),
            key=lambda e: e.priority,
        )
        if not candidates:
            return None
        top = candidates[0]
        self.entries.remove(top)
        offer = WaitlistOffer(
            patient_id=top.patient_id,
            provider_id=provider_id,
            offered_at=now,
            expiry_minutes=self.default_expiry_minutes,
        )
        self.offers.append(offer)
        return offer

    def expire_if_needed(self, offer: WaitlistOffer, now: datetime) -> WaitlistOffer:
        """If the offer window has elapsed unanswered, expire it and offer the next patient."""
        if offer.status != "Offered":
            return offer
        if now - offer.offered_at > timedelta(minutes=offer.expiry_minutes):
            offer.status = "Expired"
            return self.offer_slot(offer.provider_id, now)
        return offer


# ---------------------------------------------------------------------------
# RBAC (PRD Section 7: least-privilege role-based access control)
# ---------------------------------------------------------------------------

ROLE_PERMISSIONS = {
    "PATIENT": {"VIEW_OWN_PROFILE", "BOOK_OWN_APPOINTMENT"},
    "FRONT_DESK": {"BOOK_APPOINTMENT", "CHECK_IN_PATIENT", "VIEW_PATIENT_PROFILE"},
    "CLINICIAN": {"VIEW_PATIENT_PROFILE", "EDIT_CARE_PLAN", "VIEW_CLINICAL_REPORT"},
    "NURSE": {"VIEW_PATIENT_PROFILE", "EDIT_CARE_PLAN", "MANAGE_TASKS"},
    "CLINIC_MANAGER": {"VIEW_OPERATIONAL_REPORT", "EXPORT_REPORT", "VIEW_PATIENT_PROFILE"},
    "SYS_ADMIN": {"MANAGE_CONFIG", "VIEW_AUDIT_LOG"},
    "BILLING": {"VIEW_BILLING_INFO"},
}


def check_permission(user: User, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(user.role, set())


def require_permission(user: User, permission: str) -> None:
    if not check_permission(user, permission):
        raise RBACDeniedError(f"Role '{user.role}' lacks permission '{permission}'.")
