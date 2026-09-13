"""
test_scheduling.py
------------------------------------------------------------------
Executable pytest automation of the highest-priority scheduling test
cases from Homework 2 (Homework2_TestCases_UserStories_APISpecs.md),
run against the synthetic in-memory reference implementation in
oscs_reference.py.

Each test function's docstring names the original test case ID(s)
and PRD functional requirement(s) it automates, so results can be
traced back to Homework 2 and the PRD.

All data used below is synthetic (see conftest.py) - no real
patients, providers, or clinic data are involved.
"""

from datetime import timedelta

import pytest

from oscs_reference import (
    CANCELLED,
    CHECKED_IN,
    COMPLETED,
    CONFIRMED,
    IN_ROOM,
    REQUESTED,
    SCHEDULED,
    InvalidStateTransitionError,
    RBACDeniedError,
    ResourceConflictError,
    SchedulingConflictError,
    check_permission,
    require_permission,
)


# ---------------------------------------------------------------------------
# 1. Eligible appointment booking  (TC-FR003-01, FR-003)
# ---------------------------------------------------------------------------

def test_eligible_appointment_booking_succeeds(
    scheduler, established_patient, providers, locations, visit_types, standard_slot
):
    start, end = standard_slot

    appt = scheduler.book_appointment(
        patient=established_patient,
        provider=providers["adams"],
        location=locations["downtown"],
        visit_type=visit_types["routine_checkup"],
        start=start,
        end=end,
    )

    assert appt.state == SCHEDULED, "Eligible instant-booking visit type should book directly into Scheduled"
    assert appt.pending_review is False
    assert appt in scheduler.appointments


# ---------------------------------------------------------------------------
# 2. Preventing double-booking  (TC-FR003-01 step 3 / FR-003, FR-104)
# ---------------------------------------------------------------------------

def test_double_booking_is_prevented(
    scheduler, established_patient, new_patient_no_referral, providers, locations, visit_types, standard_slot
):
    start, end = standard_slot

    scheduler.book_appointment(
        patient=established_patient,
        provider=providers["adams"],
        location=locations["downtown"],
        visit_type=visit_types["routine_checkup"],
        start=start,
        end=end,
    )

    with pytest.raises(SchedulingConflictError):
        scheduler.book_appointment(
            patient=new_patient_no_referral,
            provider=providers["adams"],  # same provider, overlapping time
            location=locations["downtown"],
            visit_type=visit_types["routine_checkup"],
            start=start,
            end=end,
        )

    assert len(scheduler.appointments) == 1, "Second, conflicting booking must not be created"


# ---------------------------------------------------------------------------
# 3. Reschedule within policy window  (TC-FR004-01 variant / FR-004)
# ---------------------------------------------------------------------------

def test_reschedule_within_policy_window_succeeds(
    scheduler, established_patient, providers, locations, visit_types, standard_slot, now
):
    start, end = standard_slot  # 49 hours from `now` -> well outside the 24h policy window
    appt = scheduler.book_appointment(
        patient=established_patient,
        provider=providers["adams"],
        location=locations["downtown"],
        visit_type=visit_types["routine_checkup"],
        start=start,
        end=end,
    )

    new_start = start + timedelta(days=1)
    new_end = end + timedelta(days=1)

    updated = scheduler.reschedule_appointment(appt, new_start, new_end, now=now)

    assert updated.id == appt.id, "Reschedule must update the same appointment, not create a new one"
    assert updated.start == new_start and updated.end == new_end
    assert any(log.action == "RESCHEDULED" for log in updated.audit_log)


