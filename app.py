from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
from datetime import datetime
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import ProxyHandler, Request, build_opener

from flask import Flask, jsonify, render_template, request, send_from_directory
from werkzeug.utils import secure_filename

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
DATA_DIR = os.path.join(BASE_DIR, "data")
BACKEND_DIR = os.path.join(BASE_DIR, "backend")
sys.path.insert(0, BACKEND_DIR)

from custom_catalogue_service import create_custom_catalogue, get_custom_catalogue, load_custom_catalogues
from machine_catalogue_service import (
    apply_room_overrides,
    delete_machine,
    list_machines,
    upsert_machine,
    upsert_room_override,
)

try:
    import fitz
except ImportError:
    fitz = None


app = Flask(
    __name__,
    static_folder=FRONTEND_DIR,
    static_url_path="",
    template_folder=FRONTEND_DIR,
)
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 300

FRONTEND_STATIC_DATA_DIR = os.path.join(FRONTEND_DIR, "static", "data")
LAYOUT_SOURCE_CONFIG_PATH = os.path.join(FRONTEND_STATIC_DATA_DIR, "layout_source_config.json")
LAYOUT_METADATA_PATH = os.path.join(FRONTEND_STATIC_DATA_DIR, "layout_metadata.json")
CATALOGUE_PAGE_MAP_PATH = os.path.join(DATA_DIR, "catalogue_page_map.json")
CATALOGUE_AUTO_REFRESH_SECONDS = 300

LAYOUT_SOURCE_DEFAULTS = {
    "source_pptx": "layout_sources/Stage 2 PPT Layout.pptx",
    "layouts": {
        "factory": {
            "label": "Factory Layout",
            "slide": 3,
            "picture": "Picture 4",
            "image": "stage2_layout.png",
            "target_width": 7680,
        },
        "incoming-office-level-1": {
            "label": "Incoming Warehouse Office - Level 1",
            "slide": 4,
            "picture": "Picture 10",
            "image": "incoming_warehouse_office_level1.png",
            "target_width": 3600,
        },
        "incoming-office-level-2": {
            "label": "Incoming Warehouse Office - Level 2",
            "slide": 5,
            "picture": "Picture 9",
            "image": "incoming_warehouse_office_level2.png",
            "target_width": 3600,
        },
    },
}

_CATALOGUE_REFRESH_STATE = {}
_CATALOGUE_REFRESH_LOCK = threading.Lock()
_CATALOGUE_METADATA_LOCK = threading.Lock()
_CATALOGUE_TOC_CACHE = {}
_CATALOGUE_ASSET_COUNT_CACHE = {}


def read_json_file(path, fallback):
    try:
        with open(path, "r", encoding="utf-8") as json_file:
            return json.load(json_file)
    except (OSError, json.JSONDecodeError):
        return fallback


CATALOGUE_PAGE_MAP = read_json_file(CATALOGUE_PAGE_MAP_PATH, {})


def get_file_signature(path):
    try:
        stat = os.stat(path)
    except FileNotFoundError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def get_catalogue_pdf_path(pdf_url):
    return os.path.join(FRONTEND_DIR, pdf_url.lstrip("/").replace("/", os.sep))


def get_catalogue_dir():
    return os.path.join(FRONTEND_DIR, "static", "catalogue")


def get_catalogue_metadata_path():
    return os.path.join(get_catalogue_dir(), "catalogue_versions.json")


def get_catalogue_pdf_url(file_name):
    return f"/static/catalogue/{file_name}" if file_name else ""


def get_catalogue_current_file_name(risk_key):
    return f"current_{risk_key}_catalogue.pdf"


def get_catalogue_risk_key(room_code):
    prefix = (room_code or "").strip().upper()[:1]
    return {"M": "medium", "H": "high", "L": "low", "O": "office"}.get(prefix)


def extract_google_doc_id(doc_url):
    if not doc_url:
        return ""
    parsed_url = urlparse(doc_url.strip())
    path_match = re.search(r"/document/d/([^/]+)", parsed_url.path)
    return path_match.group(1) if path_match else ""


