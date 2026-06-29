import json
import math
import re
import shutil
from datetime import datetime
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageFilter
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
FRONTEND_DIR = BASE_DIR / "frontend"
CUSTOM_STATIC_DIR = FRONTEND_DIR / "static" / "custom_catalogues"
UPLOAD_DIR = DATA_DIR / "custom_catalogue_uploads"
REGISTRY_PATH = DATA_DIR / "custom_catalogues.json"

NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
SCHEME_COLORS = {"accent4": "8064A2"}
RISK_BY_PREFIX = {"M": "medium", "H": "high", "L": "low", "O": "office"}
DEFAULT_COLORS = {
    "medium": "0EA5E9",
    "high": "22C55E",
    "low": "EAB308",
    "office": "8064A2",
    "custom": "2563EB",
}


def rounded(value):
    return round(value, 4)


def slugify(value):
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "custom-catalogue"


def unique_slug(title):
    base_slug = slugify(title)
    registry = load_custom_catalogues()
    existing = {item.get("slug") for item in registry}
    slug = base_slug
    counter = 2
    while slug in existing:
        slug = f"{base_slug}-{counter}"
        counter += 1
    return slug


def load_custom_catalogues():
    if not REGISTRY_PATH.exists():
        return []
    try:
        with REGISTRY_PATH.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except (json.JSONDecodeError, OSError):
        return []
    return payload if isinstance(payload, list) else []


def save_custom_catalogues(items):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with REGISTRY_PATH.open("w", encoding="utf-8") as file:
        json.dump(items, file, indent=2)


def get_custom_catalogue(slug):
    normalized_slug = slugify(slug)
    return next(
        (item for item in load_custom_catalogues() if item.get("slug") == normalized_slug),
        None,
    )


def parse_room_shape(shape_name):
    if "_" not in shape_name:
        return None

    code, raw_name = shape_name.split("_", 1)
    code = code.strip().upper()
    if not code:
        return None

    room_name = raw_name.replace("_", " ").replace(" . ", " ").strip()
    room_name = " ".join(room_name.split())
    if not room_name:
        return None

    risk = RISK_BY_PREFIX.get(code[:1], "custom")
    return code, room_name, risk


def find_shape(slide, shape_name):
    return next((shape for shape in slide.shapes if shape.name == shape_name), None)


def find_largest_picture(slide):
    pictures = [
        shape
        for shape in slide.shapes
        if shape.shape_type == MSO_SHAPE_TYPE.PICTURE
    ]
    if not pictures:
        return None
    return max(pictures, key=lambda shape: shape.width * shape.height)


def crop_picture_image(picture):
    image = Image.open(BytesIO(picture.image.blob)).convert("RGBA")
    width, height = image.size
    box = (
        round(picture.crop_left * width),
        round(picture.crop_top * height),
        round((1 - picture.crop_right) * width),
        round((1 - picture.crop_bottom) * height),
    )
    return image.crop(box)


def export_floorplan(picture, output_path, target_width):
    image = crop_picture_image(picture)
    target_height = round(target_width * image.height / image.width)
    image = image.resize((target_width, target_height), Image.Resampling.LANCZOS)
    image = image.filter(ImageFilter.UnsharpMask(radius=1.2, percent=135, threshold=2))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, "PNG", optimize=True)
    return target_width, target_height


def shape_point_to_picture(point, path_width, path_height, shape, picture):
    local_x = int(point.get("x")) / path_width
    local_y = int(point.get("y")) / path_height
    slide_x = shape.left + local_x * shape.width
    slide_y = shape.top + local_y * shape.height
    return (
        rounded((slide_x - picture.left) / picture.width * 100),
        rounded((slide_y - picture.top) / picture.height * 100),
    )


def get_shape_rotation(shape):
    transform = shape.element.find(".//a:xfrm", namespaces=NS)
    return int(transform.get("rot") or 0) / 60000 if transform is not None else 0


