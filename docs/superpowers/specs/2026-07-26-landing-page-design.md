# Landing Page "Melpis" — Specifica di Design

## Brand

- **Nome:** Melpis
- **Posizionamento:** "L'assistente clienti che non ti fa perdere prenotazioni, recensioni e ticket urgenti mentre sei in servizio"
- **Tono:** Professionale, rassicurante, mai hype
- **Target:** Tutti i settori (ristorazione, bellezza, salute, servizi)
- **Frase chiave:** *"Il tuo assistente clienti su WhatsApp. Mentre tu lavori."*

## Stack tecnico

- HTML + Tailwind CSS (CDN) + Vanilla JS
- Animazioni: AOS (Animate On Scroll) via CDN
- Icone: Lucide (stroke-width 1.5)
- Zero build step, deploy su static host

## Palette

- **Sfondo:** Carbone `#1A1A1E`
- **Testo:** Avorio `#F5F0EB`
- **Accento primario:** Verde salvia `#7BA88F`
- **Testo su bottoni:** Carbone `#1A1A1E` (per contrasto WCAG su sfondo salvia)
- **Sfondo sezione sociale:** `#222120`
- **Filigrana numeri:** `#7BA88F` / 10% opacity

## Tipografia

- **Titoli:** Fraunces (serif) — importato da Google Fonts
- **Corpo:** Inter (sans-serif) — importato da Google Fonts
- **Tracking logo bar:** uppercase, tracking-widest

## Struttura pagina (sezioni in ordine di scroll)

### 1. Navbar

- Fissa, backdrop blur.
- Logo "Melpis" a sinistra in Fraunces.
- Bottone "Prova gratis 7 giorni" a destra (verde salvia pieno).
- Nessun menu, nessun hamburger. Desktop e mobile identici.

### 2. Hero

- `min-h-[90vh]` — la sezione successiva fa capolino per invitare allo scroll.
- **Desktop:** layout 2 colonne (50/50).
  - Sinistra: Titolo → Sottotitolo → CTA.
  - Destra: mockup telefono/chat come ancoraggio visivo (placeholder HTML: rettangolo arrotondato con bordo verde salvia, bolle chat simulate via CSS, icona WhatsApp centrata, in attesa di immagine definitiva).
- **Mobile:** singola colonna. Titolo → Sottotitolo → CTA → Mockup.
- **Titolo:** "Risposte immediate su WhatsApp. Mentre tu lavori." (Fraunces, grande)
- **Sottotitolo:** "Melpis risponde ai tuoi clienti su WhatsApp in tempo reale, gestisce prenotazioni e recensioni, e ti avvisa solo quando serve davvero. L'assistente instancabile per ristoranti, saloni e attività locali." (Inter)
- **CTA:** "Inizia la prova gratuita →" (bottone verde salvia, testo carbone `#1A1A1E`, `px-8 py-4 font-semibold`, `hover:scale-105 transition-all`)

### 3. Il problema

- Container stretto centrato (`max-w-2xl mx-auto`), testo `text-xl`.
- **Titolo:** "Ogni cliente che aspetta, è un cliente che se ne va."
- **Copy di agitazione:** "Un messaggio su WhatsApp senza risposta, una recensione ignorata, una prenotazione persa. Mentre sei in sala, in negozio o nello studio, il telefono squilla."
- **Data point:** "78%" gigante (Fraunces, verde salvia) — "dei clienti si aspetta una risposta entro 60 minuti su WhatsApp (Meta, 2024)".
- **Bridge:** whitespace extra + "Con Melpis, non devi più scegliere tra servire chi hai davanti e rispondere a chi ti scrive." in grassetto.

### 4. Killer Feature (griglia 2x2)

- Nessun bordo, nessuna ombra, nessuna card — solo spazio e tipografia.
- **Gap:** `gap-12`/`gap-16` su desktop.
- Ogni blocco: icona Lucide (verde salvia, `w-8 h-8`, stroke 1.5) → titolo Fraunces `text-2xl` `mb-2` → corpo Inter `text-base`/`text-lg` con opacità ridotta.

| # | Titolo | Copy |
|---|--------|------|
| 1 | Risposte WhatsApp in tempo reale | Mentre sei in servizio, Melpis risponde ai clienti su WhatsApp. Veloce, preciso, in italiano. |
| 2 | Prenotazioni automatiche | Legge il calendario, controlla la disponibilità e conferma. Il cliente vede subito se c'è posto. |
| 3 | Allerta umana intelligente (HITL) | Se la richiesta è delicata o fuori copione, ti gira solo quella. Il resto lo gestisce lui. |
| 4 | Report serale automatico | Ogni sera, un riepilogo di messaggi, prenotazioni, recensioni e suggerimenti. Pronto quando arrivi. |

### 5. Come funziona (3 passi)

- Layout orizzontale 3 colonne desktop, verticale mobile.
- Ogni passo: contenitore `relative`. Numero in filigrana (`absolute`, verde salvia `/10`, Fraunces gigante, ancorato in alto a sinistra). Testo in primo piano (`relative z-10`).
- Allineamento `text-left`.

| Passo | Titolo | Copy |
|-------|--------|------|
| 1 | Colleghi | Colleghi Melpis al tuo account WhatsApp Business in 2 click. Nessun cavo, nessun tecnico. |
| 2 | Personalizzi | Carichi menu, listini, orari e regole. Lui impara e comincia a rispondere. |
| 3 | Lavori | Melpis gestisce i messaggi, le prenotazioni e le recensioni. Tu fai quello che sai fare meglio. |

### 6. Prova sociale

- **Sfondo:** `#222120` (micro-shift caldo).
- **Numeri:** Fraunces `text-5xl`/`text-6xl` verde salvia + label Inter avorio.
  - "Oltre 500 attività usano Melpis"
  - "10.000+ conversazioni gestite al giorno"
- **Testimonial:** virgolette giganti in filigrana (`#7BA88F/10`) dietro la citazione. Frase breve, nome e attività.
- **Logo bar (settori):** Inter uppercase, tracking-widest, opacità 50%, flex wrap centrato. "Ristorazione · Bellezza · Salute · Servizi"

### 7. CTA finale

- Sfondo carbone standard (`#1A1A1E`), nessun blocco separato.
- Spaziatura oceanica (`py-24`/`py-32`).
- **Titolo:** "Pronto a non perdere più un cliente?" (Fraunces, `text-balance`)
- **Sub:** "Prova Melpis gratis per 7 giorni. Nessuna carta di credito. Attivazione in 5 minuti." (Inter)
- **Bottone:** verde salvia, testo carbone `#1A1A1E`, `px-8 py-4 font-semibold`, `hover:scale-105 transition-all`
- **Micro-testo sotto:** "Funziona con WhatsApp Business. Assistenza inclusa."

### 8. Footer

- Sfondo carbone o leggermente più scuro.
- Link: Privacy, Termini di servizio, Chi siamo, Contatti.
- Copyright "Melpis — © 2026"
- Layout: riga orizzontale su desktop, colonna su mobile.
- Tipografia ridotta (`text-sm`), avorio opaco.

## Copia della landing attuale

La landing esistente in `web/landing page/landing.html` verrà riscritta da zero. Il file `web/index.html` (pannello demo) rimane invariato.
