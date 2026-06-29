# Catalogue Standalone

Standalone Flask server for the SATS Stage 2 catalogue pages.

## What Is Included

- Interactive layout map at `/layout`
- Room catalogue viewer at `/catalogue/<room-code>`
- Catalogue management at `/catalogue/manage`
- Machine mapping and room name editing APIs
- Current low, medium, high, and office catalogue PDFs
- Local PDF.js assets, floor plan images, room shapes, and catalogue metadata

## Run Locally

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Open:

```text
http://127.0.0.1:5001
```

Set a different port with:

```powershell
$env:PORT = "5002"
python app.py
```

## Deploy On A Server

1. Clone this repository onto the server.
2. Install dependencies from `requirements.txt`.
3. Run `python app.py`, or run it behind your preferred WSGI/process manager.
4. Point the server route or reverse proxy to the app port.

The app listens on `0.0.0.0` and defaults to port `5001`.

## Important Files

- `app.py` - standalone Flask routes and catalogue APIs
- `frontend/` - catalogue HTML, shared navbar, static assets, PDF.js
- `frontend/static/catalogue/` - current catalogue PDFs and metadata
- `data/catalogue_page_map.json` - room-to-page catalogue map extracted from the original dashboard
- `data/catalogue_machine_capacity.json` - machine mapping data
- `layout_sources/Stage 2 PPT Layout.pptx` - source deck for regenerating layout overlays

## Updating Catalogues

Use `/catalogue/manage` to paste a Google Docs link for a risk area. The document must be shared so anyone with the link can view it. The app exports that Google Doc to PDF and replaces the matching `current_*_catalogue.pdf`.
