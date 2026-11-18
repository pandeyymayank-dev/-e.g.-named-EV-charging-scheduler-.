"""
app/scheduler.py

Pure Python EV charging scheduler.
No DB or web dependencies.
"""
from typing import Any, Dict, List, Optional, Union
import math


class DecisionLogEntry(str):
    """
    Log entry that acts as a human-readable string while providing structured attributes.
    Supports attribute access (entry.action) and string search ('defer' in entry).
    """
    def __new__(
        cls,
        text: str,
        slot: Optional[Union[int, float]] = None,
        ev_id: Any = None,
        action: Optional[str] = None,
        slack: Optional[float] = None,
        power_kw: Optional[float] = None,
        reason: Optional[str] = None,
    ):
        obj = str.__new__(cls, text)
        obj.slot = slot
        obj.ev_id = ev_id
        obj.action = action  # 'charge', 'defer', 'info'
        obj.slack = slack
        obj.power_kw = power_kw
        obj.reason = reason
        return obj

    def __getitem__(self, item):
        if isinstance(item, str):
            attrs = {
                "text": str(self),
                "slot": self.slot,
                "ev_id": self.ev_id,
                "action": self.action,
                "slack": self.slack,
                "power_kw": self.power_kw,
                "reason": self.reason,
            }
            if item in attrs:
                return attrs[item]
            raise KeyError(item)
        return str.__getitem__(self, item)


class ScheduleResult(tuple):
    """
    Container for schedule results.
    Supports:
      1. Tuple unpacking:
         scheduled_load, uncontrolled_load, assigned_slots, deadline_met, log = schedule(...)
      2. Attribute access:
         result.scheduled_load, result.uncontrolled_load, etc.
      3. Dictionary key access:
         result["scheduled_load"], result.get("scheduled_load"), etc.
    """
    def __new__(
        cls,
        scheduled_load: Dict[Any, float],
        uncontrolled_load: Dict[Any, float],
        assigned_slots: Dict[Any, List[Any]],
        deadline_met: Dict[Any, bool],
        log: List[DecisionLogEntry],
    ):
        return tuple.__new__(
            cls,
            (scheduled_load, uncontrolled_load, assigned_slots, deadline_met, log),
        )

    @property
    def scheduled_load(self) -> Dict[Any, float]:
        return tuple.__getitem__(self, 0)

    @property
    def uncontrolled_load(self) -> Dict[Any, float]:
        return tuple.__getitem__(self, 1)

    @property
    def assigned_slots(self) -> Dict[Any, List[Any]]:
        return tuple.__getitem__(self, 2)

    @property
    def deadline_met(self) -> Dict[Any, bool]:
        return tuple.__getitem__(self, 3)

    @property
    def log(self) -> List[DecisionLogEntry]:
        return tuple.__getitem__(self, 4)

    def __getitem__(self, item):
        if isinstance(item, str):
            field_map = {
                "scheduled_load": self.scheduled_load,
                "per_slot_scheduled_load": self.scheduled_load,
                "uncontrolled_load": self.uncontrolled_load,
                "per_slot_uncontrolled_load": self.uncontrolled_load,
                "uncontrolled_baseline_load": self.uncontrolled_load,
                "baseline_load": self.uncontrolled_load,
                "assigned_slots": self.assigned_slots,
                "per_ev_assigned_slots": self.assigned_slots,
                "deadline_met": self.deadline_met,
                "deadline_met_flags": self.deadline_met,
                "log": self.log,
                "decisions": self.log,
                "decision_log": self.log,
            }
            if item in field_map:
                return field_map[item]
            raise KeyError(f"Unknown result key: {item}")
        return tuple.__getitem__(self, item)

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except (KeyError, IndexError, TypeError):
            return default

    def keys(self) -> List[str]:
        return ["scheduled_load", "uncontrolled_load", "assigned_slots", "deadline_met", "log"]

    def values(self) -> List[Any]:
        return [self.scheduled_load, self.uncontrolled_load, self.assigned_slots, self.deadline_met, self.log]

    def items(self):
        return list(zip(self.keys(), self.values()))

    def __contains__(self, key: Any) -> bool:
        if isinstance(key, str):
            valid_keys = {
                "scheduled_load", "per_slot_scheduled_load",
                "uncontrolled_load", "per_slot_uncontrolled_load", "uncontrolled_baseline_load", "baseline_load",
                "assigned_slots", "per_ev_assigned_slots",
                "deadline_met", "deadline_met_flags",
                "log", "decisions", "decision_log",
            }
            return key in valid_keys
        return tuple.__contains__(self, key)

    def __repr__(self) -> str:
        return (
            f"ScheduleResult(scheduled_load={self.scheduled_load}, "
            f"uncontrolled_load={self.uncontrolled_load}, "
            f"assigned_slots={self.assigned_slots}, "
            f"deadline_met={self.deadline_met}, "
            f"log_entries={len(self.log)})"
        )


