# "Sempre" Landing Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite `web/landing page/landing.html` from "Modern Operator" dark-orange theme to "Sempre" brand with carbon/ivory/sage palette.

**Architecture:** Single static HTML file with Tailwind CSS (CDN), AOS animations (CDN), Lucide icons (CDN), and minimal inline `<style>` for custom fonts and WhatsApp mockup. Zero build step.

**Tech Stack:** HTML5, Tailwind CSS v3 (CDN via `<script>`), Google Fonts (Fraunces + Inter), AOS 2.3.1, Lucide icons (SVG inline or CDN).

## Global Constraints

- Brand name: "Sempre" — not "Evergreen" or "Modern Operator"
- Palette: Carbone `#1A1A1E` bg, Avorio `#F5F0EB` text, Verde salvia `#7BA88F` accent, `#222120` social section bg
- Button text color: Carbone `#1A1A1E` (contrast WCAG on salvia bg)
- No hamburger menu, no nav links — just logo left + CTA right
- Mockup in hero: HTML/CSS placeholder with chat bubbles, not an external image
- AOS on scroll for feature cards, problem section, CTA sections

---

### Task 1: HTML Scaffold + Fonts + Custom CSS Variables + Nav

**Files:**
- Rewrite: `web/landing page/landing.html` (entirely)

**Interfaces:**
- Consumes: nothing
- Produces: HTML shell with `<head>` (fonts, Tailwind CDN, AOS CDN, custom style block), `<body>` with Navbar

- [ ] **Step 1: Write the scaffold**

```html
<!DOCTYPE html>
<html lang="it">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Sempre — Il tuo assistente clienti su WhatsApp</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,600;0,9..144,700;1,9..144,400&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet" />
  <link href="https://unpkg.com/aos@2.3.1/dist/aos.css" rel="stylesheet" />
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://unpkg.com/lucide@latest"></script>
  <style>
    body { font-family: 'Inter', sans-serif; }
    h1, h2, h3, .font-serif { font-family: 'Fraunces', serif; }
    .chat-bubble-left { position: relative; background: rgba(123, 168, 143, 0.15); border-radius: 18px 18px 18px 4px; }
    .chat-bubble-right { position: relative; background: rgba(245, 240, 235, 0.08); border-radius: 18px 18px 4px 18px; }
  </style>
</head>
<body class="bg-[#1A1A1E] text-[#F5F0EB] antialiased">
```

Tailwind config in the `<script>` block:

```html
<script>
  tailwind.config = {
    theme: {
      extend: {
        colors: {
          carbone: '#1A1A1E',
          avorio: '#F5F0EB',
          salvia: '#7BA88F',
          social: '#222120',
        }
      }
    }
  }
</script>
```

- [ ] **Step 2: Write the Navbar**

```html
<nav class="fixed top-0 left-0 right-0 z-50 backdrop-blur-md bg-[#1A1A1E]/80">
  <div class="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
    <span class="font-serif text-2xl font-semibold tracking-tight">Sempre</span>
    <a href="#" class="inline-block bg-salvia text-carbone px-5 py-2.5 rounded-full text-sm font-semibold hover:scale-105 transition-all">Prova gratis 7 giorni</a>
  </div>
</nav>
```

- [ ] **Step 3: Verify** — Open file in browser. Navbar visible at top, backdrop blur works, CTA button shows with correct colors.

- [ ] **Step 4: Commit**

```bash
git add web/landing\ page/landing.html
git commit -m "feat(landing): scaffold with navbar + brand palette"
```

---

### Task 2: Hero Section (2-col desktop, single mobile)

- [ ] **Step 1: Write the Hero HTML**

