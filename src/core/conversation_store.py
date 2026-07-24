from collections import deque


class ConversationStore:
    def __init__(self, max_scambi: int = 10):
        self._store: dict[str, deque[tuple[str, str]]] = {}
        self._max = max_scambi

    def aggiungi(self, id_conv: str, msg_cliente: str, msg_bot: str) -> None:
        if id_conv not in self._store:
            self._store[id_conv] = deque(maxlen=self._max)
        self._store[id_conv].append((msg_cliente, msg_bot))

    def recupera_cronologia(self, id_conv: str) -> list[tuple[str, str]]:
        return list(self._store.get(id_conv, []))

    def cancella(self, id_conv: str) -> None:
        self._store.pop(id_conv, None)


store = ConversationStore()
