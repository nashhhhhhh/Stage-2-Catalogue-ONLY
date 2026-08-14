from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import ProxyHandler, Request, build_opener

from flask import Flask, jsonify, redirect, render_template, request, send_from_directory, url_for
from werkzeug.utils import secure_filename

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
DATA_DIR = os.path.join(BASE_DIR, "data")
BACKEND_DIR = os.path.join(BASE_DIR, "backend")
sys.path.insert(0, BACKEND_DIR)

from custom_catalogue_service import (
    create_custom_catalogue,
    get_pdf_contents_links,
    get_custom_catalogue,
    load_custom_catalogues,
    match_pdf_headers_to_rooms,
    match_pdf_pages_to_rooms,
    rebuild_custom_catalogue,
    save_custom_catalogues,
    upsert_custom_catalogue_room,
)
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


@app.after_request
def prevent_stale_custom_catalogue_assets(response):
    if request.path.startswith((
        "/api/catalogue/custom",
        "/static/custom_catalogues/",
        "/catalogue/custom/",
    )) or request.path in {"/", "/layout"}:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

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
_CATALOGUE_ROOM_PAGE_CACHE = {}
_CATALOGUE_ASSET_COUNT_CACHE = {}
_CUSTOM_CATALOGUE_REFRESH_STATE = {}
_CUSTOM_CATALOGUE_REFRESH_LOCK = threading.Lock()
_CUSTOM_CATALOGUE_REGISTRY_LOCK = threading.Lock()


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
    # Google can cache repeated export URLs for a short time. A unique query
    # value makes a manual refresh retrieve the current document contents.
    opener = build_opener(ProxyHandler({}))
    last_error = None
    for attempt in range(3):
        export_params = {
            "format": "pdf",
            "_refresh": str(int(datetime.now().timestamp() * 1_000_000)),
        }
        if tab_id:
            export_params["tab"] = tab_id
        export_url = f"https://docs.google.com/document/d/{doc_id}/export?{urlencode(export_params)}"
        try:
            with opener.open(Request(export_url, headers={
                "User-Agent": "Mozilla/5.0",
                "Cache-Control": "no-cache, no-store, max-age=0",
                "Pragma": "no-cache",
            }), timeout=180) as response:
                pdf_bytes = response.read()
            if pdf_bytes.startswith(b"%PDF"):
                return pdf_bytes, doc_id
            last_error = ValueError(
                "Google Docs did not return a PDF. Check that the document is shared so anyone with the link can view it."
            )
        except Exception as error:
            last_error = error
        if attempt < 2:
            time.sleep(0.75 * (attempt + 1))
    if isinstance(last_error, ValueError):
        raise last_error
    raise RuntimeError(
        "Google Docs could not be downloaded after 3 attempts. Check sharing permissions and try again. "
        f"Technical detail: {last_error}"
    ) from last_error


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

    # PyMuPDF resolves Google Docs named destinations without loading and
    # scanning the complete PDF byte stream. Catalogue links use the same
    # wide, 108-point-indented rectangles in each exported document.
    if fitz:
        try:
            with fitz.open(pdf_path) as document:
                link_pages = []
                for page in document:
                    for link in page.get_links():
                        rectangle = link.get("from")
                        destination_page = link.get("page")
                        if (
                            rectangle
                            and isinstance(destination_page, int)
                            and destination_page >= 0
                            and abs(rectangle.x0 - 108) < 0.5
                            and rectangle.width > 250
                        ):
                            link_pages.append(destination_page + 1)
                if link_pages:
                    _CATALOGUE_TOC_CACHE[cache_key] = link_pages
                    return link_pages
        except Exception:
            # Retain the byte-level parser below for unusual PDFs that
            # PyMuPDF cannot open or whose links it cannot resolve.
            pass

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
        pdf_path = get_catalogue_pdf_path(pdf_url) if pdf_url else ""
        signature = get_file_signature(pdf_path) if pdf_path else None
        if not signature:
            continue

        room_signature = tuple(
            (code, details.get("name", ""), details.get("page"))
            for code, details in room_entries
        )
        cache_key = (pdf_path, signature, room_signature)
        detected_pages = _CATALOGUE_ROOM_PAGE_CACHE.get(cache_key)
        if detected_pages is None:
            detected_pages = {}
            try:
                with open(pdf_path, "rb") as pdf_file:
                    pdf_bytes = pdf_file.read()
                rooms = {
                    code: {**details, "code": code}
                    for code, details in room_entries
                }

                # Match the Google Docs contents links by room code/name first.
                # Unlike the old positional mapper, one missing contents entry
                # does not shift or disable every room below it.
                matched_rooms, link_match_count = match_pdf_pages_to_rooms(
                    rooms,
                    get_pdf_contents_links(pdf_bytes),
                )

                # Visible headings at the top of each PDF page are the final
                # source of truth. They double-check links and correct shifted
                # page numbers after pages are inserted in Google Docs.
                verified_rooms, header_match_count = match_pdf_headers_to_rooms(
                    matched_rooms,
                    pdf_bytes,
                )
                if link_match_count or header_match_count:
                    detected_pages = {
                        code: int(room["page"])
                        for code, room in verified_rooms.items()
                        if room.get("page") not in (None, "")
                    }
            except Exception:
                detected_pages = {}

            # Retain the original all-or-nothing positional fallback only for
            # unusual PDFs where neither link text nor visible headings can be
            # read reliably.
            if not detected_pages:
                toc_pages = get_pdf_contents_link_pages(pdf_url)
                if len(toc_pages) >= len(room_entries):
                    detected_pages = {
                        code: toc_pages[index]
                        for index, (code, _) in enumerate(room_entries)
                    }
            _CATALOGUE_ROOM_PAGE_CACHE[cache_key] = detected_pages

        for code, page_number in detected_pages.items():
            if code in updated_map:
                updated_map[code]["page"] = page_number
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
    temp_path = f"{metadata_path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as metadata_file:
        json.dump(metadata, metadata_file, indent=2)
    os.replace(temp_path, metadata_path)


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
            _CATALOGUE_ROOM_PAGE_CACHE.clear()
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