```html
<section class="min-h-[90vh] flex items-center pt-16">
  <div class="max-w-7xl mx-auto px-6 w-full">
    <div class="grid md:grid-cols-2 gap-12 items-center">
      <!-- Left: text + CTA -->
      <div class="space-y-6" data-aos="fade-up" data-aos-duration="1000">
        <h1 class="font-serif text-5xl md:text-7xl font-bold leading-tight">
          Risposte immediate su WhatsApp.<br />
          <span class="text-salvia">Mentre tu lavori.</span>
        </h1>
        <p class="text-lg md:text-xl text-[#F5F0EB]/70 max-w-xl leading-relaxed">
          Sempre risponde ai tuoi clienti su WhatsApp in tempo reale, gestisce prenotazioni e recensioni, e ti avvisa solo quando serve davvero. L'assistente instancabile per ristoranti, saloni e attività locali.
        </p>
        <a href="#" class="inline-block bg-salvia text-carbone px-8 py-4 rounded-full text-lg font-semibold hover:scale-105 transition-all">Inizia la prova gratuita &rarr;</a>
      </div>
      <!-- Right: mockup chat -->
      <div class="hidden md:flex justify-center" data-aos="fade-left" data-aos-delay="300">
        <div class="w-80 rounded-3xl border border-salvia/20 bg-[#1A1A1E] p-4 shadow-2xl shadow-salvia/5">
          <div class="flex items-center gap-3 pb-3 border-b border-[#F5F0EB]/10 mb-4">
            <div class="w-8 h-8 rounded-full bg-salvia/20 flex items-center justify-center">
              <i data-lucide="message-circle" class="w-4 h-4 text-salvia"></i>
            </div>
            <div>
              <p class="text-sm font-medium">Sempre</p>
              <p class="text-xs text-[#F5F0EB]/50">Online</p>
            </div>
          </div>
          <div class="space-y-3">
            <div class="chat-bubble-left p-3 max-w-[80%]">
              <p class="text-sm">Buongiorno, avete un tavolo per stasera alle 20:00 per 4 persone?</p>
            </div>
            <div class="chat-bubble-right p-3 max-w-[85%] ml-auto">
              <p class="text-sm">Buongiorno! Le confermo che abbiamo disponibilità per 4 alle 20:00. Posso procedere con la prenotazione?</p>
            </div>
            <div class="chat-bubble-left p-3 max-w-[75%]">
              <p class="text-sm">Perfetto, confermo! Grazie.</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</section>
```

- [ ] **Step 2: Add mobile mockup below the fold** (CTA first, then mockup below)

After the grid's closing div, add a mobile-only block:

```html
<div class="flex md:hidden justify-center mt-8" data-aos="fade-up" data-aos-delay="400">
  <!-- same mockup card as above -->
</div>
```

- [ ] **Step 3: Verify** — Desktop: 2 columns, CTA visible without scroll. Mobile: CTA before mockup.

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(landing): hero section with 2-col layout + chat mockup"
```

---

### Task 3: Problem Section (agitation + data point + bridge)

- [ ] **Step 1: Write Problem section**

```html
<section class="py-24 md:py-32">
  <div class="max-w-2xl mx-auto px-6 text-center" data-aos="fade-up">
    <h2 class="font-serif text-3xl md:text-4xl font-semibold mb-8 leading-tight">
      Ogni cliente che aspetta,<br />è un cliente che se ne va.
    </h2>
    <p class="text-xl text-[#F5F0EB]/70 leading-relaxed mb-12">
      Un messaggio su WhatsApp senza risposta, una recensione ignorata, una prenotazione persa. Mentre sei in sala, in negozio o nello studio, il telefono squilla.
    </p>
    <!-- Data point -->
    <div class="flex items-center justify-center gap-4 mb-16">
      <span class="font-serif text-7xl md:text-8xl font-bold text-salvia leading-none">78%</span>
      <p class="text-left text-sm text-[#F5F0EB]/60 max-w-xs leading-relaxed">
        dei clienti si aspetta una risposta entro 60 minuti su WhatsApp.<br />
        <span class="text-[#F5F0EB]/40">— Meta, 2024</span>
      </p>
    </div>
    <!-- Bridge -->
    <p class="text-xl font-semibold text-[#F5F0EB] leading-relaxed pt-12 border-t border-[#F5F0EB]/10">
      Con <span class="text-salvia">Sempre</span>, non devi più scegliere tra servire chi hai davanti e rispondere a chi ti scrive.
    </p>
  </div>
</section>
```

- [ ] **Step 2: Verify** — Container centered, data point prominent with 78% in salvia, bridge sentence separated by whitespace + border-top.

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(landing): problem section with data point + bridge"
```

---

### Task 4: Killer Features Grid (2x2 invisible grid)

- [ ] **Step 1: Write Features section**

