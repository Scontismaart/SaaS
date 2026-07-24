from src.models.schemas import StatisticheReport


def costruisci_system_prompt_report() -> str:
    return (
        "Sei un analista business specializzato nell'analisi delle conversazioni "
        "tra un'attività commerciale e i suoi clienti.\n\n"
        "Ricevi le statistiche aggregate della giornata e alcuni messaggi di esempio "
        "per ogni categoria. Il tuo compito è produrre:\n\n"
        "1. **analisi_testuale**: un breve riepilogo narrativo (3-6 frasi) che racconta "
        "cosa è successo oggi: quante richieste, quali categorie hanno dominato, "
        "eventuali pattern interessanti. Scrivilo come se lo leggesse il titolare "
        "dell'attività — chiaro, concreto, nessun gergo tecnico.\n\n"
        "2. **suggerimenti**: 1-3 suggerimenti proattivi basati sui messaggi campione. "
        "Devono essere specifici e azionabili, non generici. Esempi:\n"
        '   - "3 clienti hanno chiesto informazioni sui posti all\'aperto: valuta di '
        'aggiungere una riga sul giardino nel menu online o nei messaggi di risposta '
        'automatica."\n'
        '   - "Un cliente ha chiesto un piatto senza glutine: se non lo hai già, '
        "potresti aggiungere un'opzione senza glutine visibile nel menu.\"\n"
        '   - "Ricevute 2 richieste per eventi privati: valuta di creare una pagina '
        'dedicata sul sito per raccogliere queste richieste in modo strutturato."\n\n'
        "REGOLE:\n"
        "- Non inventare dati. Usa solo le statistiche e gli esempi forniti.\n"
        "- Se oggi ci sono stati meno di 3 messaggi totali, scrivi un'analisi breve "
        "e non forzare suggerimenti (lista vuota va bene).\n"
        "- Se non ci sono pattern degni di nota, dillo onestamente.\n"
        "- Tono: professionale, concreto, leggermente informale — come un collega "
        "che riassume la giornata a un altro collega."
    )


def costruisci_user_prompt_report(statistiche: StatisticheReport) -> str:
    parti = [
        f"Data: {statistiche.periodo}",
        f"Totale messaggi: {statistiche.totale_messaggi}",
        f"Gestiti dall'assistente AI: {statistiche.gestiti_da_ai}",
        f"Girati a un operatore umano: {statistiche.girati_a_umano}",
        "",
        "Distribuzione per categoria:",
    ]

    for cat, count in sorted(
        statistiche.categorie.items(), key=lambda x: -x[1]
    ):
        parti.append(f"  - {cat}: {count}")
        esempi = statistiche.esempi_per_categoria.get(cat, [])
        for i, es in enumerate(esempi, 1):
            parti.append(f'    Esempio {i}: "{es}"')

    parti.append("")
    parti.append(
        "Analizza i dati qui sopra e produci analisi_testuale e suggerimenti "
        "secondo le regole che ti sono state date."
    )

    return "\n".join(parti)
