# Graph Report - whatsapp-ai-responder  (2026-07-30)

## Corpus Check
- 288 files · ~678,338 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 3682 nodes · 5363 edges · 240 communities (203 shown, 37 thin omitted)
- Extraction: 98% EXTRACTED · 2% INFERRED · 0% AMBIGUOUS · INFERRED: 132 edges (avg confidence: 0.65)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `42780b0c`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- app.js
- BookingService
- gray
- main.py
- InboundProcessor
- Tailwind CSS Utility Reference
- CoreRepository
- 6. Piano di implementazione
- slide_search_core.py
- models/schemas.py
- Repository
- Brand Guidelines v1.0
- Design
- Canvas Design System
- WhatsApp Business Cloud API Integration — Design Doc
- Prerequisites
- Form & Input Components
- Tailwind CSS Responsive Design
- design_system.py
- AppConfig
- Typography Specifications
- models.py
- Logo Usage Rules
- Component Specifications
- shadcn/ui Accessibility Patterns
- TestTailwindConfigGenerator
- BM25
- html-token-validator.py
- P3 — Operazioni, scalabilità, go-to-market
- MetaClient
- Asset Approval Checklist
- Logo AI Prompt Engineering
- _headers
- Multi-tenant Persistence Schema — Design Doc
- Color Palette Management
- CIP Deliverable Guide
- BM25
- States and Variants
- UI Styling Skill
- handle_stripe_webhook
- Workflow
- BM25
- Design System
- Tailwind CSS Customization
- onboarding.py
- WhatsAppService
- time
- Auth & Authorization — Design
- spacing
- DesignSystemGenerator
- Piano
- inbox/routes.py
- test_repository.py
- Fase 1 — Wiring AI → prenotazione reale
- gdpr/routes.py
- Routing by Task Type
- generate-slide.py
- shadcn/ui Theming & Customization
- TailwindConfigGenerator
- TestTicketRepository
- Billing & Stripe Integration — Design Document
- Asset Organization Guide
- Primary Color Meanings
- Core Logo Types
- color
- report_agent.py
- require_mfa
- TestInboxAPI
- TestRouter
- vector_store.py
- Brand Consistency Checklist
- CIP Mockup Prompt Engineering
- Color Semantics
- fetch-background.py
- TestShadcnInstaller
- test_dependencies.py
- scheduler.py
- Cosa può fare
- billing/routes.py
- email_service.py
- WhatsApp Business Cloud API Integration — Implementation Plan
- Struttura pagina (sezioni in ordine di scroll)
- review_agent.py
- Design Principles
- Design Principles
- icon/generate.py
- fontSize
- .add_components
- get
- GoogleCalendarService
- RetryWorker
- CIP Design Reference
- Icon Design Reference
- Copywriting Formulas
- Copywriting Formulas
- main
- search
- RecensioneInput
- Banner Design - Multi-Format Creative Banner System
- Messaging Framework
- Brand Voice Framework
- extract-colors.cjs
- validate-asset.cjs
- Layout Patterns
- cip/generate.py
- Tailwind Integration
- radius
- Layout Patterns
- ShadcnInstaller
- apply_status_update
- calendar/routes.py
- test_logging_filter.py
- File Structure
- update.md
- Logo Design Reference
- Token Architecture
- primitive
- Review: Robustezza Payload Meta e Webhook Status (Task 7)
- webhook_handler.py
- test_propagation.py
- test_gdpr_fk.py
- test_retention.py
- Global Constraints
- Global Constraints
- Primitive Tokens
- validate-tokens.cjs
- button
- test_tailwind_config_gen.py
- .generate_config_string
- Files modificati
- TemplateSyncer
- whatsapp/conftest.py
- Global Constraints
- Global Constraints
- Global Constraints
- Global Constraints
- Architecture — 6 Modules
- Core Visual Elements
- inject-brand-context.cjs
- CIP Design Style Guide
- embed-tokens.cjs
- patch
- Problemi riscontrati e correzioni
- email_config_store.py
- test_reminder_job.py
- router.py
- Brand
- Slide Strategies
- UUID
- Component Tokens
- generate-tokens.cjs
- TestVerifySupabaseJwtIssuer
- duration
- Slide Strategies
- ._base_config
- Riassunto modifiche
- Soluzione
- sm
- primary
- billing/test_routes.py
- test_deposito.py
- inviaMessaggio
- inizializzaOnboarding
- _run
- sync-brand-to-tokens.cjs
- core/conftest.py
- Upgrade Landing "Sempre" — Piano completo
- render-html.py
- test_shadcn_add.py
- TestJwtIssuerRejectionEndToEnd
- dependencies.py
- Slides Reference
- HTML Slide Template
- HTML Slide Template
- detect_domain
- .test_init_custom_project_root
- .test_add_components_no_components
- Slides
- ConversationStore
- TestHITLMigration
- test_repository_documents.py
- test_repository_email_configs.py
- aggiornaPrenotazioni
- Brand Guidelines Template
- Migration Scripts
- get_token
- require_ruolo
- aggiornaNotifiche
- opencode.json
- core/__init__.py
- test_repository_booking_settings.py
- test_repository_reviews.py
- test_repository_usage.py
- test_triggers_event_log.py
- Checklist pre-lancio — whatsapp-ai-responder
- graphify.js
- test_sync_brand_to_tokens.py
- main
- primary-foreground
- .__init__
- .temp_project
- run_reindex
- email_sources/base.py
- test_schema_creates_all_tables
- AGENTS.md
- CLAUDE.md
- slides-create.md
- create.md
- .test_add_components_already_installed
- .test_add_fonts
- .test_recommend_plugins
- .test_generate_typescript_config
- .test_generate_config_with_plugins
- .test_init_javascript
- .test_write_config_creates_content
- .test_write_config_invalid_path
- .test_default_output_path_typescript
- .test_default_content_paths_vue
- .test_add_colors
- aggiornaConteggio

## God Nodes (most connected - your core abstractions)
1. `Repository` - 83 edges
2. `CoreRepository` - 67 edges
3. `TailwindConfigGenerator` - 58 edges
4. `GoogleCalendarService` - 39 edges
5. `WhatsAppService` - 37 edges
6. `TestTailwindConfigGenerator` - 35 edges
7. `ShadcnInstaller` - 34 edges
8. `BookingService` - 33 edges
9. `AppConfig` - 33 edges
10. `TestShadcnInstaller` - 26 edges

## Surprising Connections (you probably didn't know these)
- `TestIngoingWebhook` --uses--> `OutboundTextPayload`  [INFERRED]
  tests/whatsapp/test_models.py → src/whatsapp/models.py
- `TestIngoingWebhook` --uses--> `SendTextRequest`  [INFERRED]
  tests/whatsapp/test_models.py → src/whatsapp/models.py
- `TestMetaClient` --uses--> `SendResponse`  [INFERRED]
  tests/whatsapp/test_client.py → src/whatsapp/models.py
- `main()` --calls--> `BookingService`  [EXTRACTED]
  run_inbound_processor.py → src/core/bookings/service.py
- `main()` --calls--> `CoreRepository`  [EXTRACTED]
  run_inbound_processor.py → src/core/db/repository.py

## Import Cycles
- None detected.

## Communities (240 total, 37 thin omitted)

### Community 0 - "app.js"
Cohesion: 0.02
Nodes (78): availabilityDate, availabilityList, bookingCalendarEl, bookingCount, bookingDayLabel, bookingDayList, bookingDetail, bookingForm (+70 more)

### Community 1 - "BookingService"
Cohesion: 0.06
Nodes (30): cancel_booking(), confirm_booking(), create_booking(), get_booking(), _get_booking_service(), get_settings(), list_bookings(), mark_completed() (+22 more)

### Community 2 - "gray"
Cohesion: 0.05
Nodes (53): $type, $value, $type, $value, $type, $value, $type, $value (+45 more)