```html
<section class="py-24 md:py-32">
  <div class="max-w-6xl mx-auto px-6">
    <h2 class="font-serif text-3xl md:text-4xl font-semibold text-center mb-16" data-aos="fade-up">Tutto quello che serve.<br />Niente di più.</h2>
    <div class="grid md:grid-cols-2 gap-12 md:gap-16">
      <!-- Feature 1 -->
      <div data-aos="fade-up">
        <i data-lucide="message-circle" class="w-8 h-8 text-salvia mb-4"></i>
        <h3 class="font-serif text-2xl mb-2">Risposte WhatsApp in tempo reale</h3>
        <p class="text-[#F5F0EB]/60 text-lg leading-relaxed">Mentre sei in servizio, Sempre risponde ai clienti su WhatsApp. Veloce, preciso, in italiano.</p>
      </div>
      <!-- Feature 2 -->
      <div data-aos="fade-up" data-aos-delay="100">
        <i data-lucide="calendar-check" class="w-8 h-8 text-salvia mb-4"></i>
        <h3 class="font-serif text-2xl mb-2">Prenotazioni automatiche</h3>
        <p class="text-[#F5F0EB]/60 text-lg leading-relaxed">Legge il calendario, controlla la disponibilità e conferma. Il cliente vede subito se c'è posto.</p>
      </div>
      <!-- Feature 3 -->
      <div data-aos="fade-up" data-aos-delay="200">
        <i data-lucide="eye" class="w-8 h-8 text-salvia mb-4"></i>
        <h3 class="font-serif text-2xl mb-2">Allerta umana intelligente</h3>
        <p class="text-[#F5F0EB]/60 text-lg leading-relaxed">Se la richiesta è delicata o fuori copione, ti gira solo quella. Il resto lo gestisce lui.</p>
      </div>
      <!-- Feature 4 -->
      <div data-aos="fade-up" data-aos-delay="300">
        <i data-lucide="file-text" class="w-8 h-8 text-salvia mb-4"></i>
        <h3 class="font-serif text-2xl mb-2">Report serale automatico</h3>
        <p class="text-[#F5F0EB]/60 text-lg leading-relaxed">Ogni sera, un riepilogo di messaggi, prenotazioni, recensioni e suggerimenti. Pronto quando arrivi.</p>
      </div>
    </div>
  </div>
</section>
```

- [ ] **Step 2: Verify** — Grid 2 columns desktop, 1 column mobile. No borders/cards. Salvia icons + serif titles.

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(landing): killer features invisible grid"
```

---

### Task 5: Come Funziona (3 steps with watermark numbers)

- [ ] **Step 1: Write How-It-Works section**

```html
<section class="py-24 md:py-32">
  <div class="max-w-6xl mx-auto px-6">
    <h2 class="font-serif text-3xl md:text-4xl font-semibold text-center mb-16" data-aos="fade-up">Come funziona</h2>
    <div class="grid md:grid-cols-3 gap-12 md:gap-16">
      <!-- Step 1 -->
      <div class="relative" data-aos="fade-up">
        <span class="absolute -top-8 -left-4 font-serif text-9xl font-bold text-salvia/10 select-none pointer-events-none leading-none">1</span>
        <div class="relative z-10">
          <h3 class="font-serif text-2xl mb-3">Colleghi</h3>
          <p class="text-[#F5F0EB]/60 text-lg leading-relaxed">Colleghi Sempre al tuo account WhatsApp Business in 2 click. Nessun cavo, nessun tecnico.</p>
        </div>
      </div>
      <!-- Step 2 -->
      <div class="relative" data-aos="fade-up" data-aos-delay="100">
        <span class="absolute -top-8 -left-4 font-serif text-9xl font-bold text-salvia/10 select-none pointer-events-none leading-none">2</span>
        <div class="relative z-10">
          <h3 class="font-serif text-2xl mb-3">Personalizzi</h3>
          <p class="text-[#F5F0EB]/60 text-lg leading-relaxed">Carichi menu, listini, orari e regole. Lui impara e comincia a rispondere.</p>
        </div>
      </div>
      <!-- Step 3 -->
      <div class="relative" data-aos="fade-up" data-aos-delay="200">
        <span class="absolute -top-8 -left-4 font-serif text-9xl font-bold text-salvia/10 select-none pointer-events-none leading-none">3</span>
        <div class="relative z-10">
          <h3 class="font-serif text-2xl mb-3">Lavori</h3>
          <p class="text-[#F5F0EB]/60 text-lg leading-relaxed">Sempre gestisce i messaggi, le prenotazioni e le recensioni. Tu fai quello che sai fare meglio.</p>
        </div>
      </div>
    </div>
  </div>
</section>
```

- [ ] **Step 2: Verify** — Watermark numbers visible behind text, 3 columns desktop, text-left alignment.

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(landing): how it works with watermark numbers"
```

---

### Task 6: Social Proof (numbers + testimonial + logo bar)

- [ ] **Step 1: Write Social Proof section** with bg shift