def download_google_doc_pdf(doc_url):
    doc_id = extract_google_doc_id(doc_url)
    if not doc_id:
        raise ValueError("Paste a valid Google Docs URL.")

    parsed_url = urlparse(doc_url.strip())
    tab_id = parse_qs(parsed_url.query).get("tab", [""])[0]
    export_params = {"format": "pdf"}
    if tab_id:
        export_params["tab"] = tab_id

    export_url = f"https://docs.google.com/document/d/{doc_id}/export?{urlencode(export_params)}"
    opener = build_opener(ProxyHandler({}))
    with opener.open(Request(export_url, headers={"User-Agent": "Mozilla/5.0"}), timeout=180) as response:
        pdf_bytes = response.read()

    if not pdf_bytes.startswith(b"%PDF"):
        raise ValueError("Google Docs did not return a PDF. Check that the document is shared for viewing.")
    return pdf_bytes, doc_id


def get_catalogue_pdf_version(pdf_url):
    if not pdf_url:
        return "missing"
    signature = get_file_signature(get_catalogue_pdf_path(pdf_url))
    return f"{signature[0]}-{signature[1]}" if signature else "missing"


def with_catalogue_pdf_versions(catalogue_map):
    return {
        code: {**details, "pdfVersion": get_catalogue_pdf_version(details.get("pdf"))}
        for code, details in catalogue_map.items()
    }


def get_pdf_page_object_order(pdf_bytes):
    page_objects = []
    for match in re.finditer(rb"/Type /Page\b", pdf_bytes):
        object_marker = pdf_bytes.rfind(b" obj", 0, match.start())
        if object_marker == -1:
            continue
        object_start = pdf_bytes.rfind(b"\n", 0, object_marker)
        object_header = pdf_bytes[object_start + 1:object_marker + 4]
        object_match = re.search(rb"(\d+)\s+0\s+obj", object_header)
        if object_match:
            page_objects.append(int(object_match.group(1)))
    return {object_id: index + 1 for index, object_id in enumerate(page_objects)}


def get_pdf_named_destinations(pdf_bytes, page_by_object):
    named_destinations = {}
    destination_marker = pdf_bytes.rfind(b"/h.")
    if destination_marker == -1:
        return named_destinations
    object_start = pdf_bytes.rfind(b" obj", 0, destination_marker)
    if object_start == -1:
        return named_destinations
    object_start = pdf_bytes.rfind(b"\n", 0, object_start)
    object_end = pdf_bytes.find(b"endobj", destination_marker)
    if object_end == -1:
        return named_destinations
    object_body = pdf_bytes[object_start:object_end]
    for destination_match in re.finditer(rb"/(h\.[^\s\[]+)\s*\[(\d+)\s+0\s+R", object_body):
        destination_name = destination_match.group(1).decode("latin-1")
        page_number = page_by_object.get(int(destination_match.group(2)))
        if page_number:
            named_destinations[destination_name] = page_number
    return named_destinations


