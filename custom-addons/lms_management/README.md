# Airport Lounge Management Backend (LMS)

This Odoo 18 module implements the backend for an airport Lounge Access Management System (LAMS). It exposes REST endpoints for a Flutter front-end and provides full back-office models and views.

## Highlights
- Airlines, FFP Programs & Tiers, Aggregators, Corporate memberships
- Pre-bookings / vouchers
- Lounge Visit (Order) records with passenger lines
- Supervisor Overrides
- Simple REST API (API key via `System Parameters` key: `lms.api_key`)

## REST Endpoints
- POST `/lms/api/scan_bcbp` — parse BCBP string (demo)
- POST `/lms/api/visit/create` — create visit with passengers
- GET `/lms/api/visit/<id>` — retrieve visit
- POST `/lms/api/search` — quick search recent visits

## Install
1. Zip this folder and upload to Odoo addons path.
2. Activate developer mode, update apps list, install.
3. Set `lms.api_key` in Settings → Technical → Parameters → System Parameters.
