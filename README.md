# Nutrislice → DAKboard sync (Pierremont Elementary lunch)

This repository fetches the weekly Nutrislice menu for Pierremont Elementary (Parkway Schools),
extracts the "top item" per day, and publishes two files:

- `dakboard_menu.json` — JSON list suitable for DAKboard custom JSON/text widget.
- `dakboard_menu.ics` — ICS file with all-day events (alternate option for DAKboard calendar).

Files are written to `public/` and automatically published to `gh-pages` via GitHub Actions.

## Quick start

1. Create a repository and paste these files:
   - `fetch_menu.py`
   - `requirements.txt`
   - `.github/workflows/update_menu.yml`
   - `README.md` (optional)

2. Commit and push to GitHub.

3. In Actions → ensure the workflow runs (you can manually trigger via **Run workflow**).

4. When the job completes, the files will be published to the `gh-pages` branch. The public URL will generally be:
