"""Core AI Receptionist - Application Layer.

Fornisce il ConversationOrchestrator unificato per coordinare il workflow AI
di gestione messaggi (RAG, FAQ cache, semaforo disponibilità, LLM, guardrails,
vertical strategies e creazione prenotazioni) in modo agnostico rispetto al canale.
"""
from src.core.receptionist.models import OrchestrationInput, OrchestrationOutput

__all__ = ["OrchestrationInput", "OrchestrationOutput"]
