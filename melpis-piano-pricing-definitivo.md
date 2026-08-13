# Melpis — Piano di Abbonamento e Pricing Definitivo

## Decisione di fondo

**Modello: Free-trial, non Freemium.** Da ottobre 2026 Meta fa pagare anche i messaggi di servizio WhatsApp — un piano gratuito permanente sarebbe un costo variabile infinito, non uno sconto una tantum. Un trial a tempo/conversazioni limitate dà lo stesso effetto "provo senza rischio" sul conversion rate, con un tetto di spesa noto in anticipo.

**Value metric: conversazioni AI gestite al mese.** Stesso concetto su cui fattura Meta (finestra 24h) — intuitivo per chiunque abbia già usato WhatsApp Business, scala col valore reale percepito (più conversazioni gestite = più tempo risparmiato = più prenotazioni salvate), difficile da aggirare.

---

## 1. Buyer Personas

**Marco, il ristoratore oberato** (persona primaria) — 1-2 locali, risponde lui su WhatsApp tra un turno e l'altro, perde prenotazioni quando è impegnato, risponde alle recensioni con settimane di ritardo. Decide in 10 minuti guardando prezzo e tempo risparmiato.

**Giulia, titolare di centro estetico/parrucchiere** — volume prenotazioni alto e ricorrente, le recensioni Google sono il suo canale di acquisizione principale. Disposta a pagare di più per le recensioni automatiche rispetto a Marco — per lei è marketing, non solo comodità.

**Il gestore multi-location** (persona Business) — 3-10 punti vendita, vuole dashboard unica, utenti multipli con permessi, knowledge base perché ogni location ha FAQ diverse. Decide in modo razionale, confronta alternative, chiede demo.

---

## 2. Competitor — nota di trasparenza

Ricerca su **Polsia.com** non ha prodotto risultati verificabili — nessun sito o dato di prodotto/prezzo confermato. Non vengono quindi riportati numeri su questo competitor specifico; se viene fornito lo spelling/URL corretto, l'analisi va rifatta.

Dal mercato italiano dell'automazione WhatsApp Business API per attività locali verificato via ricerca (es. fornitori come PS Company): pattern comune = pacchetti a scaglioni per volume messaggi, spesso a preventivo/"contattaci" più che con prezzi pubblici — il mercato compete su fiducia/demo, non sul prezzo in vetrina.

**Posizionamento Melpis**: limiti pubblici in numero di conversazioni (trasparenza, non "contattaci"), recensioni automatiche già nel tier di mezzo (non solo nel top come spesso fanno i tool generalisti).

---

## 3. Tabella dei piani

| | **Essenziale** | **Crescita** ⭐ consigliato | **Scala** |
|---|---|---|---|
| Prezzo mensile | €49/mese | €99/mese | €199/mese |
| Prezzo annuale | €470/anno (€39,17/mese — risparmi €118) | €950/anno (€79,17/mese — risparmi €238) | €1.910/anno (€159,17/mese — risparmi €478) |
| Conversazioni AI/mese | 300 | 1.200 | 5.000 (fair use, oltre: contattaci) |
| Location / numeri WhatsApp | 1 | 1 | fino a 5 |
| Utenti | 1 | 3 | illimitati |
| Prenotazioni automatiche | ✅ | ✅ | ✅ |
| Recensioni automatiche | ❌ | ✅ | ✅ |
| **Scheda Attività** (orari, menu, servizi — iniettata nel prompt AI) | ✅ | ✅ | ✅ |
| **Knowledge base / RAG** (documenti, PDF, listini complessi) | ❌ | ❌ | ✅ |
| Dashboard multi-location | ❌ | ❌ | ✅ |

**Nota importante sulla Scheda Attività vs RAG** (correzione fatta in sessione): sono due cose diverse. La Scheda Attività (orari, menu, servizi — dati strutturati semplici iniettati direttamente nel prompt) è il minimo indispensabile perché l'AI risponda in modo accurato — va **inclusa in tutti i piani**, altrimenti Essenziale e Crescita non funzionerebbero sulle domande più comuni. Il RAG vero (ricerca semantica su documenti/PDF/menu stagionali lunghi) resta un upsell legittimo per chi ha volumi di documenti complessi, non per "a che ora chiudete il martedì".

Logica psicologica applicata: **anchoring** (Scala come riferimento in alto), **decoy naturale** su Essenziale (300 conversazioni riflettono il vero break-even di valore, non manipolazione), **charm pricing** sul mensile (49/99/199), **round pricing** sull'annuale scontato (comunica che lo sconto è reale).

---

## 4. Upgrade Triggers e Retention

**80% del limite**: notifica in-app + messaggio WhatsApp automatico al gestore ("Hai usato l'80% delle conversazioni di questo mese"). Nessun blocco — consapevolezza in anticipo, proposta quando il valore è già evidente.

**100% del limite — soft cap, mai hard cap.** Bloccare le risposte WhatsApp di un ristorante a metà servizio causa churn immediato: è il canale con cui il cliente del cliente sta cercando di prenotare *adesso*. Le conversazioni oltre soglia continuano, ma in overage (es. €0,08/conversazione extra fatturata a fine mese). Hard cap solo su feature non critiche per l'operatività quotidiana (RAG, analytics avanzati).

---

## 5. Pricing Page Copy

**Headline**: Rispondi a ogni cliente, gestisci ogni prenotazione, senza restare incollato al telefono.

**Sub-headline**: Melpis risponde su WhatsApp, gestisce le prenotazioni e le recensioni al posto tuo — tu torni a fare il tuo lavoro.

**CTA per tier**:
- Essenziale → "Inizia gratis, nessuna carta richiesta"
- Crescita → "Prova Crescita — il piano scelto dalla maggior parte delle attività come la tua"
- Scala → "Parliamo del tuo gruppo — demo in 20 minuti"

**FAQ**:

1. **Cosa succede se supero le conversazioni incluse nel mio piano?**
   Niente si blocca. Continuiamo a rispondere ai tuoi clienti anche oltre il limite, a un piccolo costo aggiuntivo per conversazione.

2. **L'AI risponde sempre bene, o rischio di dare informazioni sbagliate ai miei clienti?**
   Puoi rivedere e approvare le risposte alle recensioni prima che vengano pubblicate, e imposti tu i confini di cosa l'AI può dire.

3. **Posso cambiare piano o cancellare in qualsiasi momento?**
   Sì, in un click dalla dashboard, nessun vincolo annuale se scegli il mensile. Se passi all'annuale e cambi idea, rimborso della parte non utilizzata entro i primi 30 giorni.

---

## 6. Trial (non piano free permanente)

14 giorni **o** 150 conversazioni (quel che arriva prima), senza carta di credito richiesta. Watermark discreto "Powered by Melpis" nei messaggi durante il trial. Anti-abuso: verifica email obbligatoria + Partita IVA in onboarding (un numero WhatsApp Business verificato è già una barriera naturale forte contro il multi-account).

Alla scadenza: org in sola lettura (nessun nuovo messaggio processato, dati conservati), CTA per aggiungere pagamento.

---

## 7. ADR — subscription.deleted / degrado piano (B4)

Nessun piano "free" a cui degradare. Quando un abbonamento pagante viene cancellato, l'org va in **sola lettura** — stesso stato/stessa logica dello scadere del trial (punto 6). Un solo meccanismo "org sospesa", due trigger diversi (trial scaduto / abbonamento cancellato). Non serve costruire due sistemi separati.