def _slot_key(slot_val: float) -> Union[int, float]:
    """Return an int if slot_val is an integer hour, else rounded float."""
    rounded = round(slot_val, 4)
    if abs(rounded - round(rounded)) < 1e-6:
        return int(round(rounded))
    return rounded


def _normalize_requests(requests: List[Any]) -> List[Dict[str, Any]]:
    """
    Extract request fields from dicts or objects and normalize midnight crossovers.
    If deadline < arrival, deadline wraps past midnight (+24h).
    """
    normalized = []
    for r in requests:
        if isinstance(r, dict):
            ev_id = r["id"]
            label = str(r.get("label", ev_id))
            arrival = float(r["arrival"])
            deadline = float(r["deadline"])
            hours_needed = float(r["hours_needed"])
            power_kw = float(r["power_kw"])
        else:
            ev_id = getattr(r, "id")
            label = str(getattr(r, "label", ev_id))
            arrival = float(getattr(r, "arrival"))
            deadline = float(getattr(r, "deadline"))
            hours_needed = float(getattr(r, "hours_needed"))
            power_kw = float(getattr(r, "power_kw"))

        effective_deadline = deadline
        # Support deadlines crossing midnight:
        while effective_deadline < arrival:
            effective_deadline += 24.0

        normalized.append({
            "id": ev_id,
            "label": label,
            "arrival": arrival,
            "deadline": deadline,
            "effective_deadline": effective_deadline,
            "hours_needed": max(0.0, hours_needed),
            "power_kw": max(0.0, power_kw),
        })
    return normalized