def get_pdf_contents_link_pages(pdf_url):
    pdf_path = get_catalogue_pdf_path(pdf_url)
    signature = get_file_signature(pdf_path)
    if not signature:
        return []
    cache_key = (pdf_path, signature)
    if cache_key in _CATALOGUE_TOC_CACHE:
        return _CATALOGUE_TOC_CACHE[cache_key]
    try:
        with open(pdf_path, "rb") as pdf_file:
            pdf_bytes = pdf_file.read()
    except OSError:
        return []

    page_by_object = get_pdf_page_object_order(pdf_bytes)
    named_destinations = get_pdf_named_destinations(pdf_bytes, page_by_object)
    link_pages = []
    for object_number in range(1, 80):
        object_marker = f"\n{object_number} 0 obj".encode("ascii")
        object_start = pdf_bytes.find(object_marker)
        if object_start == -1 and pdf_bytes.startswith(object_marker[1:]):
            object_start = 0
        if object_start == -1:
            continue
        object_end = pdf_bytes.find(b"endobj", object_start)
        if object_end == -1:
            continue
        object_body = pdf_bytes[object_start:object_end]
        rect_match = re.search(rb"/Rect \[([^\]]+)\]", object_body)
        destination_match = re.search(rb"/Dest /(h\.[^\s>/]+)", object_body)
        if not rect_match or not destination_match:
            continue
        try:
            rect_values = [float(value) for value in rect_match.group(1).split()]
        except ValueError:
            continue
        destination_name = destination_match.group(1).decode("latin-1")
        page_number = named_destinations.get(destination_name)
        if len(rect_values) >= 4 and abs(rect_values[0] - 108) < 0.5 and (rect_values[2] - rect_values[0]) > 250 and page_number:
            link_pages.append(page_number)

    _CATALOGUE_TOC_CACHE[cache_key] = link_pages
    return link_pages


def apply_catalogue_toc_pages(catalogue_map):
    updated_map = {code: dict(details) for code, details in catalogue_map.items()}
    risk_groups = {}
    for code, details in updated_map.items():
        risk_groups.setdefault(get_catalogue_risk_key(code), []).append((code, details))
    for room_entries in risk_groups.values():
        room_entries.sort(key=lambda item: item[0])
        pdf_url = next((details.get("pdf") for _, details in room_entries if details.get("pdf")), "")
        toc_pages = get_pdf_contents_link_pages(pdf_url)
        if len(toc_pages) >= len(room_entries):
            for index, (code, _) in enumerate(room_entries):
                updated_map[code]["page"] = toc_pages[index]
    return updated_map


def load_catalogue_metadata(risk_key):
    empty_metadata = {"current_file": "", "source_url": "", "doc_id": "", "last_updated": ""}
    if not risk_key:
        return empty_metadata
    return load_all_catalogue_metadata().get(risk_key, empty_metadata)


def load_all_catalogue_metadata():
    defaults = {
        "medium": {"current_file": "", "source_url": "", "doc_id": "", "last_updated": ""},
        "high": {"current_file": "", "source_url": "", "doc_id": "", "last_updated": ""},
        "low": {"current_file": "", "source_url": "", "doc_id": "", "last_updated": ""},
        "office": {"current_file": "", "source_url": "", "doc_id": "", "last_updated": ""},
    }
    metadata = read_json_file(get_catalogue_metadata_path(), {})
    for risk_key, default_value in defaults.items():
        merged = dict(default_value)
        merged.update(metadata.get(risk_key, {}))
        defaults[risk_key] = merged
    return defaults


def save_all_catalogue_metadata(metadata):
    metadata_path = get_catalogue_metadata_path()
    os.makedirs(os.path.dirname(metadata_path), exist_ok=True)
    with open(metadata_path, "w", encoding="utf-8") as metadata_file:
        json.dump(metadata, metadata_file, indent=2)


