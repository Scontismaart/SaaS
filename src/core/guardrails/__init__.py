"""Guardrails di qualita' risposta (task 12 della roadmap).

Pacchetto che raccoglie i controlli che stanno attorno al responder:
- validator: validazione deterministica post-LLM dell'output
- intent_classifier: classificatore di intent pre-responder (modello economico)
- faq_cache: cache semantica delle risposte FAQ piu' frequenti
"""
