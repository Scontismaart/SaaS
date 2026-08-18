"""
prompts.py
----------
Qui costruiamo il testo che l'agente riceve come istruzioni.
Tenerlo separato da responder_agent.py significa poter affinare
il tono/le regole senza toccare la logica CrewAI.

A/B test per tenant (roadmap task 12): PROMPT_VARIANTS contiene le
varianti (blocchi di istruzioni extra aggiunte in coda al system prompt);
GUARDRAIL_AB_VARIANTS attiva quelle con cui fare il test e
assegna_variante() distribuisce i tenant in modo deterministico (hash
dell'org), cosi' lo stesso locale vede sempre lo stesso stile e la
variante finisce nei metadata degli usage events per l'analisi.
"""

import hashlib
import os

from src.models.schemas import LINGUA_DEFAULT, MessaggioInput, ProfiloAttivita

GIRO_MAX = 5

PROMPT_VARIANTS: dict[str, str] = {
    # Comportamento attuale: nessuna istruzione extra.
    "control": "",
    # Variante sperimentale: risposte piu' brevi e dirette.
    "concise": (
        "\n\nSTILE RISPOSTE (variante 'concise'):\n"
        "Rispondi in modo molto conciso: massimo 2-3 frasi, nessun preambolo "
        "('Gentile cliente', 'La ringrazio per il messaggio'), vai dritta/o "
        "all'informazione utile. Se basta una frase, scrivi una frase sola."
    ),
}


def varianti_attive() -> list[str]:
    """Varianti del test in ordine stabile: 'control' sempre prima (ed
    sempre presente, e' il baseline); le altre come da env, scartando
    nomi non definiti in PROMPT_VARIANTS."""
    raw = os.getenv("GUARDRAIL_AB_VARIANTS", "control")
    scelte = [v.strip() for v in raw.split(",") if v.strip() in PROMPT_VARIANTS and v.strip()]
    if "control" not in scelte:
        scelte.insert(0, "control")
    return scelte


def assegna_variante(organization_id: str) -> str:
    """Assegnazione A/B deterministica per tenant: hash stabile dell'org,
    zero storage, zero drift tra chiamate. Con una sola variante attiva
    ('control') il comportamento resta quello di prima."""
    scelte = varianti_attive()
    if len(scelte) == 1:
        return scelte[0]
    digest = hashlib.sha256(str(organization_id).encode("utf-8")).digest()
    return scelte[digest[0] % len(scelte)]


def formatta_cronologia(scambi: list[tuple[str, str]]) -> str:
    """Trasforma gli ultimi N scambi in testo per il prompt."""
    if not scambi:
        return ""
    parti = ["Cronologia conversazione (dal più vecchio al più recente):"]
    for msg, risp in scambi[-GIRO_MAX:]:
        parti.append(f'Cliente: "{msg}"')
        parti.append(f'Assistente: "{risp}"')
    parti.append("---")
    return "\n".join(parti)


def costruisci_blocco_lingue(
    lingue_supportate: list[str] | None = None,
    lingua_default: str = LINGUA_DEFAULT,
    verticale: str | None = None,
) -> str:
    """Blocco LINGUE per il system prompt (task 14).

    Il rilevamento lingua e' delegato al LLM: nessuna libreria. Policy sulle
    lingue NON supportate: best-effort (rispondo comunque nella lingua del
    cliente) per tutti i verticali, ESCALATION a umano per
    studio_medico_dentista (un errore di traduzione in ambito clinico ha
    conseguenze diverse che in un ristorante). Con verticale=None la policy
    e' sempre best-effort: usato dalle recensioni, dove non ha senso
    "rifiutarsi" di abbozzare una risposta a un testo gia' pubblico.
    """
    lingue = lingue_supportate or [LINGUA_DEFAULT]
    if not lingua_default:
        lingua_default = LINGUA_DEFAULT
    blocco = (
        "\n\nLINGUE:\n"
        f"- Lingue supportate dall'attivita': {', '.join(lingue)}.\n"
        f"- Lingua di default: {lingua_default}.\n"
        "- Rileva la lingua del messaggio del cliente e rispondi nella STESSA "
        "lingua del cliente.\n"
        "- Se il messaggio e' molto breve o ambiguo e la lingua non e' chiara, "
        "usa la lingua di default.\n"
    )
    if verticale == "studio_medico_dentista":
        blocco += (
            "- Se il messaggio NON e' in una delle lingue supportate, NON rispondere "
            "nel merito: imposta richiede_umano=True e scrivi un breve messaggio di "
            "attesa nella lingua del cliente.\n"
        )
    else:
        blocco += (
            "- Se il messaggio e' in una lingua NON supportata, rispondi comunque "
            "nella lingua del cliente (best effort).\n"
        )
    return blocco


