# Talki

A Flask-based social app project with templates, static assets, and SQLite database support.

## Requirements

- Python 3.12+ recommended
- `Flask==3.0.2`

## Setup

1. Open a terminal in the project root:
   ```powershell
   cd C:\Users\Admin\Desktop\Talki\Talki
   ```

2. Create and activate a virtual environment (if not already present):
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

3. Install dependencies:
   ```powershell
   pip install -r requirements.txt
   ```

## Run the app

From the project root with the virtual environment activated:

```powershell
python .\app.py
```

The Flask app starts in development mode by default and listens on:

- http://127.0.0.1:5000

## Notes

- The app uses `talki.db` in the project root for SQLite storage.
- Static files are served from the `static/` folder and templates from `templates/`.
- If you need a different host or port, update the `app.run(...)` call in `app.py`.
