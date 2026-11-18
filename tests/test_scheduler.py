"""
tests/test_scheduler.py

Pytest suite for pure Python EV charging scheduler.
Tests:
  - 4-EV example with 20 kW capacity (uncontrolled peak 30, scheduled peak 20)
  - Impossible deadline
  - Zero capacity
  - Empty list
  - Midnight crossover
  - Additional edge cases (objects as requests, least slack first, 30-min slots)
"""
from dataclasses import dataclass
import pytest
from app.scheduler import schedule, ScheduleResult, DecisionLogEntry


def test_four_ev_example_20kw_capacity():
    """
    4-EV example with 20 kW capacity:
    Uncontrolled peak is 30 kW, scheduled peak is flattened to 20 kW.
    All 4 EVs finish before their deadlines.
    """
    requests = [
        {"id": "ev1", "label": "EV 1", "arrival": 8.0, "deadline": 11.0, "hours_needed": 2.0, "power_kw": 10.0},
        {"id": "ev2", "label": "EV 2", "arrival": 8.0, "deadline": 9.0, "hours_needed": 1.0, "power_kw": 10.0},
        {"id": "ev3", "label": "EV 3", "arrival": 8.0, "deadline": 12.0, "hours_needed": 3.0, "power_kw": 10.0},
        {"id": "ev4", "label": "EV 4", "arrival": 9.0, "deadline": 12.0, "hours_needed": 2.0, "power_kw": 10.0},
    ]
    capacity_kw = 20.0

    result = schedule(requests, capacity_kw=capacity_kw, slot_minutes=60)

    # 1. Uncontrolled baseline peak must be 30 kW
    uncontrolled_peak = max(result.uncontrolled_load.values())
    assert uncontrolled_peak == 30.0, f"Expected uncontrolled peak 30, got {uncontrolled_peak}"

    # 2. Scheduled load peak must be 20 kW and never exceed capacity
    scheduled_peak = max(result.scheduled_load.values())
    assert scheduled_peak == 20.0, f"Expected scheduled peak 20, got {scheduled_peak}"
    for slot, load in result.scheduled_load.items():
        assert load <= capacity_kw + 1e-9, f"Slot {slot} load {load} exceeded capacity {capacity_kw}"

    # 3. All deadlines must be met
    for ev_id, met in result.deadline_met.items():
        assert met is True, f"EV {ev_id} did not meet deadline"

    # 4. Check specific assigned slots match least-slack-first logic:
    # Slot 8: EV2 (slack 0) and EV1 (slack 1) charge. EV3 (slack 1) deferred.
    # Slot 9: EV3 (slack 0) and EV1 (slack 1) charge. EV4 (slack 1) deferred.
    # Slot 10: EV3 (slack 0) and EV4 (slack 0) charge.
    # Slot 11: EV3 (slack 0) and EV4 (slack 0) charge.
    assert result.assigned_slots["ev1"] == [8, 9]
    assert result.assigned_slots["ev2"] == [8]
    assert result.assigned_slots["ev3"] == [9, 10, 11]
    assert result.assigned_slots["ev4"] == [10, 11]

    # 5. Check log contains both charge and defer decisions
    actions = [entry.action for entry in result.log]
    assert "charge" in actions
    assert "defer" in actions

    # 6. Verify tuple unpacking and dictionary access compatibility
    sched, unctrl, assigned, met, log = result
    assert sched == result.scheduled_load
    assert unctrl == result.uncontrolled_load
    assert assigned == result.assigned_slots
    assert met == result.deadline_met
    assert log == result.log

    assert result["scheduled_load"] == sched
    assert result.get("scheduled_load") == sched
    assert "scheduled_load" in result


def test_impossible_deadline():
    """
    EV with an impossible deadline: needs 3 hours of charging but only 1 hour
    window is available before deadline.
    The scheduler charges it during the available slot, but marks deadline_met as False.
    """
    requests = [
        {"id": "ev_impossible", "label": "Late EV", "arrival": 8.0, "deadline": 9.0, "hours_needed": 3.0, "power_kw": 10.0}
    ]
    capacity_kw = 50.0  # Plenty of capacity

    result = schedule(requests, capacity_kw=capacity_kw)

    # Deadline cannot be met
    assert result.deadline_met["ev_impossible"] is False

    # EV charges in slot 8 (before deadline at 9.0), but not in slot 9
    assert result.assigned_slots["ev_impossible"] == [8]
    assert result.scheduled_load[8] == 10.0
    assert 9 not in result.assigned_slots["ev_impossible"]

    # Log reflects charging in slot 8
    slot_8_entries = [e for e in result.log if e.slot == 8 and e.ev_id == "ev_impossible"]
    assert any(e.action == "charge" for e in slot_8_entries)


def test_zero_capacity():
    """
    Zero capacity available (capacity_kw = 0).
    No EV can charge in any slot; all active EVs are deferred, and deadline_met is False.
    """
    requests = [
        {"id": "ev1", "label": "EV 1", "arrival": 8.0, "deadline": 11.0, "hours_needed": 2.0, "power_kw": 10.0},
        {"id": "ev2", "label": "EV 2", "arrival": 8.0, "deadline": 10.0, "hours_needed": 1.0, "power_kw": 10.0},
    ]
    capacity_kw = 0.0

    result = schedule(requests, capacity_kw=capacity_kw)

    # All scheduled loads must be 0.0
    assert all(load == 0.0 for load in result.scheduled_load.values())

    # No slots assigned to any EV
    for ev_id, slots in result.assigned_slots.items():
        assert slots == [], f"EV {ev_id} unexpectedly assigned slots {slots}"

    # Deadlines not met
    assert result.deadline_met["ev1"] is False
    assert result.deadline_met["ev2"] is False

    # Log records deferrals due to capacity
    assert len(result.log) > 0
    assert all(e.action == "defer" for e in result.log)

    # Uncontrolled baseline still reflects demand on arrival
    assert result.uncontrolled_load[8] == 20.0


