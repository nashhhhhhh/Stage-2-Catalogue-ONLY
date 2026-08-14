# Stage 2 Catalogue Explorer

Standalone Flask application for browsing the SATS Stage 2 floor plans, room
overlays, and equipment catalogue PDFs.

## What Is Included

- Interactive layout map at `/layout`
- Room catalogue viewer at `/catalogue/<room-code>`
- Catalogue management at `/catalogue/manage`
- Custom catalogue creation from one- or multi-slide PowerPoint maps
- Machine mapping and room name editing APIs
- Current low, medium, high, and office catalogue PDFs
- Local PDF.js assets, floor plan images, room shapes, and catalogue metadata

## Clone And Run

The catalogue PDFs are stored with [Git LFS](https://git-lfs.com/) because some
of them are larger than GitHub's normal file-size limit. Install Git LFS before
cloning, then run:

```powershell
git lfs install
git clone https://github.com/nashhhhhhh/Stage-2-Catalogue-ONLY.git
Set-Location Stage-2-Catalogue-ONLY
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
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

## Run The Tests

```powershell
python -m unittest discover -s tests -v
```

## Important Files

- `app.py` - standalone Flask routes and catalogue APIs
- `frontend/` - catalogue HTML, shared navbar, static assets, PDF.js
- `frontend/static/catalogue/` - current catalogue PDFs and metadata
- `frontend/static/custom_catalogues/` - generated custom PDFs, map images,
  and extracted room/layout JSON
- `data/catalogue_page_map.json` - room-to-page catalogue map extracted from the original dashboard
- `data/catalogue_machine_capacity.json` - machine mapping data
- `data/custom_catalogues.json` - custom catalogue registry and Google Docs links
- `data/custom_catalogue_uploads/` - saved source PowerPoint files for custom catalogues
- `layout_sources/Stage 2 PPT Layout.pptx` - source deck for regenerating layout overlays

Downloaded Google Docs PDFs are not placed in the user's Downloads folder.
Built-in catalogue PDFs are saved under `frontend/static/catalogue/`; custom
catalogue PDFs are saved under `frontend/static/custom_catalogues/<slug>/`.

## Updating Catalogues

Use `/catalogue/manage` to paste a Google Docs link for a risk area. The document must be shared so anyone with the link can view it. The app exports that Google Doc to PDF and replaces the matching `current_*_catalogue.pdf`.

Use `/catalogue/manage/create` to create a custom catalogue from a Google Docs
link and a `.pptx` map. Every slide is imported, picture tiles are assembled in
their original positions, and room shapes retain their PowerPoint orientation
and theme colour.
