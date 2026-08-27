from collections import deque


class ConversationStore:
    def __init__(self, max_scambi: int = 10):
        self._store: dict[str, deque[tuple[str, str]]] = {}
        self._max = max_scambi
        # Contatore tentativi raccolta dati prenotazione per conversazione.
        # Conta solo i giri in cui il cliente NON fornisce nessun dato nuovo
        # dopo una richiesta esplicita dell'assistente. Un dato ambiguo
        # (es. "verso sera") NON conta come tentativo fallito — conta solo
        # l'assenza totale del dato richiesto.
        self._tentativi_prenotazione: dict[str, int] = {}

    def aggiungi(self, id_conv: str, msg_cliente: str, msg_bot: str) -> None:
        if id_conv not in self._store:
            self._store[id_conv] = deque(maxlen=self._max)
        self._store[id_conv].append((msg_cliente, msg_bot))

    def recupera_cronologia(self, id_conv: str) -> list[tuple[str, str]]:
        return list(self._store.get(id_conv, []))

    def cancella(self, id_conv: str) -> None:
        self._store.pop(id_conv, None)
        self._tentativi_prenotazione.pop(id_conv, None)

    def incrementa_tentativi_prenotazione(self, id_conv: str) -> int:
        """Incrementa il contatore di tentativi falliti e restituisce il nuovo valore."""
        self._tentativi_prenotazione[id_conv] = self._tentativi_prenotazione.get(id_conv, 0) + 1
        return self._tentativi_prenotazione[id_conv]

    def resetta_tentativi_prenotazione(self, id_conv: str) -> None:
        """Reset del contatore (il cliente ha fornito un dato nuovo o la prenotazione è completata)."""
        self._tentativi_prenotazione.pop(id_conv, None)

    def tentativi_prenotazione(self, id_conv: str) -> int:
        """Restituisce il numero corrente di tentativi falliti."""
        return self._tentativi_prenotazione.get(id_conv, 0)


store = ConversationStore()