def schedule(
    requests: List[Any],
    capacity_kw: float,
    slot_minutes: int = 60,
) -> ScheduleResult:
    """
    Schedule EV charging across discrete time slots under a maximum power capacity.

    Parameters:
        requests: List of EV charging requests (dict or object with id, label, arrival, deadline, hours_needed, power_kw).
        capacity_kw: Maximum grid/transformer power capacity in kW.
        slot_minutes: Duration of each slot in minutes (default 60 = 1 hour).

    Algorithm:
        For each hourly slot:
          1. Take active EVs: (arrived, not finished, before deadline).
          2. Sort by slack = effective_deadline - slot - remaining_hours (ascending).
          3. Charge them in order while capacity remains, defer the rest.

    Returns:
        ScheduleResult (unpackable 5-tuple, dict-accessible, attribute-accessible):
          - scheduled_load: per-slot scheduled load (kW)
          - uncontrolled_load: per-slot uncontrolled baseline load (kW, everyone charges on arrival)
          - assigned_slots: per-EV assigned slots
          - deadline_met: per-EV boolean flags indicating if all required charging finished before deadline
          - log: list of DecisionLogEntry decision records
    """
    if not requests:
        return ScheduleResult(
            scheduled_load={},
            uncontrolled_load={},
            assigned_slots={},
            deadline_met={},
            log=[],
        )

    norm_requests = _normalize_requests(requests)
    slot_hours = slot_minutes / 60.0

    # Determine simulation time boundaries
    min_arrival = min(r["arrival"] for r in norm_requests)
    max_time = max(
        max(r["effective_deadline"], r["arrival"] + r["hours_needed"])
        for r in norm_requests
    )

    start_slot = math.floor(min_arrival / slot_hours) * slot_hours
    end_slot = math.ceil(max_time / slot_hours) * slot_hours

    # Generate sequential slot start timestamps
    slot_list: List[float] = []
    curr = start_slot
    while curr < end_slot - 1e-9:
        slot_list.append(round(curr, 6))
        curr += slot_hours

    # 1. Calculate Uncontrolled Baseline Load: everyone charges immediately upon arrival
    uncontrolled_load: Dict[Union[int, float], float] = {_slot_key(s): 0.0 for s in slot_list}
    for r in norm_requests:
        needed = r["hours_needed"]
        p_kw = r["power_kw"]
        for s in slot_list:
            if needed <= 1e-9:
                break
            if s >= r["arrival"] - 1e-9:
                charge_duration = min(needed, slot_hours)
                sk = _slot_key(s)
                uncontrolled_load[sk] += p_kw * (charge_duration / slot_hours)
                needed -= charge_duration

    # Round uncontrolled loads to 4 decimal places
    for sk in uncontrolled_load:
        uncontrolled_load[sk] = round(uncontrolled_load[sk], 4)

    # 2. Scheduled Charging Simulation
    scheduled_load: Dict[Union[int, float], float] = {_slot_key(s): 0.0 for s in slot_list}
    assigned_slots: Dict[Any, List[Union[int, float]]] = {r["id"]: [] for r in norm_requests}
    remaining_hours: Dict[Any, float] = {r["id"]: r["hours_needed"] for r in norm_requests}
    log: List[DecisionLogEntry] = []

    for s in slot_list:
        sk = _slot_key(s)

        # Active EVs: arrived, not finished, before deadline
        active_evs = []
        for r in norm_requests:
            ev_id = r["id"]
            rem = remaining_hours[ev_id]
            arrived = (s >= r["arrival"] - 1e-9)
            not_finished = (rem > 1e-9)
            before_deadline = (s < r["effective_deadline"] - 1e-9)

            if arrived and not_finished and before_deadline:
                # slack = deadline - slot - remaining_hours
                slack = r["effective_deadline"] - s - rem
                active_evs.append((slack, r, rem))

        # Sort by slack (ascending); tie-break by earlier deadline, earlier arrival, then id
        active_evs.sort(
            key=lambda item: (
                item[0],
                item[1]["effective_deadline"],
                item[1]["arrival"],
                str(item[1]["id"]),
            )
        )

        # Charge them in order while capacity remains, defer the rest
        current_slot_load = 0.0
        for slack, r, rem in active_evs:
            ev_id = r["id"]
            p_kw = r["power_kw"]
            label = r["label"]

            if current_slot_load + p_kw <= capacity_kw + 1e-9:
                # Capacity allows charging this EV
                current_slot_load += p_kw
                charge_duration = min(rem, slot_hours)
                remaining_hours[ev_id] = max(0.0, rem - charge_duration)
                assigned_slots[ev_id].append(sk)

                entry = DecisionLogEntry(
                    f"Slot {sk}: CHARGE EV '{label}' (id={ev_id}) with {p_kw:.1f} kW "
                    f"[slack={slack:.2f}h, remaining={remaining_hours[ev_id]:.2f}h, "
                    f"load={current_slot_load:.1f}/{capacity_kw:.1f} kW]",
                    slot=sk,
                    ev_id=ev_id,
                    action="charge",
                    slack=slack,
                    power_kw=p_kw,
                )
                log.append(entry)
            else:
                # Insufficient capacity; defer
                entry = DecisionLogEntry(
                    f"Slot {sk}: DEFER EV '{label}' (id={ev_id}) "
                    f"[slack={slack:.2f}h, remaining={rem:.2f}h, needed={p_kw:.1f} kW, "
                    f"available={max(0.0, capacity_kw - current_slot_load):.1f} kW]",
                    slot=sk,
                    ev_id=ev_id,
                    action="defer",
                    slack=slack,
                    power_kw=p_kw,
                    reason="insufficient_capacity",
                )
                log.append(entry)

        scheduled_load[sk] = round(current_slot_load, 4)

    # 3. Determine deadline_met flags
    deadline_met: Dict[Any, bool] = {
        r["id"]: (remaining_hours[r["id"]] <= 1e-9)
        for r in norm_requests
    }

    return ScheduleResult(
        scheduled_load=scheduled_load,
        uncontrolled_load=uncontrolled_load,
        assigned_slots=assigned_slots,
        deadline_met=deadline_met,
        log=log,
    )