def refresh_catalogue_from_source(risk_area, force=False):
    details = load_all_catalogue_metadata().get(risk_area, {})
    source_url = details.get("source_url", "").strip()
    if not source_url:
        return False

    now = datetime.now()
    with _CATALOGUE_REFRESH_LOCK:
        state = _CATALOGUE_REFRESH_STATE.setdefault(risk_area, {"running": False, "last_attempt": None})
        last_attempt = state.get("last_attempt")
        if state["running"] or (not force and last_attempt and (now - last_attempt).total_seconds() < CATALOGUE_AUTO_REFRESH_SECONDS):
            return False
        state["running"] = True
        state["last_attempt"] = now

    try:
        pdf_bytes, doc_id = download_google_doc_pdf(source_url)
        catalogue_dir = get_catalogue_dir()
        os.makedirs(catalogue_dir, exist_ok=True)
        file_name = get_catalogue_current_file_name(risk_area)
        pdf_path = os.path.join(catalogue_dir, file_name)
        existing_digest = ""
        if os.path.exists(pdf_path):
            with open(pdf_path, "rb") as existing_file:
                existing_digest = hashlib.sha256(existing_file.read()).hexdigest()
        incoming_digest = hashlib.sha256(pdf_bytes).hexdigest()
        changed = incoming_digest != existing_digest
        if changed:
            temp_path = f"{pdf_path}.tmp"
            with open(temp_path, "wb") as pdf_file:
                pdf_file.write(pdf_bytes)
            os.replace(temp_path, pdf_path)
            _CATALOGUE_TOC_CACHE.clear()
            _CATALOGUE_ASSET_COUNT_CACHE.clear()

        with _CATALOGUE_METADATA_LOCK:
            metadata = load_all_catalogue_metadata()
            current_details = metadata.get(risk_area, {})
            current_details.update({
                "current_file": file_name,
                "source_url": source_url,
                "doc_id": doc_id,
                "auto_refresh": True,
                "refresh_interval_minutes": CATALOGUE_AUTO_REFRESH_SECONDS // 60,
                "last_checked": now.strftime("%Y-%m-%d %H:%M:%S"),
                "refresh_error": "",
            })
            if changed or not current_details.get("last_updated"):
                current_details["last_updated"] = now.strftime("%Y-%m-%d %H:%M:%S")
            metadata[risk_area] = current_details
            save_all_catalogue_metadata(metadata)
        return changed
    except Exception as error:
        with _CATALOGUE_METADATA_LOCK:
            metadata = load_all_catalogue_metadata()
            current_details = metadata.get(risk_area, {})
            current_details.update({
                "auto_refresh": True,
                "last_checked": now.strftime("%Y-%m-%d %H:%M:%S"),
                "refresh_error": str(error),
            })
            metadata[risk_area] = current_details
            save_all_catalogue_metadata(metadata)
        return False
    finally:
        with _CATALOGUE_REFRESH_LOCK:
            _CATALOGUE_REFRESH_STATE[risk_area]["running"] = False


def schedule_catalogue_refresh(risk_area, force=False):
    if not risk_area or not load_catalogue_metadata(risk_area).get("source_url"):
        return
    threading.Thread(
        target=refresh_catalogue_from_source,
        args=(risk_area, force),
        daemon=True,
        name=f"catalogue-refresh-{risk_area}",
    ).start()


def apply_current_catalogue_files(catalogue_map):
    metadata = load_all_catalogue_metadata()
    versioned_map = {}
    for code, details in catalogue_map.items():
        risk_key = get_catalogue_risk_key(code)
        current_file = metadata.get(risk_key, {}).get("current_file")
        versioned_map[code] = {**details, "pdf": get_catalogue_pdf_url(current_file) if current_file else ""}
    return versioned_map


def normalize_catalogue_pdf_text(text):
    return (text or "").replace("\u200b", "").replace("\ufeff", "")


def count_catalogue_page_assets(pdf_path, page_number):
    if not fitz or not pdf_path or not page_number:
        return None
    signature = get_file_signature(pdf_path)
    if not signature:
        return None
    cache_key = (pdf_path, signature, int(page_number))
    if cache_key in _CATALOGUE_ASSET_COUNT_CACHE:
        return _CATALOGUE_ASSET_COUNT_CACHE[cache_key]
    try:
        with fitz.open(pdf_path) as document:
            page_index = int(page_number) - 1
            if page_index < 0 or page_index >= document.page_count:
                return None
            text = normalize_catalogue_pdf_text(document[page_index].get_text())
    except Exception:
        return None
    count = 0
    for line in text.splitlines():
        match = re.match(r"\s*[●•]\s*(\d+)\b", line)
        if match:
            count += int(match.group(1))
    _CATALOGUE_ASSET_COUNT_CACHE[cache_key] = count
    return count