### Community 3 - "main.py"
Cohesion: 0.12
Nodes (38): callable, carica_documento(), carica_file_documento(), chiedi_documenti(), crea_prenotazione(), indicizza_documenti(), onboarding_preview(), ottieni_impostazioni_prenotazioni() (+30 more)

### Community 4 - "InboundProcessor"
Cohesion: 0.07
Nodes (31): enqueue_escalation(), security_audit(), InboundProcessor, contact(), org_id(), asyncio, fixture, test_consent_status_deleted_contact_returns_none() (+23 more)

### Community 5 - "Tailwind CSS Utility Reference"
Cohesion: 0.05
Nodes (43): Arbitrary Values, Aspect Ratio, Background Colors, Border Color, Border Radius, Border Style, Border Width, Borders (+35 more)

### Community 6 - "CoreRepository"
Cohesion: 0.06
Nodes (4): CoreRepository, datetime, UUID, Like process_stripe_event but uses an existing connection/transaction so the…

### Community 7 - "6. Piano di implementazione"
Cohesion: 0.05
Nodes (41): 0.1 Cosa esiste già, 0.2 Bug strutturale da risolvere, 0.3 Punto 2 (multi-tenancy + DB) completato, 0.4 Fix migrazione Airtable: mapping stati, 0.5 Limite noto: isolamento app-level, non RLS, 0. Stato attuale, 1.1 Nuove colonne su `bookings`, 1.2 Stati `bookings.stato` estesi (+33 more)

### Community 8 - "slide_search_core.py"
Cohesion: 0.09
Nodes (36): format_context(), format_result(), main(), Format a single search result for display, Format contextual recommendations for display., BM25, calculate_pattern_break(), detect_domain() (+28 more)

### Community 9 - "models/schemas.py"
Cohesion: 0.10
Nodes (35): Enum, costruisci_system_prompt(), costruisci_user_prompt(), formatta_cronologia(), prompts.py ---------- Qui costruiamo il testo che l'agente riceve come…, Trasforma gli ultimi N scambi in testo per il prompt., Genera le istruzioni di ruolo per l'agente, basate sul profilo dell'attività…, Il messaggio del cliente così com'è, con la data odierna per risolvere date… (+27 more)

### Community 10 - "Repository"
Cohesion: 0.05
Nodes (5): main(), Atomically marks a message as replied+handled. Returns the updated row if this…, Periodic heartbeat — tells the reaper this claim is still alive., Libera i claim rimasti bloccati oltre timeout_minutes. Per i messaggi usa…, Repository

### Community 11 - "Brand Guidelines v1.0"
Cohesion: 0.05
Nodes (37): 1. Color Palette, 2. Typography, 3. Logo Usage, 4. Voice & Tone, 5. Imagery Guidelines, 6. Design Components, Accessibility, AI Image Generation (+29 more)

### Community 12 - "Design"
Cohesion: 0.06
Nodes (35): Banner Design (Built-in), Banner: Design Rules, Banner: Quick Size Reference, Banner: Top Art Styles, Banner: Workflow, CIP Design (Built-in), CIP: Generate Brief, CIP: Generate Mockups (+27 more)

### Community 13 - "Canvas Design System"
Cohesion: 0.06
Nodes (35): 1. Visual Communication First, 2. Minimal Text Integration, 3. Expert Craftsmanship, 4. Systematic Patterns, Analog Meditation, Approach, Canvas Boundaries, Canvas Design System (+27 more)

### Community 14 - "WhatsApp Business Cloud API Integration — Design Doc"
Cohesion: 0.06
Nodes (34): 1.1 Struttura moduli, 1.2 Stack, 1.3 Multi-tenancy, 1. Architettura generale, 2.1 GET /webhooks/whatsapp — Verifica iniziale Meta, 2.2 POST /webhooks/whatsapp — Ricezione eventi, 2.3 HMAC verificato prima di tutto, 2. Webhook endpoint (+26 more)

### Community 15 - "Prerequisites"
Cohesion: 0.06
Nodes (33): Accessibility, Available Domains, Available Stacks, Common Rules for Professional UI, Common Sticking Points, Example Workflow, How to Use This Skill, Icons & Visual Elements (+25 more)

### Community 16 - "Form & Input Components"
Cohesion: 0.06
Nodes (32): Accordion, Alert, Alert Dialog, Avatar, Badge, Button, Card, Checkbox (+24 more)

### Community 17 - "Tailwind CSS Responsive Design"
Cohesion: 0.06
Nodes (32): 1. Mobile-First Design, 2. Consistent Breakpoint Usage, 3. Test at Breakpoint Boundaries, 4. Use Container for Content Width, 5. Progressive Enhancement, 6. Avoid Too Many Breakpoints, Best Practices, Breakpoint System (+24 more)

### Community 18 - "design_system.py"
Cohesion: 0.12
Nodes (22): ansi_ljust(), _detect_page_type(), format_ascii_box(), format_markdown(), format_master_md(), format_page_override_md(), _generate_intelligent_overrides(), hex_to_ansi() (+14 more)

### Community 19 - "AppConfig"
Cohesion: 0.13
Nodes (24): main(), main(), AppConfig, load_tenant_config(), UUID, TenantConfig, app_config(), fake_tenant_config() (+16 more)

### Community 20 - "Typography Specifications"
Cohesion: 0.06
Nodes (30): Accessibility, Base System, Best Practices, Clean & Modern, Common Font Pairings, Contrast Requirements, CSS Implementation, Editorial (+22 more)

### Community 21 - "models.py"
Cohesion: 0.13
Nodes (22): retry, ButtonReply, ChangeEntry, ChangeValue, ContactEntry, ContactResponse, ContextEntry, Entry (+14 more)

### Community 22 - "Logo Usage Rules"
Cohesion: 0.07
Nodes (28): Absolute Don'ts, Approved Backgrounds, Before Using Logo, Clear Space, Co-branding, Color Rules, Color Usage, Color Variants (+20 more)

### Community 23 - "Component Specifications"
Cohesion: 0.07
Nodes (28): Alert, Anatomy, Anatomy, Anatomy, Anatomy, Anatomy, Badge, Button (+20 more)

### Community 24 - "shadcn/ui Accessibility Patterns"
Cohesion: 0.07
Nodes (28): Accordion, Alert, ARIA Labels, Checkbox and Radio, Color Contrast, Command Palette Navigation, Component-Specific Patterns, Dialog/Modal Navigation (+20 more)

### Community 25 - "TestTailwindConfigGenerator"
Cohesion: 0.07
Nodes (15): Test adding colors multiple times., Test adding full color palette., Test adding custom breakpoints., Test TailwindConfigGenerator class., Test that adding same plugin twice doesn't duplicate., Test plugin recommendations for Next.js., Test initialization with default settings., Test generating JavaScript configuration. (+7 more)

### Community 26 - "BM25"
Cohesion: 0.12
Nodes (22): BM25, detect_domain(), get_cip_brief(), _load_csv(), Load CSV and return list of dicts, Core search function using BM25, Auto-detect the most relevant domain from query, Main search function with auto-domain detection (+14 more)

### Community 27 - "html-token-validator.py"
Cohesion: 0.14
Nodes (24): get_context(), is_allowed_exception(), is_allowed_rgba(), is_inside_block(), load_css_variables(), main(), print_result(), print_summary() (+16 more)

### Community 28 - "P3 — Operazioni, scalabilità, go-to-market"
Cohesion: 0.07
Nodes (27): 10. Canali aggiuntivi (Instagram, Messenger, Widget, Email), 11. RAG integrato nelle risposte cliente, 12. Guardrails e qualità risposta, 13. Model routing intelligente, 14. Multilingua, 15. Infrastruttura production-ready, 16. Fix debito tecnico immediato, 17. Analytics e report vendibili (+19 more)

### Community 29 - "MetaClient"
Cohesion: 0.19
Nodes (12): Exception, MetaClient, OutboundTextPayload, SendTextRequest, MessageBlockedByOptOut, MessageUsageExceeded, UUID, fixture (+4 more)

