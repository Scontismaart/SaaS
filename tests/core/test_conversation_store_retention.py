from src.core.conversation_store import ConversationStore


def test_conversation_history_expires_after_idle_ttl(monkeypatch):
    now = [100.0]
    monkeypatch.setattr("src.core.conversation_store.time.monotonic", lambda: now[0])
    store = ConversationStore(ttl_seconds=10)
    store.aggiungi("tenant:session", "Ciao", "Salve")

    now[0] = 109.0
    assert store.recupera_cronologia("tenant:session") == [("Ciao", "Salve")]

    now[0] = 120.0
    assert store.recupera_cronologia("tenant:session") == []
    assert "tenant:session" not in store._tentativi_prenotazione


def test_conversation_history_has_a_hard_memory_bound(monkeypatch):
    now = [1.0]
    monkeypatch.setattr("src.core.conversation_store.time.monotonic", lambda: now[0])
    store = ConversationStore(max_conversations=1)
    store.aggiungi("first", "Ciao", "Salve")
    now[0] += 1
    store.aggiungi("second", "Hello", "Hi")

    assert store.recupera_cronologia("first") == []
    assert store.recupera_cronologia("second") == [("Hello", "Hi")]