def extract_rotated_rect_path(shape, picture):
    rotation = get_shape_rotation(shape)
    if rotation % 360 == 0:
        return None

    center_x = shape.left + shape.width / 2
    center_y = shape.top + shape.height / 2
    radians = math.radians(rotation)
    corners = []
    for local_x, local_y in (
        (-shape.width / 2, -shape.height / 2),
        (shape.width / 2, -shape.height / 2),
        (shape.width / 2, shape.height / 2),
        (-shape.width / 2, shape.height / 2),
    ):
        slide_x = center_x + local_x * math.cos(radians) - local_y * math.sin(radians)
        slide_y = center_y + local_x * math.sin(radians) + local_y * math.cos(radians)
        corners.append((
            rounded((slide_x - picture.left) / picture.width * 100),
            rounded((slide_y - picture.top) / picture.height * 100),
        ))

    return " ".join(
        [f"M {corners[0][0]} {corners[0][1]}"]
        + [f"L {x} {y}" for x, y in corners[1:]]
        + ["Z"]
    )


def extract_svg_path(shape, picture):
    path = shape.element.find(".//a:custGeom/a:pathLst/a:path", namespaces=NS)
    if path is None:
        return extract_rotated_rect_path(shape, picture)

    path_width = int(path.get("w") or shape.width)
    path_height = int(path.get("h") or shape.height)
    commands = []

    for command in path:
        tag = command.tag.rsplit("}", 1)[-1]
        points = command.findall("a:pt", namespaces=NS)
        coords = [
            shape_point_to_picture(point, path_width, path_height, shape, picture)
            for point in points
        ]

        if tag == "moveTo" and coords:
            commands.append(f"M {coords[0][0]} {coords[0][1]}")
        elif tag == "lnTo" and coords:
            commands.append(f"L {coords[0][0]} {coords[0][1]}")
        elif tag == "cubicBezTo" and len(coords) == 3:
            commands.append("C " + " ".join(f"{x} {y}" for x, y in coords))
        elif tag == "quadBezTo" and len(coords) == 2:
            commands.append("Q " + " ".join(f"{x} {y}" for x, y in coords))
        elif tag == "close":
            commands.append("Z")

    return " ".join(commands) or None


def resolve_color(container, default):
    if container is None or len(container) == 0:
        return default
    color = container[0]
    tag = color.tag.rsplit("}", 1)[-1]
    if tag == "srgbClr":
        return color.get("val") or default
    if tag == "schemeClr":
        return SCHEME_COLORS.get(color.get("val"), default)
    return default