### Community 30 - "Asset Approval Checklist"
Cohesion: 0.08
Nodes (25): Accessibility, Archival, Asset Approval Checklist, Automation Support, Color Compliance, Common Issues & Fixes, Content Accessibility, Content Quality (+17 more)

### Community 31 - "Logo AI Prompt Engineering"
Cohesion: 0.08
Nodes (25): Common Pitfalls, Core Prompt Structure, Detailed Brief, Eco/Sustainable, Effective Keywords by Style, Fashion Brand, Healthcare, Industry-Specific Prompts (+17 more)

### Community 32 - "_headers"
Cohesion: 0.11
Nodes (8): async_client(), _headers(), org_id(), fixture, set_env(), TestConsentPrefs, TestDataRights, TestDPA

### Community 33 - "Multi-tenant Persistence Schema — Design Doc"
Cohesion: 0.08
Nodes (24): 1.1 Sorgenti da sostituire, 1.2 Cosa NON cambia, 1. Obiettivo, 2.1 Convenzioni comuni, 2.2 DDL completo, 2.3 Trigger di popolamento event_log (esempi), 2. Schema PostgreSQL, 3.1 Isolamento a livello query (+16 more)

### Community 34 - "Color Palette Management"
Cohesion: 0.08
Nodes (24): Accessibility Requirements, Brand Compliance Validation, Checking Contrast, Color Documentation Format, Color Extraction, Color Palette Examples, Color Palette Management, Color System Structure (+16 more)

### Community 35 - "CIP Deliverable Guide"
Cohesion: 0.08
Nodes (24): Apparel, Business Card, Car/Sedan, CIP Deliverable Guide, Core Identity, Digital Assets, Email Signature, Envelope (+16 more)

### Community 36 - "BM25"
Cohesion: 0.12
Nodes (19): BM25, detect_domain(), _load_csv(), Load CSV and return list of dicts, Core search function using BM25, Auto-detect the most relevant domain from query, Main search function with auto-domain detection, Search across all domains and combine results (+11 more)

### Community 37 - "States and Variants"
Cohesion: 0.08
Nodes (24): Accessibility, Accessibility Requirements, ARIA States, Color Contrast, Color Variants, Disabled States, Error Messages, Error States (+16 more)

### Community 38 - "UI Styling Skill"
Cohesion: 0.08
Nodes (24): Accessibility Patterns, Alternative: Tailwind-Only Setup, Best Practices, Common Patterns, Component Layer: shadcn/ui, Component Library Guide, Component + Styling Setup, Core Stack (+16 more)

### Community 39 - "handle_stripe_webhook"
Cohesion: 0.13
Nodes (23): handle_stripe_webhook(), Tutto il processing avviene in un'unica transazione DB: dedup INSERT e effetti…, Subscription mode logic is not touched., test_webhook_payment_mode_updates_booking(), test_webhook_subscription_mode_unaffected(), fixture, Fix C: subscription.updated con lo stesso current_period_start (es. cambio…, Fix B: due eventi DIVERSI (evt id diversi) che referenziano lo stesso oggetto… (+15 more)

### Community 40 - "Workflow"
Cohesion: 0.08
Nodes (23): Art Direction Styles (Reuse from Banner), Color & Contrast, Design Best Practices, HTML Design Rules, HTML Template Structure, Option A: Chrome Headless CLI (Recommended — zero dependencies), Option B: chrome-devtools skill, Option C: Playwright script (+15 more)

### Community 41 - "BM25"
Cohesion: 0.13
Nodes (16): BM25, _domain_keywords(), _get_bm25(), _load_csv(), _load_product_keywords(), _normalize(), Apply synonym substitution before tokenizing., BM25 ranking algorithm for text search (+8 more)

### Community 42 - "Design System"
Cohesion: 0.09
Nodes (22): Best Practices, Chart.js Integration, Command, Component Spec Pattern, Contextual Decision Flow, Decision System CSVs, Design System, Integration (+14 more)

### Community 43 - "Tailwind CSS Customization"
Cohesion: 0.09
Nodes (22): @apply Directive, Best Practices, Color Customization, Complete Tailwind Config, Configuration Examples, Content Configuration, Custom Color Palette, Custom Font Sizes (+14 more)

### Community 44 - "onboarding.py"
Cohesion: 0.20
Nodes (19): onboarding_profilo(), onboarding_salva_profilo(), onboarding_verticali(), build_business_profile(), _ensure_store_dir(), get_active_profile(), get_active_profile_record(), list_verticals() (+11 more)