def update_custom_catalogue_metadata(slug, updates):
    with _CUSTOM_CATALOGUE_REGISTRY_LOCK:
        catalogues = load_custom_catalogues()
        updated_catalogue = None
        for catalogue in catalogues:
            if catalogue.get("slug") == slug:
                catalogue.update(updates)
                updated_catalogue = catalogue
                break
        if updated_catalogue is not None:
            save_custom_catalogues(catalogues)
        return updated_catalogue


def refresh_custom_catalogue_from_source(slug, force=False):
    catalogue = get_custom_catalogue(slug)
    if not catalogue:
        return False
    source_url = (catalogue.get("doc_url") or "").strip()
    if not source_url:
        return False

    now = datetime.now()
    with _CUSTOM_CATALOGUE_REFRESH_LOCK:
        state = _CUSTOM_CATALOGUE_REFRESH_STATE.setdefault(slug, {"running": False, "last_attempt": None})
        last_attempt = state.get("last_attempt")
        if state["running"] or (
            not force
            and last_attempt
            and (now - last_attempt).total_seconds() < CATALOGUE_AUTO_REFRESH_SECONDS
        ):
            return False
        state["running"] = True
        state["last_attempt"] = now

    try:
        pdf_bytes, _doc_id = download_google_doc_pdf(source_url)
        pdf_url = (catalogue.get("layout") or {}).get("pdf", "")
        pdf_path = get_catalogue_pdf_path(pdf_url) if pdf_url else ""
        existing_digest = ""
        if pdf_path and os.path.exists(pdf_path):
            with open(pdf_path, "rb") as existing_file:
                existing_digest = hashlib.sha256(existing_file.read()).hexdigest()
        changed = hashlib.sha256(pdf_bytes).hexdigest() != existing_digest
        if changed:
            rebuild_custom_catalogue(slug, pdf_bytes=pdf_bytes)

        updates = {
            "auto_refresh": True,
            "refresh_interval_minutes": CATALOGUE_AUTO_REFRESH_SECONDS // 60,
            "last_checked": now.strftime("%Y-%m-%d %H:%M:%S"),
            "refresh_error": "",
        }
        if changed or not catalogue.get("last_updated"):
            updates["last_updated"] = now.strftime("%Y-%m-%d %H:%M:%S")
        update_custom_catalogue_metadata(slug, updates)
        return changed
    except Exception as error:
        update_custom_catalogue_metadata(slug, {
            "auto_refresh": True,
            "refresh_interval_minutes": CATALOGUE_AUTO_REFRESH_SECONDS // 60,
            "last_checked": now.strftime("%Y-%m-%d %H:%M:%S"),
            "refresh_error": str(error),
        })
        return False
    finally:
        with _CUSTOM_CATALOGUE_REFRESH_LOCK:
            _CUSTOM_CATALOGUE_REFRESH_STATE[slug]["running"] = False


