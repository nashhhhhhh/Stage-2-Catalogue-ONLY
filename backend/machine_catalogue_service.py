from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MACHINE_CATALOGUE_PATH = DATA_DIR / "catalogue_machine_capacity.json"
ROOM_OVERRIDES_PATH = DATA_DIR / "catalogue_room_overrides.json"


def now_iso():
    return datetime.now().replace(microsecond=0).isoformat()


def normalize_room_code(value):
    if value is None:
        return ""
    text = str(value).strip().upper().replace(":", "-")
    match = re.match(r"^([HLMO])[-\s]?(\d{1,2})$", text)
    if match:
        return f"{match.group(1)}-{int(match.group(2)):02d}"
    return text


def empty_payload():
    return {
        "version": 1,
        "source": {
            "name": "",
            "last_imported": "",
        },
        "machines": [],
    }


def empty_room_overrides():
    return {
        "version": 1,
        "rooms": {},
    }


def load_machine_catalogue():
    if not MACHINE_CATALOGUE_PATH.exists():
        return empty_payload()
    try:
        with MACHINE_CATALOGUE_PATH.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return empty_payload()
    payload.setdefault("version", 1)
    payload.setdefault("source", {})
    payload.setdefault("machines", [])
    return payload


def save_machine_catalogue(payload):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload["version"] = int(payload.get("version") or 1)
    payload.setdefault("source", {})
    payload.setdefault("machines", [])
    payload["updated_at"] = now_iso()
    with MACHINE_CATALOGUE_PATH.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return payload


def load_room_overrides():
    if not ROOM_OVERRIDES_PATH.exists():
        return empty_room_overrides()
    try:
        with ROOM_OVERRIDES_PATH.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return empty_room_overrides()
    payload.setdefault("version", 1)
    payload.setdefault("rooms", {})
    return payload


def save_room_overrides(payload):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload["version"] = int(payload.get("version") or 1)
    payload.setdefault("rooms", {})
    payload["updated_at"] = now_iso()
    with ROOM_OVERRIDES_PATH.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return payload


def apply_room_overrides(catalogue_map):
    overrides = load_room_overrides().get("rooms", {})
    updated = {}
    for code, details in catalogue_map.items():
        normalized_code = normalize_room_code(code)
        room = dict(details)
        override = overrides.get(normalized_code, {})
        if override.get("name"):
            room["name"] = override["name"]
        if override.get("page") not in ("", None):
            try:
                room["page"] = int(override["page"])
            except (TypeError, ValueError):
                pass
        room["defaultName"] = details.get("name", "")
        room["nameOverride"] = override.get("name", "")
        updated[normalized_code] = room
    return updated


def upsert_room_override(data):
    payload = load_room_overrides()
    room_code = normalize_room_code((data or {}).get("code") or (data or {}).get("room_code"))
    if not room_code:
        raise ValueError("Room code is required")
    room = payload.setdefault("rooms", {}).setdefault(room_code, {})
    name = str((data or {}).get("name") or "").strip()
    page = (data or {}).get("page")
    if name:
        room["name"] = name
    else:
        room.pop("name", None)
    if page not in ("", None):
        try:
            room["page"] = int(page)
        except (TypeError, ValueError):
            room.pop("page", None)
    else:
        room.pop("page", None)
    room["updated_at"] = now_iso()
    save_room_overrides(payload)
    return {"code": room_code, **room}


def machine_summary(machine):
    capacity = machine.get("target_capacity") or machine.get("capacity") or ""
    capacity_unit = machine.get("capacity_unit", "")
    quantity = machine.get("quantity")
    return {
        "id": machine.get("id"),
        "reference": machine.get("reference", ""),
        "room_code": normalize_room_code(machine.get("room_code")),
        "source_room": machine.get("source_room", ""),
        "area": machine.get("area", ""),
        "machine_name": machine.get("machine_name", ""),
        "brand": machine.get("brand", ""),
        "quantity": quantity,
        "capacity": capacity,
        "capacity_unit": capacity_unit,
        "capacity_display": " ".join(part for part in [str(capacity).strip(), str(capacity_unit).strip()] if part),
        "mapping_confidence": machine.get("mapping_confidence", ""),
        "mapping_note": machine.get("mapping_note", ""),
        "dimensions": machine.get("dimensions", {}),
        "utilities": machine.get("utilities", {}),
        "source": machine.get("source", ""),
    }