### Community 45 - "WhatsAppService"
Cohesion: 0.15
Nodes (5): _normalize_text(), WhatsAppService, Task 6: se l'idempotency_key esiste gia', non si tenta un secondo invio (niente…, Race genuina: il pre-check non trova nulla, ma upsert_message ritorna una riga…, TestWhatsAppService

### Community 46 - "time"
Cohesion: 0.06
Nodes (36): date, enhance_prompt(), generate_batch(), generate_logo(), load_env(), main(), Enhance the logo prompt with style and industry modifiers, Generate a logo using Gemini models with image generation Args: aspect_ratio:… (+28 more)

### Community 47 - "Auth & Authorization — Design"
Cohesion: 0.09
Nodes (21): 1. Schema DB — Nuove tabelle, 2. Auth Flow — Dependency Injection (FastAPI), 3. API Key Server-to-Server, 4. Rate Limiting — Per tenant (in-memory), 5. CORS, 6. Audit Log, Applicazione, Auth & Authorization — Design (+13 more)

### Community 48 - "spacing"
Cohesion: 0.06
Nodes (34): $type, $value, $type, $value, $type, $value, $type, $value (+26 more)

### Community 49 - "DesignSystemGenerator"
Cohesion: 0.11
Nodes (15): DesignSystemGenerator, generate_design_system(), Find matching reasoning rule for a category., Apply reasoning rules to search results., Select best matching result based on priority keywords., Extract results list from search result dict., Generate complete design system recommendation. variance/motion/density are…, Main entry point for design system generation. Args: query: Search query (e.g.,… (+7 more)

### Community 50 - "Piano"
Cohesion: 0.09
Nodes (21): 1. Idempotenza webhook Meta, 2. GDPR / FK Cascade, 3. Atomicità messaggio + usage, 4. Trial length centralizzato, 5. Timezone reminders, 6. Business profile validation, 7. Async queue escalation email, Files modificati / creati (+13 more)

### Community 51 - "inbox/routes.py"
Cohesion: 0.28
Nodes (19): claim_ticket(), _get_app_config(), get_ticket(), _get_wrepo(), list_tickets(), get, post, Request (+11 more)

### Community 52 - "test_repository.py"
Cohesion: 0.19
Nodes (20): asyncio, test_claim_inbound_messages_no_double_claim(), test_claim_inbound_messages_skip_locked(), test_encryption_key_rotation_handles_invalid_token(), test_get_contact_prefs(), test_get_or_create_contact_existing(), test_get_or_create_contact_new(), test_get_or_create_conversation() (+12 more)

### Community 53 - "Fase 1 — Wiring AI → prenotazione reale"
Cohesion: 0.10
Nodes (19): 0.1 — Mutable default in reject_booking, 0.2 — POSTGRES_DSN → DATABASE_URL, 0.3 — Idempotenza migration script, 0.4 — Worktree abbandonato rimosso, 1.1 — BookingService init in lifespan (bug fix), 1.2 — AI booking creation in inbound_processor, 1.3 — SlotPienoError con alternative, 1.4 — Cleanup prenotazioni.py (+11 more)

### Community 54 - "gdpr/routes.py"
Cohesion: 0.18
Nodes (18): field_validator, ConsentPrefsInput, ConsentPrefsOutput, _export_tenant_data(), gdpr_delete(), gdpr_download(), gdpr_export(), _generate_export_token() (+10 more)

### Community 55 - "Routing by Task Type"
Cohesion: 0.10
Nodes (19): Banner Design Tasks, Brand Identity Tasks, Component Creation, Corporate Identity Program Tasks, Design Routing Guide, Design System Migration, Icon Design Tasks, Implementation Tasks (+11 more)

### Community 56 - "generate-slide.py"
Cohesion: 0.15
Nodes (19): _e(), generate_chart_slide(), generate_cta_slide(), generate_deck(), generate_metrics_slide(), generate_problem_slide(), generate_solution_slide(), generate_testimonial_slide() (+11 more)

### Community 57 - "shadcn/ui Theming & Customization"
Cohesion: 0.10
Nodes (19): Base Color Presets, Best Practices, Color Customization, Color Format, Component Customization, CSS Variable System, Customize Styles, Customize Variants (+11 more)

### Community 58 - "TailwindConfigGenerator"
Cohesion: 0.10
Nodes (11): Generate Tailwind CSS configuration files., Add full color palette (50-950 shades) for a base color. Args: name: Color name…, TailwindConfigGenerator, Test adding custom spacing., Test validating config with no content paths., Test validating config with empty theme extensions., Test writing configuration to file., Test initialization with different frameworks. (+3 more)

### Community 59 - "TestTicketRepository"
Cohesion: 0.15
Nodes (6): extended_pool(), fixture, repo(), reset_db(), reset_extended_db(), TestTicketRepository

### Community 60 - "Billing & Stripe Integration — Design Document"
Cohesion: 0.11
Nodes (18): Architettura, Billing & Stripe Integration — Design Document, Counting messaggi, Env, `GET /api/billing/subscription`, `GET /api/billing/usage`, Middleware limiti, Non in scope (+10 more)

### Community 61 - "Asset Organization Guide"
Cohesion: 0.11
Nodes (18): Asset Entry (manifest.json), Asset Organization Guide, By Campaign, By Status, By Type, Cleanup Workflow, Components, Directory Structure (+10 more)

### Community 62 - "Primary Color Meanings"
Cohesion: 0.11
Nodes (18): Accessibility Considerations, Analogous, Black, Blue, Color Combinations by Industry, Color Harmony Types, Complementary, Green (+10 more)

### Community 63 - "Core Logo Types"
Cohesion: 0.11
Nodes (18): 1. Wordmark (Logotype), 2. Lettermark (Monogram), 3. Pictorial Mark (Brand Mark), 4. Abstract Mark, 5. Mascot, 6. Emblem, 7. Combination Mark, Aesthetic Styles (+10 more)

### Community 64 - "color"
Cohesion: 0.06
Nodes (31): $type, $value, background, destructive, destructive-foreground, foreground, muted, muted-foreground (+23 more)

### Community 65 - "report_agent.py"
Cohesion: 0.26
Nodes (15): costruisci_system_prompt_report(), costruisci_user_prompt_report(), crea_report_agent(), crea_report_crew(), crea_report_task(), Agent, Crew, Task (+7 more)

### Community 66 - "require_mfa"
Cohesion: 0.15
Nodes (10): Dipendenza da combinare DOPO require_ruolo sui Tier-1. Esempio: user =…, require_mfa(), _build_test_app_real(), FastAPI, Audit 1.4 — AAL2 (MFA) step-up gate sui Tier-1 sensibili. Cosa si testa qui: 1.…, Test end-to-end con TestClient: un utente senza MFA che chiama /api/gdpr/export…, App minimale che monta /api/gdpr/export protetto da require_mfa(), per testare…, TestMfaGateOnRoute (+2 more)

### Community 67 - "TestInboxAPI"
Cohesion: 0.20
Nodes (6): async_client(), fixture, Task 6: non si puo' rispondere a un ticket non CLAIMED da te., Task 6: risposta manuale inoltrata a Meta Cloud API (mockata, niente rete…, set_env(), TestInboxAPI

### Community 69 - "vector_store.py"
Cohesion: 0.16
Nodes (16): LLM, SentenceTransformer, elenco_documenti(), _modello(), vettorizza(), rispondi(), cerca(), _collezione() (+8 more)

### Community 70 - "Brand Consistency Checklist"
Cohesion: 0.11
Nodes (17): Audit Frequency, Brand Consistency Checklist, Channel Audit, Collateral, Colors, Common Issues, Email, Imagery (+9 more)

### Community 71 - "CIP Mockup Prompt Engineering"
Cohesion: 0.11
Nodes (17): Apparel (Polo/T-Shirt), Base Prompt Structure, Business Card, CIP Mockup Prompt Engineering, Context Modifiers, Corporate Minimal, Deliverable-Specific Modifiers, Letterhead (+9 more)

### Community 72 - "Color Semantics"
Cohesion: 0.11
Nodes (17): Accent, Applying Semantic Tokens, Background & Foreground, Border & Ring, Color Semantics, Dark Mode Overrides, Destructive, Interactive States (+9 more)

### Community 73 - "fetch-background.py"
Cohesion: 0.17
Nodes (17): generate_css_for_background(), get_background_image(), get_curated_images(), get_overlay_css(), get_pexels_search_url(), load_backgrounds_config(), load_brand_colors(), main() (+9 more)

### Community 74 - "TestShadcnInstaller"
Cohesion: 0.11
Nodes (10): Test adding components in dry run mode., Test ShadcnInstaller class., Test adding all components without config., Test adding all components in dry run mode., Test listing installed components when none exist., Test listing installed components when they exist., Test initialization with dry run mode., Test checking for existing shadcn config. (+2 more)

### Community 75 - "test_dependencies.py"
Cohesion: 0.24
Nodes (8): get_current_user(), get_organization_context(), get_repo(), Request, _fake_request(), TestGetCurrentUser, TestGetOrganizationContext, TestGetRepo

### Community 76 - "scheduler.py"
Cohesion: 0.13
Nodes (23): _imposta_fonte_dati_per_scheduler(), lifespan(), FastAPI, BillingConfig, run_retention(), avvia_scheduler(), _calendar_sync_job(), ferma_scheduler() (+15 more)

### Community 77 - "Cosa può fare"
Cohesion: 0.11
Nodes (17): Benefici, Come funziona, Cos'è Sempre, Cosa può fare, Demo, Fatturazione & Piani (Stripe), Gestione prenotazioni, Gestione recensioni (+9 more)

### Community 78 - "billing/routes.py"
Cohesion: 0.25
Nodes (15): audit_log(), billing_webhook(), CheckoutSessionRequest, create_checkout_session(), create_portal_session(), _get_stripe(), get_subscription(), get_usage() (+7 more)

### Community 79 - "email_service.py"
Cohesion: 0.22
Nodes (9): EscalationEvent, _get_smtp_config(), retry, _send_with_retry(), start_worker(), stop_worker(), _worker(), fixture (+1 more)

### Community 80 - "WhatsApp Business Cloud API Integration — Implementation Plan"
Cohesion: 0.12
Nodes (15): File Structure, Files Created, Files Modified, Global Constraints, Task 10: Wiring — Mount Router in main.py, Task 1: Foundation — Config, Models, Dependencies, Task 2: `apply_status_update()` — Guardia Monotona, Task 3: Repository — Lookups, Contacts, Conversations (+7 more)

### Community 81 - "Struttura pagina (sezioni in ordine di scroll)"
Cohesion: 0.12
Nodes (15): 1. Navbar, 2. Hero, 3. Il problema, 4. Killer Feature (griglia 2x2), 5. Come funziona (3 passi), 6. Prova sociale, 7. CTA finale, 8. Footer (+7 more)

### Community 82 - "review_agent.py"
Cohesion: 0.20
Nodes (15): crea_review_agent(), crea_review_crew(), crea_review_task(), Agent, Crew, Task, costruisci_system_prompt_review(), costruisci_user_prompt_review() (+7 more)

### Community 83 - "Design Principles"
Cohesion: 0.12
Nodes (15): 22 Art Direction Styles, Banner Sizes & Art Direction Styles Reference, Complete Banner Sizes, CTA Rules, Design Principles, Pinterest Research Queries, Print, Print Specs (+7 more)

### Community 84 - "Design Principles"
Cohesion: 0.12
Nodes (15): 22 Art Direction Styles, Banner Sizes & Art Direction Styles Reference, Complete Banner Sizes, CTA Rules, Design Principles, Pinterest Research Queries, Print, Print Specs (+7 more)

### Community 85 - "icon/generate.py"
Cohesion: 0.20
Nodes (15): apply_color(), apply_viewbox_size(), extract_svgs(), generate_batch(), generate_icon(), generate_sizes(), load_env(), main() (+7 more)

### Community 86 - "fontSize"
Cohesion: 0.11
Nodes (20): $type, $value, $type, $value, $type, $value, $type, $value (+12 more)

### Community 87 - ".add_components"
Cohesion: 0.22
Nodes (7): main(), Add all available shadcn/ui components. Args: overwrite: If True, overwrite…, List installed components. Returns: Tuple of (success, message with component…, Check if shadcn is initialized in project. Returns: True if components.json…, Get list of already installed components. Returns: List of installed component…, Read shadcn version from project package.json; fall back to a pinned default., Add shadcn/ui components. Args: components: List of component names to add…

### Community 88 - "get"
Cohesion: 0.11
Nodes (25): middleware, _audit(), conteggio_documenti(), elenca_configurazioni(), elimina_documento_api(), health_check(), ottieni_dashboard(), ottieni_disponibilita() (+17 more)

### Community 89 - "GoogleCalendarService"
Cohesion: 0.06
Nodes (42): GoogleCalendarService, fernet_key(), patch_google_api(), fixture, Fixtures condivise per i test del modulo calendar. La Google Calendar API e'…, Chiave Fernet valida generata al volo per ogni test., Riga google_calendar_credentials gia' cifrata, pronta da INSERT., Monkey-patch le 3 chiamate di rete Google (insert/update/delete). Ritorna un… (+34 more)

### Community 91 - "CIP Design Reference"
Cohesion: 0.13
Nodes (14): CIP Brief (Start Here), CIP Design Reference, Commands, Deliverable Categories, Design Styles, Detailed References, Generate Mockups, HTML Presentation Features (+6 more)

### Community 92 - "Icon Design Reference"
Cohesion: 0.13
Nodes (14): Available Styles, CLI Options, Commands, Generate Batch Variations, Generate Multiple Sizes, Generate Single Icon, Icon Categories, Icon Design Reference (+6 more)

### Community 93 - "Copywriting Formulas"
Cohesion: 0.13
Nodes (14): AIDA (Attention-Interest-Desire-Action), Before-After-Bridge, Contrast Patterns, Copywriting Formulas, Core Formulas, Cost of Inaction, FAB (Features-Advantages-Benefits), Formula-to-Slide Mapping (+6 more)

### Community 94 - "Copywriting Formulas"
Cohesion: 0.13
Nodes (14): AIDA (Attention-Interest-Desire-Action), Before-After-Bridge, Contrast Patterns, Copywriting Formulas, Core Formulas, Cost of Inaction, FAB (Features-Advantages-Benefits), Formula-to-Slide Mapping (+6 more)

### Community 95 - "main"
Cohesion: 0.13
Nodes (8): main(), Add custom font families. Args: fonts: Dict of font_type: [font_names] e.g.,…, Add custom spacing values. Args: spacing: Dict of name: value e.g., {'18':…, Add custom breakpoints. Args: breakpoints: Dict of name: width e.g., {'3xl':…, Add plugin requirements. Args: plugins: List of plugin names e.g.,…, Get plugin recommendations based on configuration. Returns: List of recommended…, Validate configuration. Returns: Tuple of (valid, message), Add custom colors to theme. Args: colors: Dict of color_name: color_value Value…

### Community 96 - "search"
Cohesion: 0.17
Nodes (9): All indexed terms, for suggestion/typo-recovery purposes., Nearest known vocabulary terms for a query that returned 0 hits, so the caller…, Main search function with auto-domain detection, Search stack-specific guidelines, search(), search_stack(), _suggest_terms(), Known query -> expected top-domain sanity checks (not exact-row pinning, since… (+1 more)

### Community 97 - "RecensioneInput"
Cohesion: 0.30
Nodes (6): ABC, FonteRecensioni, FonteGoogle, FonteManuale, FonteTripAdvisor, RecensioneInput

### Community 98 - "Banner Design - Multi-Format Creative Banner System"
Cohesion: 0.14
Nodes (13): Art Direction Styles (Top 10), Banner Design - Multi-Format Creative Banner System, Banner Size Quick Reference, Design Rules, Prerequisites, Security, Step 1: Gather Requirements (AskUserQuestion), Step 2: Research & Art Direction (+5 more)

### Community 99 - "Messaging Framework"
Cohesion: 0.14
Nodes (13): Core Statements, Elevator Pitches, Framework Structure, Message Architecture, Message by Audience, Message Testing, Messaging Framework, Mission Statement (+5 more)

### Community 100 - "Brand Voice Framework"
Cohesion: 0.14
Nodes (13): Brand Voice Framework, Character Spectrum, Emotion Spectrum, Language Spectrum, Step 1: Define Personality Traits, Step 2: Create Voice Chart, Step 3: Context Adaptation, Tone Spectrum (+5 more)

### Community 101 - "extract-colors.cjs"
Cohesion: 0.22
Nodes (11): calculateCompliance(), colorDistance(), displayPalette(), extractHexColors(), findNearestBrandColor(), fs, generateImageMagickCommand(), hexToRgb() (+3 more)

### Community 102 - "validate-asset.cjs"
Cohesion: 0.25
Nodes (13): checkManifest(), formatBytes(), formatOutput(), fs, main(), parseFilename(), path, RULES (+5 more)

### Community 103 - "Layout Patterns"
Cohesion: 0.14
Nodes (13): Card Styles, Component Variants, CSS Structures, Feature Grid (3 columns), Layout Decision Flow, Layout Patterns, Layout Selection by Use Case, Metric Styles (+5 more)

### Community 104 - "cip/generate.py"
Cohesion: 0.23
Nodes (13): build_cip_prompt(), check_logo_required(), generate_cip_set(), generate_with_nano_banana(), load_env(), load_logo_image(), main(), Generate image using Gemini Nano Banana (native image generation) Supports two… (+5 more)

### Community 105 - "Tailwind Integration"
Cohesion: 0.14
Nodes (13): Animation Tokens, Base Layer, Button Example, Component Classes, CSS Variables Setup, Dark Mode Toggle, HSL Format Benefits, shadcn/ui Alignment (+5 more)

### Community 106 - "radius"
Cohesion: 0.13
Nodes (22): $type, $value, lg, $type, $value, $type, $value, $type (+14 more)

### Community 107 - "Layout Patterns"
Cohesion: 0.14
Nodes (13): Card Styles, Component Variants, CSS Structures, Feature Grid (3 columns), Layout Decision Flow, Layout Patterns, Layout Selection by Use Case, Metric Styles (+5 more)

### Community 108 - "ShadcnInstaller"
Cohesion: 0.14
Nodes (8): Handle shadcn/ui component installation., ShadcnInstaller, Test adding components without shadcn config., Test listing installed components without config., Test initialization with default project root., Test checking for non-existent shadcn config., Test getting installed components when none exist., Test getting installed components when files exist.

### Community 110 - "calendar/routes.py"
Cohesion: 0.27
Nodes (13): calendar_auth(), calendar_disconnect(), calendar_oauth2callback(), calendar_settings(), calendar_status(), CalendarSettingsInput, _get_client_config(), _make_flow() (+5 more)

### Community 111 - "test_logging_filter.py"
Cohesion: 0.29
Nodes (10): PIIWhitelistFilter, LogRecord, _make_record(), LogRecord, test_filter_allows_safe_metadata(), test_filter_blocks_email(), test_filter_blocks_empty(), test_filter_blocks_free_text() (+2 more)

### Community 112 - "File Structure"
Cohesion: 0.15
Nodes (11): Auth & Authorization Implementation Plan, File modificati, File Structure, Global Constraints, Nuovi file, Nuovo SQL, Self-Review Checklist, Task 1: DB Schema — Tabelle auth + trigger + RLS (+3 more)

### Community 113 - "update.md"
Cohesion: 0.15
Nodes (12): Color Presets, Examples, Files Modified, Important, Overview, Skills Used, Step 1: Gather Brand Input, Step 2: Update Brand Guidelines (+4 more)

### Community 114 - "Logo Design Reference"
Cohesion: 0.15
Nodes (12): Available Styles, Color Psychology, Commands, Design Brief (Start Here), Detailed References, Generate Logo, Industry Defaults, Logo Design Reference (+4 more)

### Community 115 - "Token Architecture"
Cohesion: 0.15
Nodes (12): Categories, Dark Mode, File Organization, Layer 1: Primitive Tokens, Layer 2: Semantic Tokens, Layer 3: Component Tokens, Layer Overview, Migration from Flat Tokens (+4 more)

### Community 116 - "primitive"
Cohesion: 0.15
Nodes (12): $type, $value, dark, semantic, primitive, $schema, $type, $value (+4 more)

### Community 117 - "Review: Robustezza Payload Meta e Webhook Status (Task 7)"
Cohesion: 0.15
Nodes (12): 1. `biz_opaque_callback_data` non validato come UUID, 2. `contacts` assente/vuoto in `_handle_inbound_message`, 3. Batch isolation — no `except Exception`, 4. Idempotenza — tabella `webhook_idempotency`, Files modificati, Modificati, Nuovi, Problemi riscontrati e correzioni (+4 more)

### Community 118 - "webhook_handler.py"
Cohesion: 0.27
Nodes (10): get_plan(), Plan, _handle_checkout_completed(), _handle_invoice_paid(), _handle_payment_failed(), _handle_subscription_deleted(), _handle_subscription_updated(), _init_plan_maps() (+2 more)

### Community 119 - "test_propagation.py"
Cohesion: 0.32
Nodes (11): propagate_delete_to_airtable(), propagate_delete_to_softr(), propagate_hard_delete(), _clean_env(), asyncio, fixture, test_propagate_delete_airtable_missing_config(), test_propagate_delete_airtable_success() (+3 more)

### Community 121 - "test_gdpr_fk.py"
Cohesion: 0.21
Nodes (12): _create_org_with_contact_and_booking(), Helper: crea organizzazione + contatto + booking + conversation., Se increment_message_usage fallisce, il messaggio NON viene salvato., Soft-delete contatto: booking rimane intatto, conversation deleted_at settato., Hard-delete contatto: booking.contact_id = NULL, nome/telefono = 'REDACTED'., Hard-delete contatto: CASCADE elimina conversation e contact_consent_log., delete_organization attiva il trigger BEFORE DELETE su contacts che anonimizza…, test_hard_delete_masks_pii() (+4 more)

### Community 122 - "test_retention.py"
Cohesion: 0.40
Nodes (12): contact_id(), conv_id(), msg_id(), org_id(), asyncio, fixture, test_cleanup_empty_conversations(), test_delete_expired_messages() (+4 more)

### Community 123 - "Global Constraints"
Cohesion: 0.17
Nodes (11): Global Constraints, Multi-tenant Persistence Schema — Implementation Plan, Task 1: DDL migration + base repository shell, Task 2: Bookings repository + tests, Task 3: Booking settings repository + tests, Task 4: Reviews repository + tests, Task 5: Documents + document_chunks repository (pgvector) + tests, Task 6: Email configs repository + tests (+3 more)

### Community 124 - "Global Constraints"
Cohesion: 0.17
Nodes (11): Booking Standalone Implementation Plan, Global Constraints, Task 1: DB Migration 007 + CoreRepository Extension, Task 2: BookingService — Core Availability + Lifecycle, Task 3: BookingService — Reminder Reply Hook, Task 4: BookingService — Deposito/Stripe Payment Links, Task 5: Booking API Routes, Task 6: Reminder Hook in InboundProcessor (+3 more)

### Community 125 - "Primitive Tokens"
Cohesion: 0.17
Nodes (11): Border Radius, Color Scales, Gray Scale, Motion / Duration, Primary Colors (Blue), Primitive Tokens, Shadows, Spacing Scale (+3 more)

### Community 126 - "validate-tokens.cjs"
Cohesion: 0.24
Nodes (11): extensions, formatReport(), fs, getFiles(), main(), parseArgs(), path, patterns (+3 more)

### Community 127 - "button"
Cohesion: 0.06
Nodes (45): $type, $value, $type, $value, bg, fg, font-size, hover-bg (+37 more)

### Community 128 - "test_tailwind_config_gen.py"
Cohesion: 0.20
Nodes (8): Tests for tailwind_config_gen.py, Reduce a generated TS/JS config to a bare assignable object so it can be handed…, Regression guard for the missing-comma bug between the ``theme`` block and…, The property preceding ``plugins`` must end with a comma (pure-Python check, so…, The emitted config parses as valid JS via ``node --check``., _strip_to_object(), TestGeneratedConfigIsValidJs, parametrize

### Community 129 - ".generate_config_string"
Cohesion: 0.20
Nodes (6): Generate configuration file content. Returns: Configuration file as string, Generate TypeScript configuration., Generate JavaScript configuration., Format plugins array for config. Validates each plugin name against a strict…, Add indentation to JSON string., Write configuration to file. Returns: Tuple of (success, message)

### Community 130 - "Files modificati"
Cohesion: 0.17
Nodes (11): 1. `src/whatsapp/client.py` — MetaClient hardening, 2. `src/whatsapp/router.py` — Webhook router resilience, 3. `src/core/db/repository.py` — Repository, 4. `src/core/billing/webhook_handler.py` — Stripe atomico, 5. `src/api/main.py` — Rate limit LLM globale + CORS + health check, 6. `src/whatsapp/repository.py` — Reply guard + heartbeat, 7. `src/whatsapp/inbound_processor.py` — Heartbeat loop + reply guard integration, 8. `tests/` — Riepilogo nuovi test (+3 more)

### Community 131 - "TemplateSyncer"
Cohesion: 0.29
Nodes (4): UUID, TemplateSyncer, mock, TestTemplateSyncer

### Community 132 - "whatsapp/conftest.py"
Cohesion: 0.30
Nodes (11): app_config(), button_reply_fixture(), message_webhook_fixture(), pg_pool(), postgres_container(), fixture, repo(), reset_db() (+3 more)

### Community 133 - "Global Constraints"
Cohesion: 0.18
Nodes (10): Billing & Stripe Integration Implementation Plan, Global Constraints, Task 1: Add billing columns migration, Task 2: Add stripe dependency and plan constants, Task 3: Add billing repository methods, Task 4: Add webhook handler, Task 5: Add billing API routes, Task 6: Add usage counting and limits middleware (+2 more)

### Community 134 - "Global Constraints"
Cohesion: 0.18
Nodes (10): Global Constraints, HITL Shared Inbox Implementation Plan, Task 1: Migration SQL + Schema Test, Task 2: Repository HITL Methods + Tests, Task 3: Email Notification Service + Tests, Task 4: Inbox API Routes + Tests, Task 5: Wire AI Escalation into InboundProcessor, Task 6: Idempotent Reply Endpoint (+2 more)

### Community 135 - "Global Constraints"
Cohesion: 0.18
Nodes (10): Global Constraints, Security & GDPR Compliance Implementation Plan, Task 1: .gitignore fix + git rm --cached + email_config.json -> env, Task 2: Token encryption — WhatsApp access_token encrypt-on-save, Task 3: Token encryption — Gmail token pickle -> Fernet, Task 4: PII Redaction — Strict Whitelist (no regex on free text), Task 5: Data retention — correct math + async cleanup job, Task 6: Consent tracking per contact + separate audit.log (+2 more)

### Community 136 - "Global Constraints"
Cohesion: 0.18
Nodes (10): Global Constraints, "Sempre" Landing Page Implementation Plan, Task 1: HTML Scaffold + Fonts + Custom CSS Variables + Nav, Task 2: Hero Section (2-col desktop, single mobile), Task 3: Problem Section (agitation + data point + bridge), Task 4: Killer Features Grid (2x2 invisible grid), Task 5: Come Funziona (3 steps with watermark numbers), Task 6: Social Proof (numbers + testimonial + logo bar) (+2 more)

### Community 137 - "Architecture — 6 Modules"
Cohesion: 0.18
Nodes (10): Architecture — 6 Modules, Audit Findings (Phase 1), Key Constraints, Module 1: Secrets & .gitignore, Module 2: Token Encryption (Art. 32), Module 3: PII Redaction in Logs, Module 4: Data Retention & Soft-delete (Art. 5), Module 5: GDPR Data Rights API (Art. 17 & 20) (+2 more)

### Community 138 - "Core Visual Elements"
Cohesion: 0.18
Nodes (10): Color Palette, Colors, Core Visual Elements, Logo, Logo, Quick Checks, Typography, Typography (+2 more)

### Community 139 - "inject-brand-context.cjs"
Cohesion: 0.31
Nodes (10): extractColorsFromTable(), extractCoreAttributes(), extractHexColors(), extractImageStyle(), extractTypography(), extractVoice(), fs, generatePromptAddition() (+2 more)

### Community 140 - "CIP Design Style Guide"
Cohesion: 0.18
Nodes (10): Bold Dynamic, CIP Design Style Guide, Classic Traditional, Color Psychology, Corporate Minimal, Fresh Modern, Luxury Premium, Modern Tech (+2 more)

### Community 141 - "embed-tokens.cjs"
Cohesion: 0.20
Nodes (9): args, extractTokens(), fs, minimal, MINIMAL_TOKENS, path, projectRoot, tokensPath (+1 more)

### Community 142 - "patch"
Cohesion: 0.18
Nodes (6): patch, Test adding components with overwrite flag., Test successful component addition., Test component addition with subprocess error., Test component addition when npx is not found., Test successful addition of all components.

### Community 143 - "Problemi riscontrati e correzioni"
Cohesion: 0.18
Nodes (10): 1. GDPR: FK contacts senza CASCADE/SET NULL, 2. `delete_organization()` non atomica, 3. Atomicità: messaggio salvato anche se usage increment fallisce, 4. Idempotenza webhook — tripla PK, 5. Mock pool test router — async context manager, Files modificati, Problemi riscontrati e correzioni, Task 8 — Review: GDPR Cascade + Atomicità Message/Usage + Idempotenza (+2 more)

### Community 144 - "email_config_store.py"
Cohesion: 0.46
Nodes (7): carica_config(), _carica_tutti(), elenca_config(), elimina_config(), inizializza(), salva_config(), _salva_tutti()

### Community 145 - "test_reminder_job.py"
Cohesion: 0.29
Nodes (8): mark_da_verificare_for_org(), check_timeouts_for_org(), send_reminders_for_org(), test_no_show_job_marks_da_verificare(), test_no_show_job_skips_completata(), test_reminder_timeout_flags_no_reply(), test_send_reminders_sends_for_tomorrow(), test_send_reminders_skips_in_attesa()

### Community 146 - "router.py"
Cohesion: 0.13
Nodes (19): skipif, dedup_check(), Atomic idempotency check via INSERT ON CONFLICT DO NOTHING. Returns True if…, create_router(), _handle_inbound_message(), _handle_status_update(), Request, Legge il body con limite di dimensione, supporta chunked encoding. (+11 more)

### Community 147 - "Brand"
Cohesion: 0.20
Nodes (9): Brand, Brand Sync Workflow, Quick Start, References, Routing, Scripts, Subcommands, Templates (+1 more)

### Community 148 - "Slide Strategies"
Cohesion: 0.20
Nodes (9): Common Structures, Duarte Sparkline Pattern, Matching Strategy to Context, Product Demo (6 slides), Sales Pitch (9 slides), Search Commands, Slide Strategies, Strategy Selection (+1 more)

### Community 150 - "Component Tokens"
Cohesion: 0.20
Nodes (9): Alert Tokens, Badge Tokens, Button Tokens, Card Tokens, Component Tokens, Dialog/Modal Tokens, Input Tokens, Table Tokens (+1 more)

### Community 151 - "generate-tokens.cjs"
Cohesion: 0.36
Nodes (9): flattenTokens(), fs, generateCSS(), generateTailwind(), main(), parseArgs(), path, resolveReference() (+1 more)

### Community 153 - "duration"
Cohesion: 0.20
Nodes (10): fast, normal, slow, $type, $value, $type, $value, duration (+2 more)

### Community 154 - "Slide Strategies"
Cohesion: 0.20
Nodes (9): Common Structures, Duarte Sparkline Pattern, Matching Strategy to Context, Product Demo (6 slides), Sales Pitch (9 slides), Search Commands, Slide Strategies, Strategy Selection (+1 more)

### Community 155 - "._base_config"
Cohesion: 0.22
Nodes (6): Any, Path, Initialize generator. Args: typescript: If True, generate .ts config, else .js…, Determine default output path., Create base configuration structure., Get default content paths for framework.

### Community 156 - "Riassunto modifiche"
Cohesion: 0.20
Nodes (9): Obiettivo, Punto 1 — Docker readiness, Punto 2 — CI/CD (GitHub Actions), Punto 3 — Sentry + trace_id, Punto 4 — requirements.txt pinnato + Pillow, Punto 5 — Encryption verificata, Riassunto modifiche, Risultato finale (+1 more)

### Community 157 - "Soluzione"
Cohesion: 0.20
Nodes (9): 1. Migrazione `012_reply_guard.sql`, 2. `src/whatsapp/repository.py` — 3 cambiamenti, 3. `src/whatsapp/inbound_processor.py` — heartbeat + guardia atomica, 4. Test di race condition, Files modificati, Problema, Soluzione, Task 6 — Review: Reply Guard & Heartbeat (+1 more)

### Community 158 - "sm"
Cohesion: 0.60
Nodes (5): sm, sm, sm, $type, $value

### Community 159 - "primary"
Cohesion: 0.67
Nodes (3): primary, $type, $value

### Community 160 - "billing/test_routes.py"
Cohesion: 0.22
Nodes (3): async_client(), fixture, set_env()

### Community 161 - "test_deposito.py"
Cohesion: 0.36
Nodes (8): deep_update(), _setup_deposito_settings(), test_deposito_genera_payment_link(), test_deposito_matcha_coperti_min(), test_deposito_matcha_data(), test_deposito_matcha_fascia_oraria(), test_deposito_matcha_tipo_evento(), test_deposito_non_matcha_coperti_sotto_soglia()

### Community 162 - "inviaMessaggio"
Cohesion: 0.22
Nodes (10): aggiornaPrioritari(), aggiornaReport(), aggiornaRiepilogo(), aggiornaTrends(), aggiungiBollaChat(), inviaMessaggio(), inviaRecensione(), mostraTyping() (+2 more)

### Community 163 - "inizializzaOnboarding"
Cohesion: 0.22
Nodes (10): caricaProfiloOnboarding(), generaPreviewOnboarding(), inizializzaOnboarding(), profiloOnboarding(), renderEscalationRules(), renderOnboardingStep(), renderVerticals(), righeDaTextarea() (+2 more)

### Community 164 - "_run"
Cohesion: 0.28
Nodes (8): CompletedProcess, Path, Regression tests for validate-tokens.cjs. The validator used to skip any line…, A hardcoded hex on the same line as a var() token is still a violation., A line that references only tokens produces no false positives., _run(), test_flags_hardcoded_hex_sharing_line_with_token(), test_token_only_line_reports_no_violation()

### Community 165 - "sync-brand-to-tokens.cjs"
Cohesion: 0.33
Nodes (8): adjustBrightness(), { execFileSync }, extractColorsFromMarkdown(), fs, generateColorScale(), main(), path, updateDesignTokens()

### Community 166 - "core/conftest.py"
Cohesion: 0.39
Nodes (8): other_org(), pg_pool(), postgres_container(), fixture, repo(), reset_db(), sample_contact(), sample_org()

### Community 167 - "Upgrade Landing "Sempre" — Piano completo"
Cohesion: 0.22
Nodes (8): 1) INTEGRAZIONE IMMAGINE — nuova sezione brand "full-bleed" (il salto di qualità principale), 2) CORREZIONI DESIGN-SYSTEM (violazioni reali della Pre-Flight Check), 3) MOTION UPGRADE (motivato, transform/opacity only, ridotta-motion gating), 4) DARK MODE (mandatory per consumer), 5) ACCESSIBILITÀ & POLISH, 6) FILE COINVOLTI, 7) RISCHI & NOTE, Upgrade Landing "Sempre" — Piano completo