def extract_style(shape, risk):
    shape_properties = shape.element.find("p:spPr", namespaces={
        **NS,
        "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    })
    solid_fill = shape_properties.find("a:solidFill", namespaces=NS) if shape_properties is not None else None
    line = shape_properties.find("a:ln", namespaces=NS) if shape_properties is not None else None
    line_fill = line.find("a:solidFill", namespaces=NS) if line is not None else None
    fill_color = resolve_color(solid_fill, DEFAULT_COLORS.get(risk, DEFAULT_COLORS["custom"]))
    stroke_color = resolve_color(line_fill, fill_color)
    color_node = solid_fill[0] if solid_fill is not None and len(solid_fill) else None
    alpha = color_node.find("a:alpha", namespaces=NS) if color_node is not None else None
    fill_opacity = int(alpha.get("val")) / 100000 if alpha is not None else 1
    line_width = int(line.get("w") or 12700) / 12700 if line is not None else 1
    return {
        "fillColor": f"#{fill_color}",
        "fillOpacity": rounded(fill_opacity),
        "strokeColor": f"#{stroke_color}",
        "strokeWidth": rounded(line_width),
    }


def extract_room(shape, picture):
    parsed = parse_room_shape(shape.name)
    if not parsed:
        return None

    code, room_name, risk = parsed
    return {
        "code": code,
        "name": room_name,
        "risk": risk,
        "interactive": True,
        "left": rounded((shape.left - picture.left) / picture.width * 100),
        "top": rounded((shape.top - picture.top) / picture.height * 100),
        "width": rounded(shape.width / picture.width * 100),
        "height": rounded(shape.height / picture.height * 100),
        "svgPath": extract_svg_path(shape, picture),
        **extract_style(shape, risk),
    }


def extract_rooms_from_slide(slide, picture):
    rooms = {}
    for shape in slide.shapes:
        if shape.shape_type not in {
            MSO_SHAPE_TYPE.AUTO_SHAPE,
            MSO_SHAPE_TYPE.FREEFORM,
        }:
            continue
        room = extract_room(shape, picture)
        if room:
            rooms[room["code"]] = room
    return dict(sorted(rooms.items()))


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
    for destination_match in re.finditer(
        rb"/(h\.[^\s\[]+)\s*\[(\d+)\s+0\s+R",
        object_body,
    ):
        destination_name = destination_match.group(1).decode("latin-1")
        page_object = int(destination_match.group(2))
        page_number = page_by_object.get(page_object)
        if page_number:
            named_destinations[destination_name] = page_number

    return named_destinations


def get_pdf_contents_link_pages(pdf_bytes):
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
        if (
            len(rect_values) >= 4
            and abs(rect_values[0] - 108) < 0.5
            and (rect_values[2] - rect_values[0]) > 250
            and page_number
        ):
            link_pages.append(page_number)

    return link_pages


def apply_pdf_pages_to_rooms(rooms, pdf_bytes):
    if not pdf_bytes:
        return rooms

    toc_pages = get_pdf_contents_link_pages(pdf_bytes)
    if len(toc_pages) < len(rooms):
        return rooms

    updated_rooms = {
        code: dict(room)
        for code, room in rooms.items()
    }
    for index, code in enumerate(sorted(updated_rooms)):
        updated_rooms[code]["page"] = toc_pages[index]
    return updated_rooms


def create_custom_catalogue(title, doc_url, pptx_path, pdf_bytes, options=None):
    options = options or {}
    slug = unique_slug(title)
    slide_number = int(options.get("slide_number") or 1)
    target_width = int(options.get("target_width") or 3600)
    picture_name = (options.get("picture_name") or "").strip()

    if slide_number < 1:
        raise ValueError("Slide number must be 1 or higher.")
    if target_width < 800 or target_width > 10000:
        raise ValueError("Target width must be between 800 and 10000 pixels.")

    presentation = Presentation(str(pptx_path))
    if slide_number > len(presentation.slides):
        raise ValueError(f"The PPT only has {len(presentation.slides)} slides.")

    slide = presentation.slides[slide_number - 1]
    picture = find_shape(slide, picture_name) if picture_name else find_largest_picture(slide)
    if picture is None or picture.shape_type != MSO_SHAPE_TYPE.PICTURE:
        raise ValueError("Could not find the map picture on that slide.")

    catalogue_dir = CUSTOM_STATIC_DIR / slug
    catalogue_dir.mkdir(parents=True, exist_ok=True)

    saved_pptx_path = UPLOAD_DIR / f"{slug}.pptx"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(pptx_path, saved_pptx_path)

    image_width, image_height = export_floorplan(picture, catalogue_dir / "layout.png", target_width)
    rooms = extract_rooms_from_slide(slide, picture)
    if not rooms:
        raise ValueError("No room shapes were found. Shape names should look like H-51_High Risk Cooking Area.")
    rooms = apply_pdf_pages_to_rooms(rooms, pdf_bytes)

    if pdf_bytes:
        with (catalogue_dir / "catalogue.pdf").open("wb") as file:
            file.write(pdf_bytes)

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    catalogue = {
        "slug": slug,
        "title": title.strip(),
        "doc_url": doc_url.strip(),
        "created_at": generated_at,
        "updated_at": generated_at,
        "source_pptx": str(saved_pptx_path.relative_to(BASE_DIR)).replace("\\", "/"),
        "slide_number": slide_number,
        "picture_name": picture.name,
        "room_count": len(rooms),
        "layout": {
            "image": f"/static/custom_catalogues/{slug}/layout.png",
            "pdf": f"/static/custom_catalogues/{slug}/catalogue.pdf" if pdf_bytes else "",
            "width": image_width,
            "height": image_height,
            "aspect": rounded(image_width / image_height),
        },
        "rooms": rooms,
    }

    with (catalogue_dir / "catalogue.json").open("w", encoding="utf-8") as file:
        json.dump(catalogue, file, indent=2)

    registry = [item for item in load_custom_catalogues() if item.get("slug") != slug]
    registry.append(catalogue)
    registry.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    save_custom_catalogues(registry)
    return catalogue