def costruisci_system_prompt(profilo: ProfiloAttivita, variante: str = "control") -> str:
    """Genera le istruzioni di ruolo per l'agente, basate sul profilo
    dell'attività (nome, tono, orari, regole di escalation). La variante
    A/B aggiunge un blocco di istruzioni in coda ('control': nessuna)."""

    note = "\n".join(f"- {nota}" for nota in profilo.note_speciali)
    servizi = "\n".join(f"- {s}" for s in profilo.servizi_principali)

    testo = f"""Sei l'assistente virtuale di "{profilo.nome}", un/a {profilo.tipo_attivita}.
Rispondi ai messaggi dei clienti (via WhatsApp, Instagram o altri canali di messaggistica) con questo tono: {profilo.tono}.

INFORMAZIONI SULL'ATTIVITÀ:
Orari: {profilo.orari}

Servizi principali:
{servizi}

REGOLE DI ESCALATION (fondamentali, da rispettare sempre):
{note}

COMPORTAMENTO RICHIESTO:
1. Se la richiesta rientra nelle informazioni che hai sopra e NON è tra i casi di
   escalation elencati, rispondi tu stesso in modo cordiale, breve e diretto.
2. Se la richiesta rientra in uno dei casi di escalation, NON improvvisare una
   risposta nel merito: imposta richiede_umano=True, scrivi comunque un breve
   messaggio di attesa gentile per il cliente (es. "Ti metto in contatto con
   qualcuno del nostro staff per questo, un attimo!") e spiega nel campo motivo
   perché va girato a un umano.
3. Se la richiesta è ambigua o fuori dal contesto dell'attività, imposta
   richiede_umano=True con motivo "fuori_scope".
4. Non inventare mai informazioni che non hai (es. prezzi esatti non forniti,
   disponibilità in tempo reale): se non sai, gira a un umano.

GESTIONE PRENOTAZIONI (campo "prenotazione" nello schema di output):
Quando il cliente chiede di prenotare (es. "vorrei prenotare per stasera",
"prenota per 4 persone venerdì alle 21"), imposta SEMPRE:
- categoria = "prenotazione"
- prenotazione.nome_cliente = il nome del cliente se fornito, altrimenti ""
- prenotazione.telefono = il telefono se fornito, altrimenti ""
- prenotazione.data = la data richiesta in formato YYYY-MM-DD. Risolvi sempre le date relative ("domani" → giorno dopo la data odierna, "dopodomani" → tra 2 giorni, "stasera" → oggi, "venerdì" → il prossimo venerdì rispetto alla data odierna, ecc.)
- prenotazione.ora = l'ora richiesta in formato HH:MM
- prenotazione.coperti = il numero di persone (numero intero)
- prenotazione.note = eventuali richieste speciali menzionate (allergie, festeggiamenti, ecc.)

Se la prenotazione ha dati sufficienti (almeno data, ora e coperti),
imposta richiede_umano=False e rispondi con una conferma gentile.
Se mancano dati essenziali, imposta richiede_umano=True e spiega cosa manca.
Le richieste per gruppi oltre 10 persone vanno SEMPRE escalate a umano.

Rispondi SOLO con i campi richiesti dallo schema strutturato, nessun testo extra."""
    testo += costruisci_blocco_lingue(
        profilo.lingue_supportate, profilo.lingua_default, profilo.verticale
    )
    extra = PROMPT_VARIANTS.get(variante, "")
    if extra:
        testo += extra
    return testo


def costruisci_user_prompt(messaggio: MessaggioInput) -> str:
    """Il messaggio del cliente così com'è, con la data odierna per risolvere date relative."""
    oggi = messaggio.timestamp.strftime("%Y-%m-%d")
    return (
        f"Data odierna: {oggi}\n"
        f"Messaggio ricevuto dal cliente (canale: {messaggio.canale.value}, "
        f"ore {messaggio.timestamp.strftime('%H:%M')}):\n\n"
        f'"{messaggio.testo}"'
    )