def list_machines(room_code=None):
    payload = load_machine_catalogue()
    room_filter = normalize_room_code(room_code)
    machines = payload.get("machines", [])
    if room_filter:
        machines = [
            machine for machine in machines
            if normalize_room_code(machine.get("room_code")) == room_filter
        ]
    return {
        "source": payload.get("source", {}),
        "updated_at": payload.get("updated_at", ""),
        "machines": sorted(
            (machine_summary(machine) for machine in machines),
            key=lambda row: (
                row.get("room_code") or "ZZZ",
                row.get("machine_name") or "",
                row.get("reference") or "",
            ),
        ),
    }


def sanitize_machine(data):
    machine = dict(data or {})
    machine["id"] = str(machine.get("id") or uuid.uuid4())
    machine["reference"] = str(machine.get("reference") or "").strip()
    machine["room_code"] = normalize_room_code(machine.get("room_code"))
    machine["source_room"] = str(machine.get("source_room") or "").strip()
    machine["area"] = str(machine.get("area") or "").strip()
    machine["machine_name"] = str(machine.get("machine_name") or "").strip()
    machine["brand"] = str(machine.get("brand") or "").strip()
    machine["target_capacity"] = str(machine.get("target_capacity") or machine.get("capacity") or "").strip()
    machine["capacity_unit"] = str(machine.get("capacity_unit") or "").strip()
    machine["mapping_confidence"] = str(machine.get("mapping_confidence") or "manual").strip()
    machine["mapping_note"] = str(machine.get("mapping_note") or "").strip()
    machine["source"] = str(machine.get("source") or "").strip()
    quantity = machine.get("quantity")
    try:
        machine["quantity"] = None if quantity in ("", None) else float(quantity)
    except (TypeError, ValueError):
        machine["quantity"] = None
    dimensions = machine.get("dimensions") if isinstance(machine.get("dimensions"), dict) else {}
    machine["dimensions"] = {
        "width_mm": str(dimensions.get("width_mm") or "").strip(),
        "length_mm": str(dimensions.get("length_mm") or "").strip(),
        "height_mm": str(dimensions.get("height_mm") or "").strip(),
    }
    utilities = machine.get("utilities") if isinstance(machine.get("utilities"), dict) else {}
    machine["utilities"] = {
        "electrical_kw": str(utilities.get("electrical_kw") or "").strip(),
        "phase": str(utilities.get("phase") or "").strip(),
        "gas": str(utilities.get("gas") or "").strip(),
        "cold_water": str(utilities.get("cold_water") or "").strip(),
        "hot_water": str(utilities.get("hot_water") or "").strip(),
        "drainage": str(utilities.get("drainage") or "").strip(),
        "compressed_air": str(utilities.get("compressed_air") or "").strip(),
        "steam_indirect": str(utilities.get("steam_indirect") or "").strip(),
        "steam_direct": str(utilities.get("steam_direct") or "").strip(),
        "live_load": str(utilities.get("live_load") or "").strip(),
    }
    return machine


def upsert_machine(data):
    payload = load_machine_catalogue()
    machine = sanitize_machine(data)
    machines = payload.setdefault("machines", [])
    for index, current in enumerate(machines):
        if str(current.get("id")) == machine["id"]:
            machines[index] = machine
            break
    else:
        machines.append(machine)
    save_machine_catalogue(payload)
    return machine


def delete_machine(machine_id):
    payload = load_machine_catalogue()
    before = len(payload.get("machines", []))
    payload["machines"] = [
        machine for machine in payload.get("machines", [])
        if str(machine.get("id")) != str(machine_id)
    ]
    save_machine_catalogue(payload)
    return len(payload["machines"]) < before
