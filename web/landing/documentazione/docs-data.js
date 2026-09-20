/**
 * Melpis Documentation — Structured Content Index & Registry
 * Used for instant client-side search, category navigation, and breadcrumbs.
 * Strictly verified against actual code and features in the Melpis repository.
 */
window.MELPIS_DOCS_DATA = {
  categories: [
    {
      id: "inizia-da-qui",
      title: "Inizia da qui",
      description: "Cos'è Melpis, architettura essenziale, wizard di onboarding in 7 passi e checklist pre-lancio.",
      icon: "🚀",
      count: 3
    },
    {
      id: "integrazioni",
      title: "Canali e Integrazioni",
      description: "WhatsApp Business, Instagram Direct, Google Calendar, Google Recensioni, PMS e Airtable.",
      icon: "🔌",
      count: 6
    },
    {
      id: "configurazione-ai",
      title: "Configurazione AI e Conoscenza",
      description: "Personalità, tono di voce, orari, caricamento documenti RAG, listino prezzi e cache FAQ.",
      icon: "🧠",
      count: 4
    },
    {
      id: "inbox-e-messaggi",
      title: "Shared Inbox e Intervento Umano",
      description: "Presa in carico ticket (Claim), risposta manuale su WhatsApp/Instagram, escalation e SLA.",
      icon: "💬",
      count: 2
    },
    {
      id: "prenotazioni",
      title: "Prenotazioni e Appuntamenti",
      description: "Disponibilità slot, semaforo orario, capienze, creazione appuntamenti e sync calendario.",
      icon: "📅",
      count: 1
    },
    {
      id: "account-e-piani",
      title: "Account, Team e Piani",
      description: "Gestione collaboratori (Owner, Manager, Staff), piani Essenziale, Crescita, Scala e Stripe.",
      icon: "👥",
      count: 2
    },
    {
      id: "sicurezza-e-privacy",
      title: "Sicurezza, Privacy e GDPR",
      description: "Conformità GDPR, DPA, retention 60-90 giorni, gestione opt-out e diritto all'oblio.",
      icon: "🛡️",
      count: 1
    },
    {
      id: "risoluzione-problemi",
      title: "Troubleshooting e Architettura",
      description: "Diagnosi token scaduti, errori Meta, webhook, rate limit e architettura tecnica a worker.",
      icon: "🔧",
      count: 2
    }
  ],
  articles: [
    {
      slug: "cos-e-melpis",
      title: "Cos'è Melpis e come funziona l'assistente AI",
      description: "Panoramica dell'architettura: ricezione messaggi, recupero documenti, zero allucinazioni e guardrail deterministici.",
      category: "inizia-da-qui",
      categoryName: "Inizia da qui",
      path: "/documentazione/",
      difficulty: "Base",
      time: "4 min",
      updatedAt: "Settembre 2026",
      popular: true,
      keywords: ["introduzione", "cos'è", "come funziona", "architettura", "panoramica", "guardrails", "zero allucinazioni", "rag"]
    },
    {
      slug: "guida-onboarding",
      title: "Guida passo-passo al Wizard di configurazione",
      description: "Configura il tuo assistente in 7 passaggi: settore, orari, servizi, multilingua, escalation, WhatsApp e test.",
      category: "inizia-da-qui",
      categoryName: "Inizia da qui",
      path: "/documentazione/inizia-da-qui/guida-onboarding/",
      difficulty: "Base",
      time: "6 min",
      updatedAt: "Settembre 2026",
      popular: true,
      keywords: ["onboarding", "wizard", "configurazione iniziale", "settori", "orari", "primi passi", "registrazione"]
    },
    {
      slug: "checklist-pre-lancio",
      title: "Checklist di verifica prima del lancio",
      description: "Verifica credenziali Meta, test nel simulatore, fuso orario, sincronizzazione calendario e prova dal vivo.",
      category: "inizia-da-qui",
      categoryName: "Inizia da qui",
      path: "/documentazione/inizia-da-qui/checklist-pre-lancio/",
      difficulty: "Intermedio",
      time: "5 min",
      updatedAt: "Settembre 2026",
      popular: false,
      keywords: ["checklist", "lancio", "collaudo", "verifica", "produzione", "pre-lancio", "test dal vivo"]
    },
    {
      slug: "collegare-whatsapp",
      title: "Come collegare WhatsApp Business (Meta Cloud API)",
      description: "Guida completa alla configurazione di Phone Number ID, WABA ID, Access Token permanente e Webhook ufficiale.",
      category: "integrazioni",
      categoryName: "Canali e Integrazioni",
      path: "/documentazione/integrazioni/collegare-whatsapp/",
      difficulty: "Intermedio",
      time: "7 min",
      updatedAt: "Settembre 2026",
      popular: true,
      keywords: ["whatsapp", "meta", "cloud api", "waba id", "phone number id", "access token", "webhook", "meta developer"]
    },
    {
      slug: "collegare-instagram",
      title: "Come collegare Instagram Direct (DM)",
      description: "Ricevi e rispondi automaticamente ai messaggi diretti Instagram collegando la tua Pagina Facebook professionale.",
      category: "integrazioni",
      categoryName: "Canali e Integrazioni",
      path: "/documentazione/integrazioni/collegare-instagram/",
      difficulty: "Intermedio",
      time: "6 min",
      updatedAt: "Settembre 2026",
      popular: false,
      keywords: ["instagram", "dm", "direct", "meta", "facebook page", "social", "messaggi instagram"]
    },
    {
      slug: "collegare-google-calendar",
      title: "Come collegare e sincronizzare Google Calendar",
      description: "Sincronizza in tempo reale le prenotazioni dei clienti con la tua agenda Google Calendar personale o aziendale.",
      category: "integrazioni",
      categoryName: "Canali e Integrazioni",
      path: "/documentazione/integrazioni/collegare-google-calendar/",
      difficulty: "Base",
      time: "5 min",
      updatedAt: "Settembre 2026",
      popular: true,
      keywords: ["calendar", "google calendar", "agenda", "sincronizzazione", "appuntamenti", "oauth", "disponibilità"]
    },
    {
      slug: "collegare-google-recensioni",
      title: "Come collegare Google Recensioni (Business Profile)",
      description: "Scarica automaticamente le recensioni Google, genera risposte professionali con l'AI e approvale con un click.",
      category: "integrazioni",
      categoryName: "Canali e Integrazioni",
      path: "/documentazione/integrazioni/collegare-google-recensioni/",
      difficulty: "Intermedio",
      time: "5 min",
      updatedAt: "Settembre 2026",
      popular: false,
      keywords: ["recensioni", "google reviews", "business profile", "gmb", "sentiment", "reputazione", "risposte automatiche"]
    },
    {
      slug: "gestionali-e-pms",
      title: "Collegamento Gestionali Esterni e PMS",
      description: "Integrazione con SimplyBook.me, Apaleo, Cal.com e modalità Authoritative, Shadow o Local-only.",
      category: "integrazioni",
      categoryName: "Canali e Integrazioni",
      path: "/documentazione/integrazioni/gestionali-e-pms/",
      difficulty: "Avanzato",
      time: "8 min",
      updatedAt: "Settembre 2026",
      popular: false,
      keywords: ["pms", "gestionale", "simplybook", "apaleo", "cal.com", "wubook", "zak", "modalità authoritative", "shadow"]
    },
    {
      slug: "integrazione-airtable",
      title: "Collegamento Airtable e vincolo di policy sanitaria",
      description: "Sincronizza lead e contatti con la tua Base Airtable. Scopri le regole di sicurezza GDPR per il settore medico.",
      category: "integrazioni",
      categoryName: "Canali e Integrazioni",
      path: "/documentazione/integrazioni/integrazione-airtable/",
      difficulty: "Intermedio",
      time: "5 min",
      updatedAt: "Settembre 2026",
      popular: false,
      keywords: ["airtable", "pat", "personal access token", "database", "crm", "sanità", "gdpr", "divieto medico"]
    },
    {
      slug: "personalizzazione-assistente",
      title: "Personalità, tono di voce e regole operative dell'AI",
      description: "Imposta il nome dell'assistente, lo stile comunicativo, gli orari di apertura e i limiti di lunghezza dei messaggi.",
      category: "configurazione-ai",
      categoryName: "Configurazione AI e Conoscenza",
      path: "/documentazione/configurazione-ai/personalizzazione-assistente/",
      difficulty: "Base",
      time: "5 min",
      updatedAt: "Settembre 2026",
      popular: true,
      keywords: ["personalità", "tono di voce", "stile", "regole", "prompt", "configurazione ai", "orari"]
    },
    {
      slug: "documenti-e-conoscenza",
      title: "Caricamento Documenti, Menù e Riconoscimento OCR",
      description: "Carica PDF, TXT, CSV o pagine web: indicizzazione semantica automatica con pgvector e OCR per PDF scansionati.",
      category: "configurazione-ai",
      categoryName: "Configurazione AI e Conoscenza",
      path: "/documentazione/configurazione-ai/documenti-e-conoscenza/",
      difficulty: "Intermedio",
      time: "6 min",
      updatedAt: "Settembre 2026",
      popular: false,
      keywords: ["documenti", "pdf", "menù", "conoscenza", "ocr", "indicizzazione", "pgvector", "chunking", "rag"]
    },
    {
      slug: "listino-servizi-e-prezzi",
      title: "Listino Servizi Strutturato e Rilevamento Conflitti",
      description: "Definisci servizi, durate e prezzi ufficiali. Il motore di rilevamento conflitti impedisce all'AI di dare cifre discordanti.",
      category: "configurazione-ai",
      categoryName: "Configurazione AI e Conoscenza",
      path: "/documentazione/configurazione-ai/listino-servizi-e-prezzi/",
      difficulty: "Intermedio",
      time: "5 min",
      updatedAt: "Settembre 2026",
      popular: false,
      keywords: ["listino", "prezzi", "servizi", "durata", "conflitti prezzo", "priorità dati", "grounding"]
    },
    {
      slug: "faq-e-cache-semantica",
      title: "FAQ Aziendali e Cache Semantica a Zero Token",
      description: "Crea risposte ufficiali immediate alle domande frequenti: risparmia token e azzera i tempi di attesa per i clienti.",
      category: "configurazione-ai",
      categoryName: "Configurazione AI e Conoscenza",
      path: "/documentazione/configurazione-ai/faq-e-cache-semantica/",
      difficulty: "Intermedio",
      time: "4 min",
      updatedAt: "Settembre 2026",
      popular: false,
      keywords: ["faq", "domande frequenti", "cache semantica", "zero token", "risposta istantanea", "risparmio costi"]
    },
    {
      slug: "shared-inbox-e-claim",
      title: "Shared Inbox, Presa in Carico e Risposta Manuale",
      description: "Gestisci tutte le chat WhatsApp e Instagram da una sola schermata: claim dei ticket, risposta in tempo reale e storico.",
      category: "inbox-e-messaggi",
      categoryName: "Shared Inbox e Intervento Umano",
      path: "/documentazione/inbox-e-messaggi/shared-inbox-e-claim/",
      difficulty: "Base",
      time: "6 min",
      updatedAt: "Settembre 2026",
      popular: true,
      keywords: ["inbox", "shared inbox", "claim", "operatore umano", "hitl", "risposta manuale", "ticket"]
    },
    {
      slug: "regole-escalation-e-sla",
      title: "Regole di Escalation Umana, Notifiche e SLA",
      description: "Come funziona il passaggio automatico dall'AI all'operatore umano in caso di richieste complesse o lamentele.",
      category: "inbox-e-messaggi",
      categoryName: "Shared Inbox e Intervento Umano",
      path: "/documentazione/inbox-e-messaggi/regole-escalation-e-sla/",
      difficulty: "Intermedio",
      time: "5 min",
      updatedAt: "Settembre 2026",
      popular: false,
      keywords: ["escalation", "sla", "notifiche", "emergenza", "passaggio umano", "lamentele", "pending staff"]
    },
    {
      slug: "gestione-prenotazioni",
      title: "Gestione Prenotazioni, Semaforo Slot e No-Show",
      description: "Visualizza gli appuntamenti, regola le capienze orarie, gestisci modifiche, conferme e contrassegno dei no-show.",
      category: "prenotazioni",
      categoryName: "Prenotazioni e Appuntamenti",
      path: "/documentazione/prenotazioni/gestione-prenotazioni/",
      difficulty: "Base",
      time: "6 min",
      updatedAt: "Settembre 2026",
      popular: true,
      keywords: ["prenotazioni", "appuntamenti", "semaforo", "capienze", "no-show", "tavoli", "poltrone"]
    },
    {
      slug: "team-e-ruoli",
      title: "Gestione Team, Collaboratori e Permessi (RBAC)",
      description: "Invita i tuoi collaboratori e assegna i ruoli corretti: Owner, Manager e Staff, con limiti utenti basati sul piano.",
      category: "account-e-piani",
      categoryName: "Account, Team e Piani",
      path: "/documentazione/account-e-piani/team-e-ruoli/",
      difficulty: "Base",
      time: "4 min",
      updatedAt: "Settembre 2026",
      popular: false,
      keywords: ["team", "collaboratori", "ruoli", "owner", "manager", "staff", "permessi", "invito colleghi"]
    },
    {
      slug: "piani-e-fatturazione",
      title: "Piani, Quote Messaggi e Gestione Stripe Portal",
      description: "Dettaglio dei piani Essenziale, Crescita e Scala. Modifica o disdici tramite Stripe; ricevuta immediata e fattura fiscale su richiesta.",
      category: "account-e-piani",
      categoryName: "Account, Team e Piani",
      path: "/documentazione/account-e-piani/piani-e-fatturazione/",
      difficulty: "Base",
      time: "5 min",
      updatedAt: "Settembre 2026",
      popular: true,
      keywords: ["piani", "prezzi", "stripe", "fatturazione", "upgrade", "disdetta", "quote messaggi", "crediti"]
    },
    {
      slug: "gdpr-privacy-e-dpa",
      title: "Privacy, GDPR, DPA e Conservazione Dati",
      description: "Tutto sulla protezione dei dati: accordo DPA, retention 60-90 giorni, gestione opt-out e diritto alla cancellazione.",
      category: "sicurezza-e-privacy",
      categoryName: "Sicurezza, Privacy e GDPR",
      path: "/documentazione/sicurezza-e-privacy/gdpr-privacy-e-dpa/",
      difficulty: "Intermedio",
      time: "6 min",
      updatedAt: "Settembre 2026",
      popular: false,
      keywords: ["gdpr", "privacy", "dpa", "retention", "conservazione dati", "cancellazione", "opt-out", "stop"]
    },
    {
      slug: "guida-troubleshooting",
      title: "Risoluzione Problemi e Diagnosi Errori Comuni",
      description: "Cosa fare se il bot non risponde, se il token Meta scade, se il webhook fallisce o se Google Calendar si disconnette.",
      category: "risoluzione-problemi",
      categoryName: "Troubleshooting e Architettura",
      path: "/documentazione/risoluzione-problemi/guida-troubleshooting/",
      difficulty: "Intermedio",
      time: "7 min",
      updatedAt: "Settembre 2026",
      popular: true,
      keywords: ["troubleshooting", "errori", "token scaduto", "webhook non risponde", "problemi", "diagnosi", "supporto"]
    },
    {
      slug: "architettura-tecnica",
      title: "Architettura Tecnica: Webhook, Worker e Guardrail",
      description: "Approfondimento ingegneristico: modello asincrono, transazioni SKIP LOCKED, idempotenza e pipeline di sicurezza.",
      category: "risoluzione-problemi",
      categoryName: "Troubleshooting e Architettura",
      path: "/documentazione/risoluzione-problemi/architettura-tecnica/",
      difficulty: "Avanzato",
      time: "8 min",
      updatedAt: "Settembre 2026",
      popular: false,
      keywords: ["architettura", "tecnico", "worker", "inbound processor", "skip locked", "idempotenza", "fastapi", "pgvector"]
    }
  ]
};