def build_catalogue_asset_counts():
    current_catalogue_map = apply_catalogue_toc_pages(
        apply_room_overrides(apply_current_catalogue_files(CATALOGUE_PAGE_MAP))
    )
    counts = {}
    for code, details in current_catalogue_map.items():
        pdf_url = details.get("pdf")
        page_number = details.get("page")
        count = count_catalogue_page_assets(get_catalogue_pdf_path(pdf_url), page_number) if pdf_url else None
        counts[code] = {
            "asset_count": count if count is not None else 0,
            "page": page_number,
            "source": "catalogue_pdf" if count is not None else "missing",
        }
    return counts


def load_layout_source_config():
    config = copy.deepcopy(LAYOUT_SOURCE_DEFAULTS)
    saved = read_json_file(LAYOUT_SOURCE_CONFIG_PATH, {})
    config["source_pptx"] = saved.get("source_pptx") or config["source_pptx"]
    for key, defaults in LAYOUT_SOURCE_DEFAULTS["layouts"].items():
        saved_layout = (saved.get("layouts") or {}).get(key) or {}
        merged = {**defaults, **saved_layout, "image": defaults["image"], "label": saved_layout.get("label") or defaults["label"]}
        try:
            merged["slide"] = max(1, int(merged.get("slide") or defaults["slide"]))
        except (TypeError, ValueError):
            merged["slide"] = defaults["slide"]
        try:
            merged["target_width"] = max(800, int(merged.get("target_width") or defaults["target_width"]))
        except (TypeError, ValueError):
            merged["target_width"] = defaults["target_width"]
        merged["picture"] = str(merged.get("picture") or defaults["picture"]).strip()
        config["layouts"][key] = merged
    return config


def save_layout_source_config(config):
    os.makedirs(os.path.dirname(LAYOUT_SOURCE_CONFIG_PATH), exist_ok=True)
    with open(LAYOUT_SOURCE_CONFIG_PATH, "w", encoding="utf-8") as config_file:
        json.dump(config, config_file, indent=2)


def get_layout_source_pptx_path(config):
    return os.path.join(BASE_DIR, config.get("source_pptx") or LAYOUT_SOURCE_DEFAULTS["source_pptx"])


def get_pptx_slide_count(pptx_path):
    try:
        from pptx import Presentation
        return len(Presentation(pptx_path).slides)
    except Exception:
        return None


def build_layout_source_payload():
    config = load_layout_source_config()
    metadata = read_json_file(LAYOUT_METADATA_PATH, {})
    pptx_path = get_layout_source_pptx_path(config)
    layouts = {}
    for key, details in config["layouts"].items():
        layout_metadata = metadata.get(key) or {}
        room_source = "room_shapes.json" if key == "factory" else "office_layout_shapes.json"
        rooms_payload = read_json_file(os.path.join(FRONTEND_STATIC_DATA_DIR, room_source), {})
        room_count = len(rooms_payload) if key == "factory" else len((rooms_payload or {}).get(key) or {})
        layouts[key] = {
            **details,
            "width": layout_metadata.get("width"),
            "height": layout_metadata.get("height"),
            "aspect": layout_metadata.get("aspect"),
            "room_count": room_count,
        }
    return {
        "source_pptx": config["source_pptx"],
        "source_name": os.path.basename(config["source_pptx"]),
        "source_exists": os.path.exists(pptx_path),
        "slide_count": get_pptx_slide_count(pptx_path) if os.path.exists(pptx_path) else None,
        "layouts": layouts,
    }


def rebuild_layout_sources():
    result = subprocess.run(
        [sys.executable, "extract_ppt_shapes.py"],
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "Unknown PowerPoint extraction error").strip())
    _CATALOGUE_ASSET_COUNT_CACHE.clear()
    return result.stdout.strip()


@app.route("/")
def root():
    return send_from_directory(FRONTEND_DIR, "layout_map.html")


@app.route("/layout")
def layout_map():
    return send_from_directory(FRONTEND_DIR, "layout_map.html")