```html
<section class="py-24 md:py-32 bg-[#222120]">
  <div class="max-w-6xl mx-auto px-6 text-center">
    <!-- Logo bar -->
    <div class="flex justify-center gap-8 flex-wrap mb-16 uppercase tracking-widest text-sm text-[#F5F0EB]/50 font-medium">
      <span>Ristorazione</span>
      <span class="text-[#F5F0EB]/20">&middot;</span>
      <span>Bellezza</span>
      <span class="text-[#F5F0EB]/20">&middot;</span>
      <span>Salute</span>
      <span class="text-[#F5F0EB]/20">&middot;</span>
      <span>Servizi</span>
    </div>
    <!-- Numbers -->
    <div class="grid md:grid-cols-2 gap-8 max-w-3xl mx-auto mb-16" data-aos="fade-up">
      <div>
        <p class="font-serif text-6xl text-salvia font-bold">500+</p>
        <p class="text-[#F5F0EB]/60 text-lg">attività usano Sempre</p>
      </div>
      <div>
        <p class="font-serif text-6xl text-salvia font-bold">10.000+</p>
        <p class="text-[#F5F0EB]/60 text-lg">conversazioni gestite al giorno</p>
      </div>
    </div>
    <!-- Testimonial -->
    <div class="relative max-w-2xl mx-auto" data-aos="fade-up">
      <span class="absolute -top-12 -left-4 font-serif text-8xl text-salvia/10 select-none pointer-events-none leading-none">&ldquo;</span>
      <div class="relative z-10">
        <p class="text-xl italic text-[#F5F0EB]/80 leading-relaxed mb-4">"Non ho più perso una prenotazione da quando uso Sempre."</p>
        <p class="text-sm text-[#F5F0EB]/50">Marco Rossi, Ristorante Al Portico</p>
      </div>
    </div>
  </div>
</section>
```

- [ ] **Step 2: Verify** — `#222120` background visible, numbers prominent, testimonial has large opening quote watermark.

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(landing): social proof with numbers + testimonial + sectors"
```

---

### Task 7: CTA Final + Footer

- [ ] **Step 1: Write CTA section**

```html
<section class="py-32 md:py-40 text-center">
  <div class="max-w-3xl mx-auto px-6" data-aos="fade-up">
    <h2 class="font-serif text-4xl md:text-5xl font-semibold mb-6 text-balance">Pronto a non perdere più un cliente?</h2>
    <p class="text-lg md:text-xl text-[#F5F0EB]/60 mb-10 leading-relaxed">Prova Sempre gratis per 7 giorni. Nessuna carta di credito. Attivazione in 5 minuti.</p>
    <a href="#" class="inline-block bg-salvia text-carbone px-8 py-4 rounded-full text-lg font-semibold hover:scale-105 transition-all">Inizia la prova gratuita &rarr;</a>
    <p class="text-sm text-[#F5F0EB]/40 mt-6">Funziona con WhatsApp Business. Assistenza inclusa.</p>
  </div>
</section>
```

- [ ] **Step 2: Write Footer**

```html
<footer class="border-t border-[#F5F0EB]/10 py-8">
  <div class="max-w-7xl mx-auto px-6 flex flex-col md:flex-row items-center justify-between gap-4">
    <div class="flex gap-6 text-sm text-[#F5F0EB]/40">
      <a href="#" class="hover:text-[#F5F0EB]/70 transition-colors">Privacy</a>
      <a href="#" class="hover:text-[#F5F0EB]/70 transition-colors">Termini</a>
      <a href="#" class="hover:text-[#F5F0EB]/70 transition-colors">Chi siamo</a>
      <a href="#" class="hover:text-[#F5F0EB]/70 transition-colors">Contatti</a>
    </div>
    <p class="text-sm text-[#F5F0EB]/30">Sempre &mdash; &copy; 2026</p>
  </div>
</footer>
```

- [ ] **Step 3: Add AOS init + Lucide icon mount at end of body**

```html
<script src="https://unpkg.com/aos@2.3.1/dist/aos.js"></script>
<script>
  AOS.init({ duration: 800, once: true, disable: 'mobile' });
  lucide.createIcons();
</script>
</body>
</html>
```

- [ ] **Step 4: Verify** — CTA centered, ocean spacing, footer dark with links.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(landing): CTA final + footer + AOS init"
```

---

### Task 8: Final Review & Polish

- [ ] **Step 1: Open the file** and verify:
  - Layout matches spec on desktop (1920px, 1440px) and mobile (375px, 390px)
  - Button text is Carbone (`#1A1A1E`), not Avorio
  - All sections present in order
  - AOS animations work
  - Lucide icons render
  - Scroll is smooth

- [ ] **Step 2: Run a check** for any remaining "Modern Operator" or "Evergreen" references

```bash
Select-String -Path "web/landing page/landing.html" -Pattern "Modern Operator|Evergreen|MODERN" -SimpleMatch
```

Expected: no matches.

- [ ] **Step 3: Final commit** if any fixes needed
