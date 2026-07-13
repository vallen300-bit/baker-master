---
title: DESIGN — Researcher tranche-3 item #10 PDF extraction
item: "#10 (researcher-capability-extension-brief @22ab300)"
status: DESIGN CLEARED — codex #9368 findings incorporated
---

## Contract

`scripts/pdf_extract.sh` is a read-only, offline wrapper around `pypdf`. It accepts one
PDF path and an optional inclusive page range. It emits exactly one JSON object on
stdout; diagnostics and dependency failures are represented as structured JSON errors.

## Security and resource bounds

- The file is opened once with `O_RDONLY|O_NOFOLLOW`; validation, hashing, and parsing
  use the held descriptor, never a second path open.
- Only regular files under the researcher or Baker research roots are accepted.
- Input is capped at 50 MiB, documents at 1,000 pages, and each call at 100 pages.
- Extracted UTF-8 text is capped at 2 MiB per response. Image-only pages are explicit
  in `image_only_pages` and produce a warning; OCR and network access are out of scope.
- Source identity is basename plus SHA-256 only; absolute paths never enter JSON output.

## Verification plan

The shell test covers argument validation, root containment, and a text-layer sample when
the optional local `pypdf` dependency is installed. The independent Codex build gate
must additionally probe descriptor swap resistance, page bounds, oversized input, and
JSON-only failure output.