def test_reschedule_outside_policy_window_is_rejected(
    scheduler, established_patient, providers, locations, visit_types, now
):
    """Companion negative case: policy requires >24h notice; here only 2h remain."""
    start = now + timedelta(hours=2)
    end = start + timedelta(minutes=30)
    appt = scheduler.book_appointment(
        patient=established_patient,
        provider=providers["adams"],
        location=locations["downtown"],
        visit_type=visit_types["routine_checkup"],
        start=start,
        end=end,
    )

    from oscs_reference import ReschedulePolicyViolation

    with pytest.raises(ReschedulePolicyViolation):
        scheduler.reschedule_appointment(appt, start + timedelta(days=1), end + timedelta(days=1), now=now)


# ---------------------------------------------------------------------------
# 4. Cancellation with reason  (TC-FR004-01, FR-004)
# ---------------------------------------------------------------------------

def test_cancellation_with_reason_is_recorded(
    scheduler, established_patient, providers, locations, visit_types, standard_slot, now
):
    start, end = standard_slot
    appt = scheduler.book_appointment(
        patient=established_patient,
        provider=providers["adams"],
        location=locations["downtown"],
        visit_type=visit_types["routine_checkup"],
        start=start,
        end=end,
    )

    scheduler.cancel_appointment(
        appt, reason_code="SCHEDULE_CONFLICT", now=now, free_text="Work obligation"
    )

    assert appt.state == CANCELLED
    assert appt.cancellation_reason_code == "SCHEDULE_CONFLICT"
    assert appt.cancellation_free_text == "Work obligation"
    assert any(log.action == "CANCELLED" for log in appt.audit_log)


# ---------------------------------------------------------------------------
# 5. Waitlist offer when a slot opens  (TC-FR105-01, FR-105)
# ---------------------------------------------------------------------------

def test_waitlist_offer_sent_when_slot_opens(
    scheduler, waitlist_manager, established_patient, waitlisted_patient_a, waitlisted_patient_b,
    providers, locations, visit_types, standard_slot, now,
):
    start, end = standard_slot
    appt = scheduler.book_appointment(
        patient=established_patient,
        provider=providers["adams"],
        location=locations["downtown"],
        visit_type=visit_types["routine_checkup"],
        start=start,
        end=end,
    )

    waitlist_manager.add_entry(waitlisted_patient_a, providers["adams"], priority=1)
    waitlist_manager.add_entry(waitlisted_patient_b, providers["adams"], priority=2)

    offer = scheduler.cancel_appointment(
        appt, reason_code="SCHEDULE_CONFLICT", now=now, waitlist_manager=waitlist_manager
    )

    assert offer is not None, "Cancelling should trigger a waitlist offer"
    assert offer.patient_id == waitlisted_patient_a.id, "Highest priority patient should be offered first"
    assert offer.status == "Offered"

    # Offer expires unanswered after its window -> next-priority patient is offered.
    expired_check_time = now + timedelta(minutes=16)
    next_offer = waitlist_manager.expire_if_needed(offer, now=expired_check_time)

    assert offer.status == "Expired"
    assert next_offer is not None
    assert next_offer.patient_id == waitlisted_patient_b.id, "Slot should roll to the next-priority patient"


# ---------------------------------------------------------------------------
# 6. Resource conflict detection  (TC-FR104-01, FR-104)
# ---------------------------------------------------------------------------

def test_resource_conflict_detection(
    scheduler, established_patient, new_patient_no_referral, providers, locations, resources,
    visit_types, standard_slot,
):
    start, end = standard_slot

    scheduler.book_appointment(
        patient=established_patient,
        provider=providers["adams"],
        location=locations["downtown"],
        visit_type=visit_types["routine_checkup"],
        start=start,
        end=end,
        resource_ids=[resources["room_101"].id, resources["ultrasound_a"].id],
    )

    overlapping_start = start + timedelta(minutes=15)
    overlapping_end = overlapping_start + timedelta(minutes=30)

    with pytest.raises(ResourceConflictError):
        scheduler.book_appointment(
            patient=new_patient_no_referral,
            provider=providers["lee"],  # different provider, same room -> still a conflict
            location=locations["downtown"],
            visit_type=visit_types["routine_checkup"],
            start=overlapping_start,
            end=overlapping_end,
            resource_ids=[resources["room_101"].id],
        )