def test_empty_list():
    """
    Empty list of requests should return empty mappings/lists without crashing.
    """
    result = schedule([], capacity_kw=20.0, slot_minutes=60)

    assert result.scheduled_load == {}
    assert result.uncontrolled_load == {}
    assert result.assigned_slots == {}
    assert result.deadline_met == {}
    assert result.log == []


def test_midnight_crossover():
    """
    Deadlines crossing midnight:
    EV1 arrives at 22.0, deadline at 2.0 (next day -> 26.0), hours_needed=2, power=10 kW.
    EV2 arrives at 22.0, deadline at 4.0 (next day -> 28.0), hours_needed=3, power=10 kW.
    Capacity = 10 kW.
    Uncontrolled peak = 20 kW (slots 22 and 23).
    Scheduled peak = 10 kW.
    Both EVs meet their deadlines across midnight.
    """
    requests = [
        {"id": "ev1", "label": "Night EV 1", "arrival": 22.0, "deadline": 2.0, "hours_needed": 2.0, "power_kw": 10.0},
        {"id": "ev2", "label": "Night EV 2", "arrival": 22.0, "deadline": 4.0, "hours_needed": 3.0, "power_kw": 10.0},
    ]
    capacity_kw = 10.0

    result = schedule(requests, capacity_kw=capacity_kw, slot_minutes=60)

    # Uncontrolled peak: both try to charge simultaneously on arrival (slots 22, 23)
    assert max(result.uncontrolled_load.values()) == 20.0

    # Scheduled peak: capped at 10 kW
    assert max(result.scheduled_load.values()) == 10.0
    for load in result.scheduled_load.values():
        assert load <= capacity_kw + 1e-9

    # Both EVs finish before deadline
    assert result.deadline_met["ev1"] is True
    assert result.deadline_met["ev2"] is True

    # EV1 has earlier deadline (2:00 / 26.0) -> slack is lower, charges first at 22 and 23
    assert result.assigned_slots["ev1"] == [22, 23]

    # EV2 is deferred at 22 and 23, then charges across midnight at 24 (0:00), 25 (1:00), 26 (2:00)
    assert result.assigned_slots["ev2"] == [24, 25, 26]

    # EV2 finishes at slot 26 (ends at 27.0 <= 28.0 / 4:00 AM)
    assert all(s in result.scheduled_load for s in [22, 23, 24, 25, 26])


def test_least_slack_first_priority():
    """
    Two EVs arrive at same time with same hours needed, but different deadlines.
    The one with tighter deadline/slack must be scheduled first when capacity is limited to 1 EV.
    """
    requests = [
        {"id": "slack_loose", "label": "Loose", "arrival": 10.0, "deadline": 16.0, "hours_needed": 2.0, "power_kw": 10.0},
        {"id": "slack_tight", "label": "Tight", "arrival": 10.0, "deadline": 13.0, "hours_needed": 2.0, "power_kw": 10.0},
    ]
    # Capacity only fits 1 EV at a time
    result = schedule(requests, capacity_kw=10.0)

    # Tight EV charges at 10 and 11
    assert result.assigned_slots["slack_tight"] == [10, 11]
    # Loose EV is deferred to 12 and 13
    assert result.assigned_slots["slack_loose"] == [12, 13]

    assert result.deadline_met["slack_tight"] is True
    assert result.deadline_met["slack_loose"] is True


def test_requests_as_dataclass_objects():
    """
    Requests passed as Python objects/dataclasses rather than dictionaries.
    """
    @dataclass
    class EVRequest:
        id: str
        label: str
        arrival: float
        deadline: float
        hours_needed: float
        power_kw: float

    requests = [
        EVRequest(id="car_a", label="Sedan", arrival=9.0, deadline=12.0, hours_needed=2.0, power_kw=7.0),
        EVRequest(id="car_b", label="SUV", arrival=9.0, deadline=11.0, hours_needed=1.0, power_kw=7.0),
    ]

    result = schedule(requests, capacity_kw=7.0)

    # SUV has tighter deadline (11.0 vs 12.0), charges at slot 9
    assert result.assigned_slots["car_b"] == [9]
    # Sedan charges at slots 10 and 11
    assert result.assigned_slots["car_a"] == [10, 11]

    assert result.deadline_met["car_a"] is True
    assert result.deadline_met["car_b"] is True
    assert max(result.scheduled_load.values()) == 7.0
    assert max(result.uncontrolled_load.values()) == 14.0


def test_already_finished_or_zero_hours():
    """
    EV needing 0 hours of charging should have deadline_met = True immediately.
    """
    requests = [
        {"id": "ev_done", "label": "Full Battery", "arrival": 8.0, "deadline": 10.0, "hours_needed": 0.0, "power_kw": 10.0}
    ]
    result = schedule(requests, capacity_kw=20.0)

    assert result.deadline_met["ev_done"] is True
    assert result.assigned_slots["ev_done"] == []