### Community 168 - "render-html.py"
Cohesion: 0.36
Nodes (7): generate_html(), get_deliverable_info(), get_image_base64(), main(), Convert image to base64 for embedding in HTML, Extract deliverable type from filename and get info, Generate HTML presentation from CIP images

### Community 171 - "dependencies.py"
Cohesion: 0.36
Nodes (7): AsyncClient, close_http_client(), get_http_client(), _get_supabase_jwks(), is_demo_mode(), _load_project_env(), verify_supabase_jwt()

### Community 172 - "Slides Reference"
Cohesion: 0.29
Nodes (6): Key Features, Knowledge Base, Slides Reference, Usage, When to Use, Workflow

### Community 173 - "HTML Slide Template"
Cohesion: 0.29
Nodes (6): Animation Classes, Background Images, Base Structure, Chart.js Integration, CSS Variables Reference, HTML Slide Template

### Community 174 - "HTML Slide Template"
Cohesion: 0.29
Nodes (6): Animation Classes, Background Images, Base Structure, Chart.js Integration, CSS Variables Reference, HTML Slide Template

### Community 175 - "detect_domain"
Cohesion: 0.43
Nodes (3): detect_domain(), Auto-detect the most relevant domain from query. Matches are weighted by…, TestDomainDetection

### Community 179 - "Slides"
Cohesion: 0.33
Nodes (5): References (Knowledge Base), Routing, Slides, Subcommands, When to Use