@app.route("/catalogue/<room_code>")
def catalogue_view(room_code):
    normalized_code = room_code.strip().upper()
    risk_key = get_catalogue_risk_key(normalized_code)
    schedule_catalogue_refresh(risk_key)
    room_prefix = normalized_code[:1]
    catalogue_metadata = load_catalogue_metadata(risk_key)
    current_catalogue_map = apply_room_overrides(apply_current_catalogue_files(CATALOGUE_PAGE_MAP))
    risk_catalogue_map = apply_catalogue_toc_pages({
        code: details for code, details in current_catalogue_map.items() if code.startswith(f"{room_prefix}-")
    })
    catalogue = risk_catalogue_map.get(normalized_code)
    risk_catalogue_map = with_catalogue_pdf_versions(risk_catalogue_map)
    pdf_version = get_catalogue_pdf_version(catalogue["pdf"]) if catalogue else None
    return render_template(
        "catalogue_view.html",
        room_code=normalized_code,
        room_name=catalogue.get("name") if catalogue else None,
        page_number=catalogue.get("page") if catalogue and catalogue.get("pdf") else None,
        pdf_url=catalogue.get("pdf") if catalogue else None,
        pdf_version=pdf_version if catalogue and catalogue.get("pdf") else None,
        risk_key=risk_key,
        catalogue_metadata=catalogue_metadata,
        risk_catalogue_map=risk_catalogue_map,
    )


@app.route("/catalogue/machines/manage")
@app.route("/catalogue/manage/machines")
def catalogue_machine_manager():
    return send_from_directory(FRONTEND_DIR, "machine_capacity_admin.html")


@app.route("/catalogue/manage")
def catalogue_management_page():
    return send_from_directory(FRONTEND_DIR, "catalogue_management.html")


@app.route("/catalogue/manage/rooms")
def catalogue_room_management_page():
    return send_from_directory(FRONTEND_DIR, "catalogue_rooms_admin.html")


@app.route("/catalogue/manage/create")
def catalogue_create_page():
    return send_from_directory(FRONTEND_DIR, "catalogue_create.html")


@app.route("/catalogue/custom/<slug>")
def custom_catalogue_view(slug):
    catalogue = get_custom_catalogue(slug)
    return render_template("custom_catalogue_view.html", custom_catalogue=catalogue), 200 if catalogue else 404


@app.route("/api/catalogue/status/<risk_area>")
def catalogue_status(risk_area):
    normalized_risk = risk_area.strip().lower()
    if normalized_risk not in {"medium", "high", "low", "office"}:
        return jsonify({"error": "Invalid catalogue area"}), 400
    schedule_catalogue_refresh(normalized_risk)
    metadata = load_catalogue_metadata(normalized_risk)
    current_file = metadata.get("current_file", "")
    pdf_url = get_catalogue_pdf_url(current_file) if current_file else ""
    return jsonify({
        "risk_area": normalized_risk,
        "version": get_catalogue_pdf_version(pdf_url) if pdf_url else "missing",
        "metadata": metadata,
    })


@app.route("/api/catalogue/layout-source")
def catalogue_layout_source():
    return jsonify(build_layout_source_payload())