def schedule_custom_catalogue_refresh(slug, force=False):
    catalogue = get_custom_catalogue(slug)
    if not catalogue or not (catalogue.get("doc_url") or "").strip():
        return
    threading.Thread(
        target=refresh_custom_catalogue_from_source,
        args=(slug, force),
        daemon=True,
        name=f"custom-catalogue-refresh-{slug}",
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


def count_catalogue_assets_for_pages(pdf_path, page_numbers):
    """Count several catalogue pages while opening the PDF only once."""
    results = {}
    if not fitz or not pdf_path:
        return results
    signature = get_file_signature(pdf_path)
    if not signature:
        return results

    requested_pages = sorted({int(page) for page in page_numbers if page})
    uncached_pages = []
    for page_number in requested_pages:
        cache_key = (pdf_path, signature, page_number)
        if cache_key in _CATALOGUE_ASSET_COUNT_CACHE:
            results[page_number] = _CATALOGUE_ASSET_COUNT_CACHE[cache_key]
        else:
            uncached_pages.append(page_number)

    if not uncached_pages:
        return results

    try:
        with fitz.open(pdf_path) as document:
            for page_number in uncached_pages:
                page_index = page_number - 1
                if page_index < 0 or page_index >= document.page_count:
                    continue
                text = normalize_catalogue_pdf_text(document[page_index].get_text())
                count = 0
                for line in text.splitlines():
                    match = re.match(r"\s*[●•]\s*(\d+)\b", line)
                    if match:
                        count += int(match.group(1))
                cache_key = (pdf_path, signature, page_number)
                _CATALOGUE_ASSET_COUNT_CACHE[cache_key] = count
                results[page_number] = count
    except Exception:
        return results
    return results


def build_catalogue_asset_counts():
    current_catalogue_map = apply_catalogue_toc_pages(
        apply_room_overrides(apply_current_catalogue_files(CATALOGUE_PAGE_MAP))
    )
    counts = {}
    rooms_by_pdf = {}
    for code, details in current_catalogue_map.items():
        pdf_url = details.get("pdf")
        page_number = details.get("page")
        if pdf_url and page_number:
            pdf_path = get_catalogue_pdf_path(pdf_url)
            rooms_by_pdf.setdefault(pdf_path, []).append((code, int(page_number)))
        counts[code] = {
            "asset_count": 0,
            "page": page_number,
            "source": "missing",
        }

    for pdf_path, room_entries in rooms_by_pdf.items():
        page_counts = count_catalogue_assets_for_pages(
            pdf_path,
            (page_number for _, page_number in room_entries),
        )
        for code, page_number in room_entries:
            if page_number in page_counts:
                counts[code].update({
                    "asset_count": page_counts[page_number],
                    "source": "catalogue_pdf",
                })
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


def build_catalogue_management_payload():
    metadata = load_all_catalogue_metadata()
    layout_source = build_layout_source_payload()
    built_in_titles = {
        "medium": "Factory - Medium Risk",
        "high": "Factory - High Risk",
        "low": "Factory - Low Risk",
        "office": "Incoming Warehouse Office",
    }
    catalogues = []
    for risk_area, title in built_in_titles.items():
        details = metadata.get(risk_area, {})
        layout_keys = ["incoming-office-level-1", "incoming-office-level-2"] if risk_area == "office" else ["factory"]
        catalogues.append({
            "id": f"area:{risk_area}",
            "kind": "area",
            "risk_area": risk_area,
            "title": title,
            "source_url": details.get("source_url", ""),
            "last_checked": details.get("last_checked", ""),
            "last_updated": details.get("last_updated", ""),
            "refresh_error": details.get("refresh_error", ""),
            "refresh_interval_minutes": details.get("refresh_interval_minutes", CATALOGUE_AUTO_REFRESH_SECONDS // 60),
            "source_pptx": layout_source.get("source_pptx", ""),
            "source_name": layout_source.get("source_name", ""),
            "source_exists": layout_source.get("source_exists", False),
            "slide_count": layout_source.get("slide_count"),
            "shared_layout": True,
            "layouts": {
                key: layout_source.get("layouts", {}).get(key, {})
                for key in layout_keys
            },
        })

    for item in load_custom_catalogues():
        slug = item.get("slug")
        if not slug:
            continue
        layout = item.get("layout") or {}
        source_pptx = item.get("source_pptx", "")
        source_pptx_path = os.path.join(BASE_DIR, source_pptx) if source_pptx else ""
        saved_layouts = item.get("layouts") or [{
            "key": "custom",
            "label": item.get("title") or slug,
            "slide_number": item.get("slide_number", 1),
            "picture_name": item.get("picture_name", ""),
            "image": layout.get("image", ""),
            "width": layout.get("width"),
            "height": layout.get("height"),
            "aspect": layout.get("aspect"),
            "room_codes": list((item.get("rooms") or {}).keys()),
            "room_count": item.get("room_count", len(item.get("rooms") or {})),
        }]
        catalogues.append({
            "id": f"custom:{slug}",
            "kind": "custom",
            "slug": slug,
            "title": item.get("title") or slug,
            "source_url": item.get("doc_url", ""),
            "last_checked": item.get("last_checked", ""),
            "last_updated": item.get("last_updated", item.get("updated_at", "")),
            "refresh_error": item.get("refresh_error", ""),
            "refresh_interval_minutes": item.get("refresh_interval_minutes", CATALOGUE_AUTO_REFRESH_SECONDS // 60),
            "source_pptx": source_pptx,
            "source_name": os.path.basename(source_pptx),
            "source_exists": bool(source_pptx_path and os.path.isfile(source_pptx_path)),
            "slide_count": get_pptx_slide_count(source_pptx_path) if source_pptx_path else None,
            "shared_layout": False,
            "room_count": item.get("room_count", len(item.get("rooms") or {})),
            "layouts": {
                saved_layout.get("key", f"slide-{saved_layout.get('slide_number', 1)}"): {
                    "label": saved_layout.get("label") or item.get("title") or slug,
                    "slide": saved_layout.get("slide_number", 1),
                    "picture": saved_layout.get("picture_name", ""),
                    "target_width": layout.get("width", 3600),
                    "width": saved_layout.get("width"),
                    "height": saved_layout.get("height"),
                    "aspect": saved_layout.get("aspect"),
                    "image": saved_layout.get("image", ""),
                    "room_count": saved_layout.get("room_count", len(saved_layout.get("room_codes") or [])),
                }
                for saved_layout in saved_layouts
            },
        })
    return {"catalogues": catalogues}


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


@app.route("/catalogue")
@app.route("/catalogue/")
def catalogue_home():
    return redirect(url_for("layout_map"))


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
    if catalogue:
        schedule_custom_catalogue_refresh(slug)
        catalogue = copy.deepcopy(catalogue)
        pdf_url = (catalogue.get("layout") or {}).get("pdf", "")
        catalogue["pdfVersion"] = get_catalogue_pdf_version(pdf_url)
        catalogue["refresh_interval_minutes"] = CATALOGUE_AUTO_REFRESH_SECONDS // 60
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


@app.route("/api/catalogue/management/catalogues")
def catalogue_management_catalogues():
    return jsonify(build_catalogue_management_payload())


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
    current_catalogue_map = apply_catalogue_toc_pages(
        apply_room_overrides(apply_current_catalogue_files(CATALOGUE_PAGE_MAP))
    )
    layout_labels = {
        "high": "Factory - High Risk",
        "medium": "Factory - Medium Risk",
        "low": "Factory - Low Risk",
        "office": "Incoming Warehouse Office",
    }
    selected_catalogue = request.args.get("catalogue", "").strip()
    built_in_rows = [
        {
            "code": code,
            "name": details.get("name", ""),
            "default_name": details.get("defaultName", details.get("name", "")),
            "name_override": details.get("nameOverride", ""),
            "page": details.get("page"),
            "risk_key": get_catalogue_risk_key(code),
            "layout": layout_labels.get(get_catalogue_risk_key(code), "Factory"),
            "catalogue_id": f"area:{get_catalogue_risk_key(code)}",
        }
        for code, details in current_catalogue_map.items()
    ]
    if not selected_catalogue:
        return jsonify(sorted(built_in_rows, key=lambda row: (row["layout"], row["code"])))
    if selected_catalogue.startswith("area:"):
        risk_key = selected_catalogue.removeprefix("area:")
        if risk_key not in {"medium", "high", "low", "office"}:
            return jsonify({"error": "Invalid catalogue"}), 400
        return jsonify(sorted(
            (row for row in built_in_rows if row["risk_key"] == risk_key),
            key=lambda row: row["code"],
        ))
    if selected_catalogue.startswith("custom:"):
        slug = selected_catalogue.removeprefix("custom:")
        catalogue = get_custom_catalogue(slug)
        if not catalogue:
            return jsonify({"error": "Catalogue not found"}), 404
        rows = [
            {
                "code": code,
                "name": details.get("name", ""),
                "default_name": details.get("defaultName", details.get("name", "")),
                "name_override": (catalogue.get("room_overrides") or {}).get(code, {}).get("name", ""),
                "page": details.get("page"),
                "risk_key": "catalogue",
                "layout": catalogue.get("title", slug),
                "catalogue_id": f"custom:{catalogue['slug']}",
            }
            for code, details in (catalogue.get("rooms") or {}).items()
        ]
        return jsonify(sorted(rows, key=lambda row: row["code"]))
    return jsonify({"error": "Invalid catalogue"}), 400


@app.route("/api/catalogue/room-catalogues")
def catalogue_room_catalogues():
    current_catalogue_map = apply_room_overrides(apply_current_catalogue_files(CATALOGUE_PAGE_MAP))
    built_in_labels = {
        "medium": "Factory - Medium Risk",
        "high": "Factory - High Risk",
        "low": "Factory - Low Risk",
        "office": "Incoming Warehouse Office",
    }
    counts = {key: 0 for key in built_in_labels}
    for code in current_catalogue_map:
        risk_key = get_catalogue_risk_key(code)
        if risk_key in counts:
            counts[risk_key] += 1
    catalogues = [
        {"id": f"area:{key}", "title": title, "room_count": counts[key]}
        for key, title in built_in_labels.items()
    ]
    catalogues.extend({
        "id": f"custom:{item.get('slug')}",
        "title": item.get("title") or item.get("slug"),
        "room_count": item.get("room_count", len(item.get("rooms") or {})),
    } for item in load_custom_catalogues() if item.get("slug"))
    return jsonify(catalogues)


@app.route("/api/catalogue/rooms", methods=["POST"])
def save_catalogue_room():
    payload = request.get_json(silent=True) or {}
    catalogue_id = str(payload.get("catalogue_id") or "").strip()
    try:
        if catalogue_id.startswith("custom:"):
            room = upsert_custom_catalogue_room(catalogue_id.removeprefix("custom:"), payload)
        else:
            room = upsert_room_override(payload)
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
            "slide_numbers": item.get("slide_numbers", [item.get("slide_number", 1)]),
            "picture_name": item.get("picture_name"),
            "room_count": item.get("room_count", len(item.get("rooms", {}))),
            "layout": item.get("layout", {}),
            "layouts": item.get("layouts", []),
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


@app.route("/api/catalogue/custom/<slug>/status")
def custom_catalogue_status(slug):
    catalogue = get_custom_catalogue(slug)
    if not catalogue:
        return jsonify({"error": "Custom catalogue not found"}), 404
    schedule_custom_catalogue_refresh(slug)
    pdf_url = (catalogue.get("layout") or {}).get("pdf", "")
    return jsonify({
        "slug": slug,
        "version": get_catalogue_pdf_version(pdf_url),
        "metadata": {
            "auto_refresh": bool(catalogue.get("doc_url")),
            "refresh_interval_minutes": CATALOGUE_AUTO_REFRESH_SECONDS // 60,
            "last_checked": catalogue.get("last_checked", ""),
            "last_updated": catalogue.get("last_updated", catalogue.get("updated_at", "")),
            "refresh_error": catalogue.get("refresh_error", ""),
        },
    })


@app.route("/api/catalogue/<risk_area>/refresh", methods=["POST"])
def refresh_area_catalogue_api(risk_area):
    normalized_risk = risk_area.strip().lower()
    if normalized_risk not in {"medium", "high", "low", "office"}:
        return jsonify({"error": "Invalid catalogue area"}), 400
    if not load_catalogue_metadata(normalized_risk).get("source_url"):
        return jsonify({"error": "This catalogue does not have a Google Docs source link"}), 400

    changed = refresh_catalogue_from_source(normalized_risk, force=True)
    metadata = load_catalogue_metadata(normalized_risk)
    current_file = metadata.get("current_file", "")
    pdf_url = get_catalogue_pdf_url(current_file) if current_file else ""
    refresh_error = metadata.get("refresh_error", "")
    response = {
        "changed": changed,
        "version": get_catalogue_pdf_version(pdf_url) if pdf_url else "missing",
        "metadata": metadata,
    }
    if refresh_error:
        response["error"] = refresh_error
        return jsonify(response), 502
    return jsonify(response)


@app.route("/api/catalogue/custom/<slug>/refresh", methods=["POST"])
def refresh_custom_catalogue_api(slug):
    if not get_custom_catalogue(slug):
        return jsonify({"error": "Custom catalogue not found"}), 404
    changed = refresh_custom_catalogue_from_source(slug, force=True)
    catalogue = get_custom_catalogue(slug) or {}
    pdf_url = (catalogue.get("layout") or {}).get("pdf", "")
    refresh_error = catalogue.get("refresh_error", "")
    response = {
        "changed": changed,
        "version": get_catalogue_pdf_version(pdf_url),
        "metadata": {
            "last_checked": catalogue.get("last_checked", ""),
            "last_updated": catalogue.get("last_updated", catalogue.get("updated_at", "")),
            "refresh_error": refresh_error,
        },
    }
    if refresh_error:
        response["error"] = refresh_error
        return jsonify(response), 502
    return jsonify(response)


@app.route("/api/catalogue/custom/<slug>/rebuild", methods=["POST"])
def rebuild_custom_catalogue_api(slug):
    try:
        catalogue = rebuild_custom_catalogue(slug)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except Exception as error:
        return jsonify({"error": f"Unable to rebuild the custom catalogue: {error}"}), 500
    return jsonify({
        "catalogue": {
            "slug": catalogue["slug"],
            "title": catalogue["title"],
            "room_count": catalogue["room_count"],
            "view_url": f"/catalogue/custom/{catalogue['slug']}",
        }
    })


@app.route("/api/catalogue/custom/<slug>/update", methods=["POST"])
def update_custom_catalogue_api(slug):
    current = get_custom_catalogue(slug)
    if not current:
        return jsonify({"error": "Catalogue not found"}), 404

    title = request.form.get("title", current.get("title", "")).strip()
    doc_url = request.form.get("doc_url", current.get("doc_url", "")).strip()
    pptx_file = request.files.get("pptx_file")
    if not title:
        return jsonify({"error": "Catalogue name is required"}), 400
    if not doc_url:
        return jsonify({"error": "Google Docs link is required"}), 400
    if pptx_file and pptx_file.filename and not pptx_file.filename.lower().endswith(".pptx"):
        return jsonify({"error": "Upload a .pptx PowerPoint file"}), 400

    current_pdf_url = (current.get("layout") or {}).get("pdf", "")
    current_pdf_path = get_catalogue_pdf_path(current_pdf_url) if current_pdf_url else ""
    source_changed = doc_url != (current.get("doc_url") or "").strip()
    try:
        if source_changed or not current_pdf_path or not os.path.isfile(current_pdf_path):
            pdf_bytes, _doc_id = download_google_doc_pdf(doc_url)
        else:
            with open(current_pdf_path, "rb") as pdf_file:
                pdf_bytes = pdf_file.read()
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except Exception as error:
        return jsonify({"error": f"Unable to reach the public Google Doc. Technical detail: {error}"}), 502

    source_pptx = os.path.join(BASE_DIR, current.get("source_pptx", ""))
    temp_path = ""
    if pptx_file and pptx_file.filename:
        temp_dir = os.path.join(DATA_DIR, "custom_catalogue_uploads", "_incoming")
        os.makedirs(temp_dir, exist_ok=True)
        temp_name = secure_filename(f"{current['slug']}-{pptx_file.filename}") or f"{current['slug']}-catalogue.pptx"
        temp_path = os.path.join(temp_dir, temp_name)
        pptx_file.save(temp_path)
        source_pptx = temp_path
    elif not os.path.isfile(source_pptx):
        return jsonify({"error": "The saved PowerPoint source for this catalogue is missing"}), 400

    picture_name = request.form.get("picture_name")
    if picture_name is None:
        picture_name = current.get("picture_name", "")
    try:
        catalogue = create_custom_catalogue(
            title,
            doc_url,
            source_pptx,
            pdf_bytes,
            {
                "slug": current["slug"],
                "created_at": current.get("created_at"),
                "slide_numbers": request.form.get(
                    "slide_numbers",
                    request.form.get("slide_number", ",".join(map(str, current.get("slide_numbers", [current.get("slide_number", 1)])))),
                ),
                "slide_number": request.form.get(
                    "slide_number",
                    request.form.get("slide_numbers", current.get("slide_number", 1)),
                ),
                "picture_name": picture_name,
                "target_width": request.form.get("target_width", (current.get("layout") or {}).get("width", 3600)),
                "last_checked": current.get("last_checked", "") if not source_changed else "",
                "last_updated": current.get("last_updated", "") if not source_changed else "",
                "refresh_error": "",
                "refresh_interval_minutes": current.get("refresh_interval_minutes", CATALOGUE_AUTO_REFRESH_SECONDS // 60),
                "room_overrides": current.get("room_overrides", {}),
            },
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except Exception as error:
        return jsonify({"error": f"Unable to rebuild the catalogue: {error}"}), 500
    finally:
        if temp_path:
            try:
                os.remove(temp_path)
            except FileNotFoundError:
                pass

    return jsonify({
        "success": True,
        "catalogue": {
            "slug": catalogue["slug"],
            "title": catalogue["title"],
            "room_count": catalogue["room_count"],
            "view_url": f"/catalogue/custom/{catalogue['slug']}",
        },
    })


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
                "slide_numbers": request.form.get("slide_numbers", request.form.get("slide_number", "all")),
                "picture_name": request.form.get("picture_name", ""),
                "target_width": request.form.get("target_width", "3600"),
            },
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except Exception as error:
        return jsonify({"error": f"Unable to process the PowerPoint file: {error}"}), 500
    finally:
        try:
            os.remove(temp_path)
        except FileNotFoundError:
            pass
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
    _CATALOGUE_ROOM_PAGE_CACHE.clear()
    _CATALOGUE_ASSET_COUNT_CACHE.clear()
    return jsonify({"success": True, "risk_area": risk_area, "metadata": metadata[risk_area]})


@app.route("/<path:path>")
def frontend_files(path):
    return send_from_directory(FRONTEND_DIR, path)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5001"))
    app.run(host="0.0.0.0", port=port, debug=False)