### Community 184 - "test_repository_documents.py"
Cohesion: 0.53
Nodes (5): asyncio, test_create_document_and_add_chunks(), test_document_chunk_cross_tenant_trigger(), test_list_documents(), test_search_similar_returns_chunks()

### Community 185 - "test_repository_email_configs.py"
Cohesion: 0.53
Nodes (5): asyncio, test_add_and_list_email_configs(), test_duplicate_email_config(), test_email_config_org_isolation(), test_remove_email_config()

### Community 187 - "aggiornaPrenotazioni"
Cohesion: 0.40
Nodes (6): aggiornaListaGiorno(), aggiornaPrenotazioni(), aggiornaSemaforo(), colorePrenotazione(), inizializzaCalendarioPrenotazioni(), oggiIso()

### Community 188 - "Brand Guidelines Template"
Cohesion: 0.40
Nodes (4): Brand Guidelines Template, Document Structure, Extractable Fields, Usage

### Community 193 - "Migration Scripts"
Cohesion: 0.40
Nodes (4): Migration Scripts, Order, Prerequisites, Verification

### Community 196 - "aggiornaNotifiche"
Cohesion: 0.60
Nodes (5): aggiornaBadgeNotifiche(), aggiornaNotifiche(), leggiStatoNotifiche(), salvaStatoNotifiche(), segnaNotificheViste()