@app.route("/api/catalogue/layout-source", methods=["POST"])
def update_catalogue_layout_source():
    config = load_layout_source_config()
    pptx_file = request.files.get("pptx_file")
    if pptx_file and pptx_file.filename:
        if not pptx_file.filename.lower().endswith(".pptx"):
            return jsonify({"error": "Upload a .pptx PowerPoint file"}), 400
        pptx_path = get_layout_source_pptx_path(config)
        os.makedirs(os.path.dirname(pptx_path), exist_ok=True)
        pptx_file.save(pptx_path)

    for key, defaults in LAYOUT_SOURCE_DEFAULTS["layouts"].items():
        current = config["layouts"].get(key, copy.deepcopy(defaults))
        try:
            slide_number = int(request.form.get(f"slide:{key}", current.get("slide")))
            target_width = int(request.form.get(f"target_width:{key}", current.get("target_width")))
        except (TypeError, ValueError):
            return jsonify({"error": f"{current.get('label', key)} needs valid slide and export width values"}), 400
        picture_value = request.form.get(f"picture:{key}", current.get("picture", "")).strip()
        if slide_number < 1 or target_width < 800 or target_width > 10000 or not picture_value:
            return jsonify({"error": f"{current.get('label', key)} has invalid layout settings"}), 400
        config["layouts"][key] = {
            **current,
            "label": defaults["label"],
            "image": defaults["image"],
            "slide": slide_number,
            "picture": picture_value,
            "target_width": target_width,
        }

    slide_count = get_pptx_slide_count(get_layout_source_pptx_path(config))
    if slide_count:
        for details in config["layouts"].values():
            if details["slide"] > slide_count:
                return jsonify({"error": f"{details['label']} points to slide {details['slide']}, but the deck only has {slide_count} slides"}), 400
    save_layout_source_config(config)
    try:
        rebuild_output = rebuild_layout_sources()
    except Exception as error:
        return jsonify({"error": f"Unable to rebuild the PowerPoint layout maps: {error}"}), 500
    return jsonify({"success": True, "message": rebuild_output, "layout_source": build_layout_source_payload()})


@app.route("/api/catalogue/machines")
def catalogue_machines():
    return jsonify(list_machines(request.args.get("room")))


@app.route("/api/catalogue/machines", methods=["POST"])
def save_catalogue_machine():
    return jsonify({"machine": upsert_machine(request.get_json(silent=True) or {})})


@app.route("/api/catalogue/machines/<machine_id>", methods=["DELETE"])
def remove_catalogue_machine(machine_id):
    deleted = delete_machine(machine_id)
    return jsonify({"deleted": deleted}), 200 if deleted else 404


@app.route("/api/catalogue/asset-counts")
def catalogue_asset_counts():
    return jsonify({"counts": build_catalogue_asset_counts()})


@app.route("/api/catalogue/rooms")
def catalogue_rooms():
    current_catalogue_map = apply_room_overrides(apply_current_catalogue_files(CATALOGUE_PAGE_MAP))
    layout_labels = {
        "high": "Factory - High Risk",
        "medium": "Factory - Medium Risk",
        "low": "Factory - Low Risk",
        "office": "Incoming Warehouse Office",
    }
    room_rows = [
        {
            "code": code,
            "name": details.get("name", ""),
            "default_name": details.get("defaultName", details.get("name", "")),
            "name_override": details.get("nameOverride", ""),
            "page": details.get("page"),
            "risk_key": get_catalogue_risk_key(code),
            "layout": layout_labels.get(get_catalogue_risk_key(code), "Factory"),
        }
        for code, details in current_catalogue_map.items()
    ]
    return jsonify(sorted(room_rows, key=lambda row: (row["layout"], row["code"])))


@app.route("/api/catalogue/rooms", methods=["POST"])
def save_catalogue_room():
    try:
        room = upsert_room_override(request.get_json(silent=True) or {})
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    return jsonify({"room": room})


@app.route("/api/catalogue/custom")
def list_custom_catalogue_api():
    return jsonify([
        {
            "slug": item.get("slug"),
            "title": item.get("title"),
            "doc_url": item.get("doc_url"),
            "created_at": item.get("created_at"),
            "updated_at": item.get("updated_at"),
            "slide_number": item.get("slide_number"),
            "picture_name": item.get("picture_name"),
            "room_count": item.get("room_count", len(item.get("rooms", {}))),
            "view_url": f"/catalogue/custom/{item.get('slug')}",
        }
        for item in load_custom_catalogues()
    ])


@app.route("/api/catalogue/custom/<slug>")
def get_custom_catalogue_api(slug):
    catalogue = get_custom_catalogue(slug)
    if not catalogue:
        return jsonify({"error": "Custom catalogue not found"}), 404
    return jsonify(catalogue)