# ---------------------------------------------------------------------------
# 7. Scheduling eligibility / constraint failure  (TC-FR107-01, FR-107)
# ---------------------------------------------------------------------------

def test_scheduling_eligibility_constraint_failure(
    scheduler, new_patient_no_referral, providers, locations, visit_types, standard_slot
):
    start, end = standard_slot

    appt = scheduler.book_appointment(
        patient=new_patient_no_referral,
        provider=providers["adams"],
        location=locations["downtown"],
        visit_type=visit_types["new_patient_consult"],  # requires_referral=True
        start=start,
        end=end,
    )

    assert appt.state == REQUESTED, "Instant booking must be blocked for a failed eligibility check"
    assert appt.pending_review is True
    assert appt.review_reason is not None


# ---------------------------------------------------------------------------
# 8. Valid appointment lifecycle state transition  (TC-FR108-01, FR-108)
# ---------------------------------------------------------------------------

def test_valid_appointment_lifecycle_transitions(
    scheduler, established_patient, providers, locations, visit_types, standard_slot, now
):
    start, end = standard_slot
    appt = scheduler.book_appointment(
        patient=established_patient,
        provider=providers["adams"],
        location=locations["downtown"],
        visit_type=visit_types["routine_checkup"],
        start=start,
        end=end,
    )
    # TC-FR108-01 exercises the full lifecycle starting from "Requested" (the
    # generic creation state per FR-108), independent of the instant-booking
    # shortcut to "Scheduled" used by the eligible-booking test above.
    appt.state = REQUESTED

    for next_state in (SCHEDULED, CONFIRMED, CHECKED_IN, IN_ROOM, COMPLETED):
        scheduler.transition_state(appt, next_state, now=now)
        assert appt.state == next_state

    transition_log = [log for log in appt.audit_log if log.action == "STATE_CHANGE"]
    assert len(transition_log) == 5, "Every lifecycle transition must produce an audit log entry"


# ---------------------------------------------------------------------------
# 9. Invalid appointment lifecycle state transition  (TC-FR108-02, FR-108)
# ---------------------------------------------------------------------------

def test_invalid_appointment_lifecycle_transition_rejected(
    scheduler, established_patient, providers, locations, visit_types, standard_slot, now
):
    start, end = standard_slot
    appt = scheduler.book_appointment(
        patient=established_patient,
        provider=providers["adams"],
        location=locations["downtown"],
        visit_type=visit_types["routine_checkup"],
        start=start,
        end=end,
    )
    assert appt.state == SCHEDULED

    with pytest.raises(InvalidStateTransitionError):
        scheduler.transition_state(appt, COMPLETED, now=now)  # skips Confirmed/Checked-in/In-room

    assert appt.state == SCHEDULED, "Appointment must remain in its prior state after a rejected transition"


# ---------------------------------------------------------------------------
# 10. Role-based access check  (TC-SEC-01, TC-FR503-01, PRD Section 7)
# ---------------------------------------------------------------------------

def test_rbac_denies_unauthorized_role(users):
    billing_user = users["billing"]

    assert check_permission(billing_user, "EDIT_CARE_PLAN") is False
    with pytest.raises(RBACDeniedError):
        require_permission(billing_user, "EDIT_CARE_PLAN")


def test_rbac_grants_authorized_role(users):
    clinician = users["clinician"]

    assert check_permission(clinician, "EDIT_CARE_PLAN") is True
    require_permission(clinician, "EDIT_CARE_PLAN")  # must not raise


def test_rbac_report_export_restricted_to_clinic_manager(users):
    front_desk = users["front_desk"]
    clinic_manager = users["clinic_manager"]

    assert check_permission(front_desk, "EXPORT_REPORT") is False
    assert check_permission(clinic_manager, "EXPORT_REPORT") is True
