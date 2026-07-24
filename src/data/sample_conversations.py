from src.models.schemas import MessaggioInput, CanaleMessaggio

MESSAGGI_TEST = [
    MessaggioInput(
        testo="Buongiorno, siete aperti a pranzo oggi?",
    ),
    MessaggioInput(
        testo="Vorrei prenotare per 2 persone stasera alle 20:30",
    ),
    MessaggioInput(
        testo="Avete posti all'aperto domani sera?",
    ),
    MessaggioInput(
        testo="Mio figlio ha un'allergia alle noci, potete preparare qualcosa di sicuro?",
    ),
    MessaggioInput(
        testo="Il mese scorso sono stato da voi e il servizio è stato lentissimo, voglio parlare con il responsabile",
    ),
    MessaggioInput(
        testo="Quanto costa il menu degustazione?",
    ),
    MessaggioInput(
        testo="Siamo un gruppo di 15 persone per una festa di compleanno, possiamo organizzare?",
    ),
    MessaggioInput(
        testo="Fate consegne a domicilio?",
    ),
]