@app.route("/api/catalogue/custom", methods=["POST"])
def create_custom_catalogue_api():
    title = request.form.get("title", "").strip()
    doc_url = request.form.get("doc_url", "").strip()
    pptx_file = request.files.get("pptx_file")
    if not title:
        return jsonify({"error": "Catalogue name is required"}), 400
    if not doc_url:
        return jsonify({"error": "Google Docs link is required"}), 400
    if not pptx_file or not pptx_file.filename:
        return jsonify({"error": "PowerPoint file is required"}), 400
    if not pptx_file.filename.lower().endswith(".pptx"):
        return jsonify({"error": "Upload a .pptx PowerPoint file"}), 400
    try:
        pdf_bytes, _doc_id = download_google_doc_pdf(doc_url)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except Exception as error:
        return jsonify({"error": f"Unable to reach the public Google Doc. Technical detail: {error}"}), 502

    temp_dir = os.path.join(DATA_DIR, "custom_catalogue_uploads", "_incoming")
    os.makedirs(temp_dir, exist_ok=True)
    temp_path = os.path.join(temp_dir, secure_filename(pptx_file.filename) or "catalogue_upload.pptx")
    pptx_file.save(temp_path)
    try:
        catalogue = create_custom_catalogue(
            title,
            doc_url,
            temp_path,
            pdf_bytes,
            {
                "slide_number": request.form.get("slide_number", "1"),
                "picture_name": request.form.get("picture_name", ""),
                "target_width": request.form.get("target_width", "3600"),
            },
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except Exception as error:
        return jsonify({"error": f"Unable to process the PowerPoint file: {error}"}), 500
    return jsonify({
        "catalogue": {
            "slug": catalogue["slug"],
            "title": catalogue["title"],
            "room_count": catalogue["room_count"],
            "view_url": f"/catalogue/custom/{catalogue['slug']}",
        }
    }), 201


@app.route("/catalogue/upload", methods=["POST"])
def upload_catalogue():
    risk_area = request.form.get("risk_area", "").strip().lower()
    doc_url = request.form.get("doc_url", "").strip()
    if risk_area not in {"medium", "high", "low", "office"}:
        return jsonify({"error": "Invalid catalogue area"}), 400
    if not doc_url:
        return jsonify({"error": "Google Docs link is required"}), 400
    try:
        pdf_bytes, doc_id = download_google_doc_pdf(doc_url)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except Exception as error:
        return jsonify({"error": f"Unable to reach the public Google Doc. Technical detail: {error}"}), 502

    catalogue_dir = get_catalogue_dir()
    os.makedirs(catalogue_dir, exist_ok=True)
    metadata = load_all_catalogue_metadata()
    current_file = metadata.get(risk_area, {}).get("current_file", "")
    file_name = get_catalogue_current_file_name(risk_area)
    if current_file and current_file != file_name:
        old_path = os.path.join(catalogue_dir, secure_filename(current_file))
        if os.path.exists(old_path):
            os.remove(old_path)
    with open(os.path.join(catalogue_dir, file_name), "wb") as pdf_file:
        pdf_file.write(pdf_bytes)
    metadata[risk_area] = {
        "current_file": file_name,
        "source_url": doc_url,
        "doc_id": doc_id,
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "last_checked": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "auto_refresh": True,
        "refresh_interval_minutes": CATALOGUE_AUTO_REFRESH_SECONDS // 60,
        "refresh_error": "",
    }
    save_all_catalogue_metadata(metadata)
    _CATALOGUE_TOC_CACHE.clear()
    _CATALOGUE_ASSET_COUNT_CACHE.clear()
    return jsonify({"success": True, "risk_area": risk_area, "metadata": metadata[risk_area]})


@app.route("/<path:path>")
def frontend_files(path):
    return send_from_directory(FRONTEND_DIR, path)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5001"))
    app.run(host="0.0.0.0", port=port, debug=False)