### Community 197 - "opencode.json"
Cohesion: 0.50
Nodes (3): plugin, $schema, .opencode/plugins/graphify.js

### Community 201 - "core/__init__.py"
Cohesion: 0.32
Nodes (5): format_output(), Format results for Claude consumption (token-optimized), _check_file(), main(), _read_rows()

### Community 203 - "test_repository_booking_settings.py"
Cohesion: 0.67
Nodes (3): asyncio, test_booking_settings_unique_per_org(), test_upsert_and_get_settings()

### Community 204 - "test_repository_reviews.py"
Cohesion: 0.67
Nodes (3): asyncio, test_create_and_list_reviews(), test_review_star_validation()

### Community 205 - "test_repository_usage.py"
Cohesion: 0.67
Nodes (3): asyncio, test_record_and_query_usage(), test_usage_summary()

### Community 206 - "test_triggers_event_log.py"
Cohesion: 0.67
Nodes (3): asyncio, test_message_event_triggers_event_log(), test_review_event_triggers_event_log()

### Community 207 - "Checklist pre-lancio — whatsapp-ai-responder"
Cohesion: 0.50
Nodes (3): Checklist pre-lancio — whatsapp-ai-responder, Google Calendar Sync, WhatsApp / Meta Cloud API

### Community 218 - "primary-foreground"
Cohesion: 0.67
Nodes (3): primary-foreground, $type, $value

