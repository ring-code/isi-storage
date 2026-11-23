# ISI Storage — Inventory, Rental & Fulfillment Backend

**ISI Storage** is a containerized, domain-driven Python/Flask backend and internal administration portal designed as the **single source of truth** for manufacturing blueprints, physical warehouse inventory, asset tracking, CRM, and order fulfillment (supporting both rentals and direct sales).

It is architected to run securely inside a private, firewalled internal network while synchronizing product catalogs and sales orders asynchronously with an external, public-facing WordPress/WooCommerce storefront. The WooCommerce integration is implemented through a separate, proprietary plugin developed by me for the original client. This plugin is not included in this repository and is not part of this open-source distribution.

This repository contains the Python backend and its associated components only.

---

## Table of Contents
1. [Core Architectural Principles](#core-architectural-principles)
2. [Technology Stack](#technology-stack)
3. [System Modules & Features](#system-modules--features)
   - [1. Definitions & Data Modeling (`definitions`)](#1-definitions--data-modeling-definitions)
   - [2. Product Blueprints & Specification Inheritance (`products`)](#2-product-blueprints--specification-inheritance-products)
   - [3. Physical Inventory, Spaces & Asset Tracking (`inventory`)](#3-physical-inventory-spaces--asset-tracking-inventory)
   - [4. Commercial Layer, CRM & Fulfillment (`sales`)](#4-commercial-layer-crm--fulfillment-sales)
   - [5. Authentication & Security (`auth`)](#5-authentication--security-auth)
4. [WooCommerce Integration (Push / Poll)](#woocommerce-integration-push--poll)
5. [Project Directory Structure](#project-directory-structure)
6. [Setup & Installation](#setup--installation)
7. [Database Migrations & Administration](#database-migrations--administration)

---

## Core Architectural Principles

* **Zero-Inbound Security Posture (Unidirectional Communication):** The `isi_storage` instance sits behind a closed firewall with **no open incoming ports to the public internet**. All external synchronization (pushing products to WooCommerce and polling for new orders) is strictly initiated **outbound** from the internal network over HTTPS and authenticated via a shared API key.
* **High Availability Separation:** Because the external WooCommerce storefront is decoupled from the internal storage backend, customers can browse and place orders even if the internal storage VM is temporarily offline or undergoing maintenance.
* **Domain-Driven Modularity:** The codebase is separated into cohesive Flask Blueprints (`auth`, `definitions`, `products`, `inventory`, `sales`), with neutral modules (`extensions.py`, `associations.py`, `utility/`) breaking circular dependencies.
* **Generic Integrity Protection:** Deletion of foundational records (such as `DataType` or `OptionList`) is protected via SQLAlchemy reflection (`is_model_instance_in_use`), preventing foreign-key crashes even as new models are linked in the future.
* **Secrets Management:** Sensitive credentials (database passwords, Flask secret keys, API keys, initial admin passwords) are never stored in plain `.env` files or source code; they are mounted as **Docker Secrets** under `/run/secrets/` and read via a dedicated `get_secret()` helper.

---

## Technology Stack

* **Backend Framework:** Python 3.11, Flask 3.x (Application Factory pattern), Gunicorn (WSGI server)
* **Database & ORM:** PostgreSQL 15 (using native `JSONB` for validation rules and damage metadata), SQLAlchemy 2.x, Flask-Migrate (Alembic)
* **Forms & Auth:** Flask-WTF / WTForms, Flask-Login, `email_validator`, `werkzeug.security` (`pbkdf2:sha256` hashing)
* **Background Scheduling:** `APScheduler` (`BlockingScheduler` running in a sidecar process via `entrypoint.sh`)
* **Frontend UI:** Jinja2, Bootstrap 4, Vanilla JavaScript (`Tablesort` for natural sorting, custom clickable rows, `QRCode.js` for rendering QR tags, `html5-qrcode` for live camera & image-based QR scanning)
* **Infrastructure:** Docker & Docker Compose

---

## System Modules & Features

### 1. Definitions & Data Modeling (`definitions`)
Provides the atomic, strongly typed building blocks used across the product catalog:
* **Data Types:** Defines primitive input types (`text`, `textarea`, `integer`, `float`, `boolean`, `color`, `date`, `range`, etc.) along with optional `JSONB` validation rules (e.g., `min`, `max`, `min_length`, `regex`).
These allow the connection of HTML input elements (e.g. text, number, color) to the data types, letting the user design a convenient and error-proof input method.
* **Option Lists:** Reusable, predefined lists of valid values (e.g., standard colors or sizes) strongly typed to a `DataType`, supporting single-choice (dropdown/radio) or multi-choice selection modes with min/max item rules.
* **Global Attributes:** System-wide property definitions linked to either a `DataType` or an `OptionList`. Each attribute defines its **WooCommerce Sync Behavior**:
  * `do_not_sync` (internal use only)
  * `sync_as_global` (informational / filtering attribute on WooCommerce)
  * `sync_as_variation` (variation-defining attribute such as Color or Size)

### 2. Product Blueprints & Specification Inheritance (`products`)
Separates abstract product definitions ("blueprints") from physical warehouse items:
* **Hierarchical Categories:** Unlimited parent/child category tree.
* **Specification Inheritance Engine:** Categories define `SpecificationDefinition` contracts that cascade down the tree with granular rule controls:
  * **Inheritable (`is_inheritable`):** Child categories automatically inherit the specification.
  * **Enforced (`requires_implementation`):** Products in this category tree *must* have a non-empty value before they are considered "Concrete".
  * **Final (`forbid_override`):** Locks a category-level default value so child categories and SKUs cannot alter it.
  * **Overrides & Hiding:** Child categories can hide non-enforced parent specs or apply `SpecificationRuleOverride` records to tighten rules downstream.
* **Chain of Command Resolution:** Effective specification values for any item are resolved bottom-up:  
  `Unit Override` $\rightarrow$ `Product SKU Override` $\rightarrow$ `Child Category Default` $\rightarrow$ `Parent Category Default`.
* **Concrete vs. Abstract SKUs:**
  * **Concrete SKUs** satisfy all category specifications and can be mass-produced via **Batch Unit Creation**.
  * **Abstract SKUs** leave one or more enforced specifications empty (e.g., a generic "Flat Cube" SKU whose color is only chosen per physical unit) and are fulfilled individually via **Single Unit Creation**.
* **Automated Attribute Sync Bridge (`sync_specs_to_attributes`):** Whenever a Product SKU is saved, resolved specifications linked to a global `Attribute` are automatically denormalized into `ProductAttribute` for fast querying and external syncing.

### 3. Physical Inventory, Spaces & Asset Tracking (`inventory`)
Tracks individual, serialized physical items in the warehouse:
* **Product Units:** Individual physical items linked to a parent `Product` SKU, featuring a unique `serial_number`, `actual_production_cost`, `condition` (`available`, `rented_out`, `in_maintenance`, `sold`, `decommissioned`), and a mutually exclusive commercial grade (`RentalGrade` or `SaleGrade`, enforced via SQL `CHECK` constraint).
* **Storage Spaces:** Physical warehouse locations (shelves, racks, zones). Includes a Space Management hub with live inventory previews (count + first 5 serial numbers) and a dedicated full-inventory view per space. Spaces containing units are protected against accidental deletion.
* **QR Code Asset Tags (`AssetTag`):**
  * Decoupled one-to-one lifecycle entity (`unassigned`, `active`, `decommissioned`) storing a unique UUID (`code_value`).
  * Managed directly from each unit's dashboard: generate new QR codes on the fly, open a print-ready label view (`print_tag.html`), or decommission damaged stickers and issue replacements while preserving historical auditability.
  * **QR Scanner (`scan_tag`):** Integrated `html5-qrcode` page allowing warehouse staff to scan tags via device camera (or image upload) to jump straight to that unit's dashboard.
* **Damage Tracking (`Damage` & `DamageTemplate`):** Supports both text-only damage logs (`text_list`, seeded automatically on install) and coordinate-based visual damage mapping (`x_coordinate`, `y_coordinate`, `dmg_metadata` JSONB) tied to a product's `DamageTemplate`.

### 4. Commercial Layer, CRM & Fulfillment (`sales`)
Bridges internal inventory with external storefront sales and internal order management:
* **Rental & Sale Grades:** Commercial pricing tiers defining `first_day_price`, `next_day_price` (or `sale_price`), `tax_rate`, UI swatch colors, `shipping_class_slug`, and eligible internal `Category` assignments.
* **Public Products & Variations (`PublicProduct`, `PublicVariation`):** Maps a commercial `Grade` to eligible internal `Product` SKUs. Each `PublicVariation` stores a deterministic, primary-key-based `isi_variation_id` (`BigInteger` hash) to guarantee stable synchronization with WooCommerce even if descriptive attributes change.
* **Shop Categories:** Public-facing hierarchical categories assigned directly to internal `Product` SKUs and aggregated automatically onto parent `PublicProduct` payloads during sync.
* **Customer CRM:** Dedicated database and UI for managing `Customer` profiles, multiple `Address` records (billing/shipping), and full per-customer order histories.
* **Order Lifecycle & Real-Time Availability Engine:**
  * Supports both internal order creation (`Draft` $\rightarrow$ `Pending Fulfillment` $\rightarrow$ `Fulfilled` / `Sale Completed`) and polled WooCommerce orders.
  * **Overbooking Prevention (`check_availability`):** Calculates real-time available stock for any date range by taking total `available` physical units and subtracting both **hard reservations** (units committed to overlapping `Booking` records) and **soft allocations** (quantities in `Pending Fulfillment` orders).
  * **Late-Binding Fulfillment:** Orders reserve capacity virtually upon confirmation; specific physical `ProductUnit`s (by serial number) are picked and bound to a `Booking` (for rentals) or marked `sold` (for sales) during warehouse fulfillment.

### 5. Authentication & Security (`auth`)
* **Role-Based Access Control (RBAC):** Three built-in roles (`admin`, `manager`, `user`) enforced via `@role_required` decorators.
* **Zero-Knowledge User Onboarding:** Administrators create new user accounts with a username, email, and role—without ever setting or seeing a password. The system generates a cryptographically secure, 7-day expiring, single-use token (stored hashed in the DB) and outputs a one-time setup URL for the new employee to set their own credentials.

---

## WooCommerce Integration (Push / Poll)

1. **Product Push (`src/app/sync_to_wp.py`):**
   * Can be triggered manually via CLI (`docker compose run --rm isi_storage python3 app/sync_to_wp.py`) or directly from the **WC Products** UI via a background `subprocess.Popen` trigger (automatically disabled in the UI if `WP_API_BASE_URL` is unconfigured).
   * Calls `/internal/sales/availability-summary` (`build_woocommerce_payload()`), which compiles `PublicProduct`s, hierarchical `ShopCategory` trees, `shipping_class` slugs, synced `Attribute`s, `PublicVariation` SKUs/hashes, stock totals, booking calendars, and pending order allocations, then `POST`s the JSON payload to WordPress (`/sync/update-availability`).
2. **Order Polling (`src/app/utility/polling_logic.py`):**
   * Executed every 60 seconds by `run_scheduler.py`.
   * If `WP_API_BASE_URL` is configured, polls WordPress (`/sync/get-new-orders`), creates/matches `Customer` and `Address` records, maps purchased `isi_variation_id` hashes back to internal `PublicVariation`s, generates `CustomerOrder` + `OrderItem` records in `Pending Fulfillment` status, and confirms ingestion back to WordPress (`/sync/confirm-orders`).

---

## Project Directory Structure

```text
isi_storage/
├── docker-compose.yml          # Orchestrates postgres_db and isi_storage containers
├── setup_env.py                # Interactive setup wizard generating .env and /secrets
├── .env                        # Non-secret environment configuration (gitignored)
├── secrets/                    # Docker secret files (gitignored)
│   ├── default_admin_password.txt
│   ├── isi_sync_api_key.txt
│   ├── postgres_password.txt
│   └── storage_secret_key.txt
└── src/
    ├── Dockerfile
    ├── entrypoint.sh           # Runs migrations/seeding, starts scheduler & Gunicorn
    ├── requirements.txt
    ├── config.py               # Reads env vars & Docker secrets via get_secret()
    ├── run.py                  # Flask WSGI entrypoint
    ├── run_scheduler.py        # APScheduler background polling worker
    ├── migrations/             # Alembic database migration scripts
    └── app/
        ├── __init__.py         # App factory (create_app) & Blueprint registration
        ├── extensions.py       # db, migrate, login_manager, csrf, get_secret()
        ├── associations.py     # Shared SQLAlchemy M2M association tables
        ├── commands.py         # CLI commands (`flask seed init`)
        ├── permissions.py      # @role_required RBAC decorator
        ├── sync_to_wp.py       # Standalone WooCommerce push script
        ├── auth/               # User, UserRights, login/logout, token onboarding
        ├── definitions/        # DataType, OptionList, Attribute, generic delete checks
        ├── inventory/          # AssetTag, Space, Damage, DamageTemplate, QR scanner
        ├── products/           # Product, Category, Specification*, ProductUnit
        ├── sales/              # Customer, Address, CustomerOrder, Booking, Grades, PublicProduct
        ├── utility/            # Domain logic (specs, sync, availability, pricing, polling)
        ├── static/             # CSS, JS (Tablesort, QRCode, html5-qrcode, form managers)
        └── templates/          # Bootstrap 4 Jinja2 templates organized by domain
```

---

## Setup & Installation

### Prerequisites
* Docker & Docker Compose
* Python 3 (on the host machine, solely to run the initial setup wizard)

### First-Time Setup

1. **Run the Interactive Setup Wizard:**
   From the project root (`isi_storage/`), run:
   ```bash
   python3 setup_env.py
   ```
   This prompts for:
   * Optional WordPress public domain (leaving blank disables sync/polling cleanly).
   * Default Admin email, username, and password.
   
   It automatically generates cryptographically secure secrets in `./secrets/` and writes `./.env`.

2. **Build and Start the Stack:**
   ```bash
   docker compose up -d --build
   ```
   On startup, `entrypoint.sh` automatically executes `flask seed init`, which:
   1. Applies all Alembic database migrations (`flask db upgrade`).
   2. Seeds default roles (`admin`, `manager`, `user`).
   3. Creates the initial admin user using the credentials in `.env` and `secrets/default_admin_password.txt`.
   4. Seeds the default `Standard Text-Only` (`text_list`) `DamageTemplate`.
   5. Starts `run_scheduler.py` in the background and launches Gunicorn on port `5050`.

3. **Access the Application:**
   Navigate to `http://<server-ip>:5050` (or `http://localhost:5050` locally; note that live camera QR scanning requires HTTPS or `localhost`).

---

## Database Migrations & Administration

* **Generate a new migration** after editing SQLAlchemy models:
  ```bash
  docker compose exec isi_storage flask db migrate -m "Description of schema change"
  ```
* **Apply pending migrations:**
  ```bash
  docker compose exec isi_storage flask db upgrade
  ```
* **Access the PostgreSQL CLI directly:**
  ```bash
  docker compose exec postgres_db psql -U isidb_user -d storage_db
  ```
  *(Note: When querying the users table in `psql`, always specify the schema: `SELECT * FROM public.user;` to avoid PostgreSQL's built-in `user` keyword).*


---

## Credits & Acknowledgements

### Original Project Foundation
* **Initial Prototype / Base System:** Built upon the foundational codebase and initial database/plugin concepts created by https://github.com/Brezel141. At least 90% are rewritten at this point, still: Thank you, Manuel.
### Open-Source Frontend Libraries
* **[Tablesort](https://github.com/tristen/tablesort)** by Tristen Brown — Lightweight client-side table sorting (MIT License).
* **[QRCode.js](https://github.com/davidshimjs/qrcodejs)** by davidshimjs — Client-side QR code rendering (MIT License).
* **[html5-qrcode](https://github.com/mebjas/html5-qrcode)** by minhazav — Cross-platform camera & file QR code scanning (Apache-2.0 License).
* **[Bootstrap 4](https://getbootstrap.com/)** & **jQuery** — UI layout and styling (MIT License).

### Backend Dependencies & Licensing
* Built with Python, Flask, SQLAlchemy, PostgreSQL, and APScheduler.
* Full license texts for all Python packages are documented in [`LICENSES.md`](./LICENSES.md) (generated via `pip-licenses`).
* This project is licensed under the **[GPL-3.0 License](./LICENSE)**