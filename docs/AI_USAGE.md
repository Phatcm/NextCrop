# Use of Super Intelligence (SI) / AI tools

Declaration for NASA Space Apps Challenge 2026. Team NextCrop used one AI tool:

**Claude Code (Anthropic, Claude models)**, as a coding and writing assistant throughout the challenge.

| Area | What the AI did | Where |
|---|---|---|
| Code and data | Wrote and refactored code and tests: data pipeline and quality checks, rotation-option generator, read-only API, web interface (map, charts, English/Vietnamese switch, NASA tab, moisture-check badges), CI workflows | `pipeline/`, `app/api/`, `app/web/`, `.github/` |
| Images | Drew the NextCrop logo mark as an SVG. It is AI-generated and marked as such here and in the submission | `app/web/favicon.svg` and the header logo in `app/web/index.html` |
| Text | Drafted documentation, interface text, English translations and submission wording | `docs/`, `README.md`, `app/web/js/i18n.js`, `pipeline/src/rotation/options.py` |
| Audio | Not used | |

**What people decided:** the challenge and the product idea, which data sources to use, thresholds and rules (for example the minimum suitability of 4000 and the rest days between crops, each with its source in `docs/rotation-rules.md`), and whether to accept each result. Data checks were run against the real data (cross-checks between sources, a regression of 41,293 generator runs proving the English text did not change the Vietnamese output), and automated tests run on every pull request (CI).

**Limits of this declaration:** English text has not been reviewed by a native speaker. The AI produced no NASA branding, flags or mission identifiers.

Version history of the work is in the git log of this repository.