## Knowledge Gaps
- **1318 isolated node(s):** `$schema`, `.opencode/plugins/graphify.js`, `fs`, `path`, `fs` (+1313 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **37 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Repository` connect `Repository` to `_headers`, `main.py`, `TestInboxAPI`, `whatsapp/conftest.py`, `scheduler.py`, `apply_status_update`, `inbox/routes.py`, `AppConfig`, `UUID`, `gdpr/routes.py`, `test_repository.py`, `test_gdpr_fk.py`, `TestTicketRepository`?**
  _High betweenness centrality (0.018) - this node is a cross-community bridge._
- **Why does `CoreRepository` connect `CoreRepository` to `main.py`, `core/conftest.py`, `scheduler.py`, `time`, `billing/routes.py`, `email_service.py`, `AppConfig`, `webhook_handler.py`, `gdpr/routes.py`, `test_gdpr_fk.py`?**
  _High betweenness centrality (0.015) - this node is a cross-community bridge._
- **Why does `TailwindConfigGenerator` connect `TailwindConfigGenerator` to `test_tailwind_config_gen.py`, `.generate_config_string`, `.test_add_fonts`, `.test_recommend_plugins`, `.test_generate_typescript_config`, `.test_generate_config_with_plugins`, `.test_init_javascript`, `.test_write_config_creates_content`, `.test_write_config_invalid_path`, `.test_default_output_path_typescript`, `.test_default_content_paths_vue`, `.test_add_colors`, `TestTailwindConfigGenerator`, `._base_config`, `main`?**
  _High betweenness centrality (0.012) - this node is a cross-community bridge._
- **Are the 3 inferred relationships involving `CoreRepository` (e.g. with `ConsentPrefsInput` and `ConsentPrefsOutput`) actually correct?**
  _`CoreRepository` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Are the 2 inferred relationships involving `TailwindConfigGenerator` (e.g. with `TestGeneratedConfigIsValidJs` and `TestTailwindConfigGenerator`) actually correct?**
  _`TailwindConfigGenerator` has 2 INFERRED edges - model-reasoned connections that need verification._
- **Are the 3 inferred relationships involving `WhatsAppService` (e.g. with `MetaClient` and `OutboundTextPayload`) actually correct?**
  _`WhatsAppService` has 3 INFERRED edges - model-reasoned connections that need verification._
- **What connects `$schema`, `.opencode/plugins/graphify.js`, `fs` to the rest of the system?**
  _1318 weakly-connected nodes found - possible documentation gaps or missing edges._