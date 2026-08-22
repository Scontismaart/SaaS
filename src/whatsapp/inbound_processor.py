import asyncio
import json
import logging
import uuid

from pydantic import ValidationError

from src.agents.prompts import assegna_variante
from src.core.billing.suspension import is_org_suspended
from src.core.bookings import SlotPienoError
from src.core.crew_runner import genera_risposta_async
from src.core.documenti.rag_context import recupera_contesto_documenti
from src.core.guardrails import faq_cache
from src.core.guardrails.feedback import rileva_feedback_emoji
from src.core.guardrails.intent_classifier import classifica_intent
from src.core.guardrails.validator import applica_guardrail, valida_risposta
from src.core.llm_config import LLMRouteRequest, budget_ratio_from_billing, route_llm
from src.core.notifications.email_service import enqueue_escalation
from src.core.security_logger import security_audit
from src.models.schemas import (
    CanaleMessaggio,
    LINGUA_DEFAULT,
    MessaggioInput,
    ProfiloAttivita,
    WhatsAppBusinessProfile,
)
from src.whatsapp.config import AppConfig, load_tenant_config

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 30

# Messaggio neutro per il cliente finale quando l'org e' sospesa: nessuna
# menzione di abbonamenti/fatturazione (esporrebbe lo stato di billing del
# locale a un cliente casuale). La notifica vera va al gestore via email.
ORG_SUSPENDED_REPLY = "Grazie per averci scritto, ti risponderemo al piu' presto."

DISCLOSURE_TEXT = (
    "Ciao! Sono l'assistente automatico di {nome}, un sistema di intelligenza "
    "artificiale. Scrivi OPERATORE se vuoi parlare con una persona."
)

HUMAN_WAIT_REPLY = "Ti passo una persona dello staff, un attimo!"


def _profile_from_dict(raw: dict | None, fallback_name: str = "Attivita") -> ProfiloAttivita:
    raw = raw or {}
    try:
        validated = WhatsAppBusinessProfile.model_validate(raw)
    except ValidationError as e:
        logger.error("business_profile validation failed", extra={
            "errors": e.errors(),
            "raw": raw,
        })
        validated = WhatsAppBusinessProfile()
    return ProfiloAttivita(
        nome=validated.nome or fallback_name,
        tipo_attivita=validated.tipo_attivita or "attivita commerciale",
        tono=validated.tono or "cordiale e professionale",
        orari=validated.orari or "",
        servizi_principali=validated.servizi_principali or [],
        note_speciali=validated.note_speciali or [],
        lingue_supportate=validated.lingue_supportate or [LINGUA_DEFAULT],
        lingua_default=validated.lingua_default or LINGUA_DEFAULT,
        verticale=validated.verticale,
    )


async def decorate_with_disclosure(org_id: str, from_number: str, testo: str, repo,
                                   nome_attivita: str = "Attivita") -> str:
    """Prepende la disclosure AI al primo messaggio automatico per quel contatto."""
    contact = await repo.get_or_create_contact(org_id, from_number)
    sent = await repo.mark_ai_disclosure_sent(contact["id"], org_id)
    if not sent:
        return testo
    return DISCLOSURE_TEXT.format(nome=nome_attivita) + "\n\n" + testo


class InboundProcessor:
    def __init__(self, app_config: AppConfig, repo, service, booking_service=None):
        self.app_config = app_config
        self.repo = repo
        self.service = service
        self.booking_service = booking_service

    async def process_next_batch(self):
        await self.repo.reap_stale_claims()
        messages = await self.repo.claim_inbound_messages(limit=10)
        for msg in messages:
            try:
                await self._process_one(msg)
            except Exception as e:
                logger.error("Error processing message %s: %s", msg["id"], e)

    async def _heartbeat_loop(self, msg_id, organization_id):
        try:
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                await self.repo.update_heartbeat(msg_id, organization_id)
        except asyncio.CancelledError:
            pass

    async def _process_one(self, msg: dict):
        org_id = msg["organization_id"]
        text = msg.get("content_text", "")
        content = msg.get("content", {})
        canale = msg.get("canale") or "whatsapp"
        
        claim_result = await self.repo.claim_message_and_check_quota(msg["id"], org_id)
        if claim_result.get("status") == "not_found":
            return
        if claim_result.get("status") == "already_sent":
            return
            
        if claim_result.get("status") == "currently_processing":
            logger.info("Message %s is currently being processed by another worker. Yielding.", msg["id"])
            return
        if claim_result.get("status") == "quota_exceeded":
            tenant_config = await load_tenant_config(org_id, self.app_config, self.repo)
            try:
                res = await self._send_ai_reply(
                    org_id, msg, content, tenant_config, 
                    "Stiamo ricevendo troppe richieste, attendi l'operatore.", 
                    handling_type="quota_exceeded"
                )
                meta_id = (res.get("wam_id") or f"meta-{msg['id']}") if isinstance(res, dict) else f"meta-{msg['id']}"
                conv = await self.repo.escalate_to_human(str(msg["conversation_id"]), org_id)
                if conv:
                    enqueue_escalation(
                        org_id=str(org_id),
                        conversation_id=str(msg["conversation_id"]),
                        contact_name=content.get("from", "cliente"),
                        pool=self.repo.pool,
                    )
                await self._finalize_message(msg["id"], handling_type="quota_exceeded", meta_message_id=meta_id, organization_id=org_id)
            except Exception as e:
                logger.error("Quota exceeded notification send failed for %s: %s", msg["id"], e)
            return

        opt_out = await self.service.check_opt_out(text)
        if opt_out["is_opt_out"]:
            from_number = content.get("from", "")
            contact = await self.repo.get_or_create_contact(org_id, from_number)
            await self.repo.record_consent_event(
                contact_id=contact["id"],
                event_type="opt_out",
                method="keyword_match",
                triggering_message_id=msg["id"],
                matched_text=text,
                organization_id=org_id,
            )
            security_audit("consent_opt_out", contact_id=str(contact["id"]), organization_id=str(org_id))
            # Il percorso di opt-out non ha side-effect esterni verso Meta (fail-closed opt-out).
            # La persistenza del consenso e l'audit log sono transazionalmente completati nel DB locale.
            # È quindi sicuro finalizzare/marcare subito il messaggio come handled ('opt_out').
            await self._finalize_message(msg["id"], handling_type="opt_out", organization_id=org_id)
            return

        wants_human = await self.service.check_human_request(text)
        if wants_human:
            from_number = content.get("from", "")
            tenant_config = await load_tenant_config(org_id, self.app_config, self.repo)
            try:
                res = await self._send_ai_reply(org_id, msg, content, tenant_config, HUMAN_WAIT_REPLY, handling_type="automation")
                meta_id = (res.get("wam_id") or f"meta-{msg['id']}") if isinstance(res, dict) else f"meta-{msg['id']}"
                conv = await self.repo.escalate_to_human(str(msg["conversation_id"]), org_id)
                if conv:
                    enqueue_escalation(
                        org_id=str(org_id),
                        conversation_id=str(msg["conversation_id"]),
                        contact_name=from_number or "cliente",
                        pool=self.repo.pool,
                    )
                await self._finalize_message(msg["id"], handling_type="escalated", meta_message_id=meta_id, organization_id=org_id)
            except Exception as e:
                logger.error("Human request notification send failed for %s: %s", msg["id"], e)
            return

        feedback_emoji = rileva_feedback_emoji(text)
        if feedback_emoji:
            await self._handle_feedback_emoji(org_id, msg, feedback_emoji)
            return

        if self.booking_service:
            booking_reply = await self.booking_service.handle_reminder_reply(
                org_id, content.get("from", ""), text
            )
            if booking_reply:
                # Booking reminder reply invia la risposta internamente via booking_service._send_whatsapp;
                # la finalizzazione avviene qui una volta completata l'elaborazione.
                await self._finalize_message(msg["id"], handling_type="automation", organization_id=org_id)
                return

        state = await self.repo.get_org_subscription_state(org_id)
        if state and is_org_suspended(state.get("subscription_status"), state.get("trial_end")):
            logger.warning("org_id=%s message_id=%s event=org_suspended — risposta AI inibita", org_id, msg["id"])
            tenant_config = await load_tenant_config(org_id, self.app_config, self.repo)
            try:
                res = await self._send_ai_reply(org_id, msg, content, tenant_config, ORG_SUSPENDED_REPLY, handling_type="automation")
                meta_id = (res.get("wam_id") or f"meta-{msg['id']}") if isinstance(res, dict) else f"meta-{msg['id']}"
                await self._finalize_message(msg["id"], handling_type="suspended", meta_message_id=meta_id, organization_id=org_id)
            except Exception as e:
                logger.error("Org suspended message send failed for %s: %s", msg["id"], e)
            return

        tenant_config = await load_tenant_config(org_id, self.app_config, self.repo)
        if tenant_config is not None:
            business_profile_raw = getattr(tenant_config, "business_profile", None) or {}
        else:
            business_profile_raw = await self.repo.get_org_business_profile(org_id) or {}

        fast_reply = await self.service.fast_path_match(text, business_profile_raw)
        if fast_reply:
            from_number = content.get("from", "")
            nome = (business_profile_raw or {}).get("nome") or "Attivita"
            decorated = await decorate_with_disclosure(org_id, from_number, fast_reply, self.repo, nome_attivita=nome)
            try:
                res = await self._send_ai_reply(org_id, msg, content, tenant_config, decorated)
                meta_id = (res.get("wam_id") or f"meta-{msg['id']}") if isinstance(res, dict) else f"meta-{msg['id']}"
                await self._finalize_message(msg["id"], handling_type="ai_handled", meta_message_id=meta_id, organization_id=org_id)
            except Exception as e:
                logger.error("Fast reply send failed for %s: %s", msg["id"], e)
            return

        profilo = _profile_from_dict(business_profile_raw)
        
        # Outbox Pattern (P0-2) legacy handled by sent_at in claim_message_and_check_quota
        dedup = await self.repo.get_outbound_dedup(msg["organization_id"], msg["id"])
        if dedup:
            from_number = content.get("from", "")
            try:
                res = await self._send_ai_reply(org_id, msg, content, tenant_config, dedup["response_text"])
                meta_id = (res.get("wam_id") or f"meta-{msg['id']}") if isinstance(res, dict) else f"meta-{msg['id']}"
                await self._finalize_message(msg["id"], handling_type="ai_handled", meta_message_id=meta_id, organization_id=org_id)
            except Exception as e:
                logger.error("Dedup send failed for %s: %s", msg["id"], e)
            return

        messaggio = MessaggioInput(
            testo=text,
            canale=CanaleMessaggio(canale),
            id_conversazione=str(msg.get("conversation_id", "")),
        )

        intent_result = await classifica_intent(text)
        if intent_result.source == "llm":
            try:
                await self.repo.record_usage(
                    org_id,
                    "intent_classification",
                    metadata={
                        "intent": intent_result.intent,
                        "confidence": intent_result.confidence,
                        "message_id": str(msg["id"]),
                    },
                )
            except Exception as e:
                logger.warning("Intent usage logging failed for org %s msg %s: %s", org_id, msg["id"], e)

        q_emb = None
        if faq_cache.cache_enabled() and intent_result.intent == "faq":
            try:
                q_emb = await faq_cache.embedding_query(text)
                cached_answer = await faq_cache.cerca_in_cache(str(org_id), text, self.repo, q_emb=q_emb)
            except Exception as e:
                logger.warning("FAQ cache lookup failed for org %s msg %s: %s", org_id, msg["id"], e)
                cached_answer = None
            if cached_answer:
                from_number = content.get("from", "")
                decorated = await decorate_with_disclosure(org_id, from_number, cached_answer, self.repo, profilo.nome)
                try:
                    res = await self._send_ai_reply(org_id, msg, content, tenant_config, decorated)
                    meta_id = (res.get("wam_id") or f"meta-{msg['id']}") if isinstance(res, dict) else f"meta-{msg['id']}"
                    try:
                        await self.repo.record_usage(
                            org_id,
                            "cache_hit",
                            metadata={
                                "conversation_id": str(msg.get("conversation_id", "")),
                                "message_id": str(msg["id"]),
                                "intent": intent_result.intent,
                            },
                        )
                    except Exception as e:
                        logger.warning("Cache hit usage logging failed for org %s msg %s: %s", org_id, msg["id"], e)
                    await self._finalize_message(msg["id"], handling_type="ai_handled", meta_message_id=meta_id, organization_id=org_id)
                except Exception as e:
                    logger.error("FAQ cache reply send failed for %s: %s", msg["id"], e)
                return

        ai_cached = claim_result.get("ai_reply_cache")
        risposta_text = ""
        richiede_umano = False
        pren = None
        esito = None
        variante_prompt = assegna_variante(str(org_id))
        
        if ai_cached:
            if isinstance(ai_cached, dict):
                risposta_text = ai_cached.get("text", "")
                richiede_umano = bool(ai_cached.get("richiede_umano", False))
            elif isinstance(ai_cached, str):
                try:
                    parsed = json.loads(ai_cached)
                    if isinstance(parsed, dict):
                        risposta_text = parsed.get("text", "")
                        richiede_umano = bool(parsed.get("richiede_umano", False))
                    else:
                        risposta_text = parsed
                except Exception:
                    risposta_text = ai_cached
        else:
            if await self.repo.check_booking_exists(msg["id"], org_id):
                risposta_text = "Ho confermato la tua prenotazione!"
                richiede_umano = False
                await self.repo.save_ai_reply(
                    msg["id"],
                    reply={"text": risposta_text, "richiede_umano": False, "motivo": "booking_exists"},
                    organization_id=org_id,
                )
            else:
                heartbeat_task = asyncio.ensure_future(self._heartbeat_loop(msg["id"], org_id))
                try:
                    contesto = await recupera_contesto_documenti(str(org_id), text, self.repo, q_emb=q_emb)
                    risposta = await genera_risposta_async(
                        messaggio, profilo, billing=state, contesto_documenti=contesto.testo,
                        intent=intent_result.intent, variante=variante_prompt,
                    )
                finally:
                    heartbeat_task.cancel()

                esito = valida_risposta(risposta, contesto.chunks, profilo)
                if esito.azione != "none":
                    risposta = applica_guardrail(risposta, esito)
                    if esito.azione == "block":
                        logger.warning("guardrail block org_id=%s message_id=%s motivo=%s", org_id, msg["id"], esito.motivo)
                        try:
                            await self.repo.record_usage(
                                org_id, "guardrail_block",
                                metadata={"motivo": esito.motivo, "violazioni": list(esito.violazioni), "conversation_id": str(msg.get("conversation_id", "")), "message_id": str(msg["id"])}
                            )
                        except Exception as e:
                            logger.warning("Guardrail usage logging failed for org %s msg %s: %s", org_id, msg["id"], e)

                try:
                    route = route_llm(
                        LLMRouteRequest(
                            task_type="customer_message",
                            user_text=text,
                            remaining_budget_ratio=budget_ratio_from_billing(state),
                            intent=intent_result.intent,
                        )
                    )
                    await self.repo.record_usage(
                        org_id, "ai_response", quantity=1,
                        metadata={
                            "channel": canale, "model": route.model, "tier": route.tier, "reason": route.reason,
                            "intent": intent_result.intent, "intent_source": intent_result.source, "prompt_variant": variante_prompt,
                            "conversation_id": str(msg.get("conversation_id", "")), "message_id": str(msg["id"]),
                        }
                    )
                except Exception as e:
                    logger.warning("AI usage logging failed for org %s msg %s: %s", org_id, msg["id"], e)

                pren = risposta.prenotazione
                if pren and pren.data and pren.ora and pren.coperti:
                    if self.booking_service:
                        try:
                            created = await self.booking_service.create_booking(
                                org_id=org_id,
                                nome_cliente=pren.nome_cliente or ("Cliente Instagram" if canale == "instagram" else "Cliente WhatsApp"),
                                telefono=pren.telefono or ("" if canale == "instagram" else content.get("from", "")),
                                data=pren.data,
                                ora=pren.ora,
                                coperti=pren.coperti,
                                note=pren.note,
                                origine="Instagram" if canale == "instagram" else "WhatsApp",
                                richiede_intervento=risposta.richiede_umano,
                                id_conversazione=str(msg.get("conversation_id", "")),
                                source_message_id=str(msg["id"])
                            )
                            logger.info("Booking %s created from AI response for org %s", created["id"], org_id)
                        except SlotPienoError as e:
                            if e.alternative:
                                alt_text = " o ".join(e.alternative)
                                risposta.risposta += f" Mi dispiace, alle {pren.ora} siamo al completo per {pren.coperti} persone. Ti andrebbe bene alle {alt_text}?"
                            else:
                                risposta.risposta += f" Mi dispiace, alle {pren.ora} siamo al completo per {pren.coperti} persone. Posso chiedere allo staff una fascia alternativa."
                            risposta.motivo = "slot_prenotazione_pieno"
                        except Exception as e:
                            logger.error("Booking creation from AI failed for org %s: %s", org_id, e)

                risposta_text = risposta.risposta
                richiede_umano = bool(risposta.richiede_umano)

                # Persist full JSONB metadata structure to ai_reply_cache
                await self.repo.save_ai_reply(
                    msg["id"],
                    reply={
                        "text": risposta_text,
                        "richiede_umano": richiede_umano,
                        "motivo": getattr(risposta, "motivo", "") or (getattr(esito, "motivo", "") if esito else ""),
                    },
                    organization_id=org_id,
                )

        if richiede_umano:
            try:
                meta_id = None
                if risposta_text:
                    from_number = content.get("from", "")
                    decorated = await decorate_with_disclosure(org_id, from_number, risposta_text, self.repo, profilo.nome)
                    res = await self._send_ai_reply(org_id, msg, content, tenant_config, decorated)
                    meta_id = (res.get("wam_id") or f"meta-{msg['id']}") if isinstance(res, dict) else f"meta-{msg['id']}"
                conv = await self.repo.escalate_to_human(str(msg["conversation_id"]), org_id)
                if conv:
                    enqueue_escalation(
                        org_id=str(org_id), conversation_id=str(msg["conversation_id"]),
                        contact_name=content.get("from", "cliente"), pool=self.repo.pool,
                    )
                await self._finalize_message(msg["id"], handling_type="escalated", meta_message_id=meta_id, organization_id=org_id)
            except Exception as e:
                logger.error("Human escalation reply send failed for %s: %s", msg["id"], e)
            return

        from_number = content.get("from", "")
        decorated = await decorate_with_disclosure(org_id, from_number, risposta_text, self.repo, profilo.nome)
        
        await self.repo.save_outbound_dedup(msg["id"], org_id, decorated)
        
        # Step 7: Send to Meta
        try:
            res = await self._send_ai_reply(org_id, msg, content, tenant_config, decorated)
            meta_message_id = (res.get("wam_id") or f"meta-{msg['id']}") if isinstance(res, dict) else f"meta-{msg['id']}"
            await self._finalize_message(msg["id"], handling_type="ai_handled", meta_message_id=meta_message_id, organization_id=org_id)
        except Exception as e:
            logger.error("Meta send failed for %s: %s", msg["id"], e)
            return

        if (esito and faq_cache.cache_enabled() and intent_result.intent == "faq"
                and esito.azione != "block" and not richiede_umano
                and not (pren and pren.data and pren.ora and pren.coperti)):
            try:
                await faq_cache.salva_in_cache(
                    str(org_id), text, risposta_text, self.repo,
                    q_emb=q_emb, prompt_variant=variante_prompt,
                )
            except Exception as e:
                logger.warning("FAQ cache store failed for org %s msg %s: %s", org_id, msg["id"], e)

    async def _handle_feedback_emoji(self, org_id, msg, value: str):
        """Registra il 👍/👎 del cliente sull'ultima risposta AI della
        conversazione e chiude il messaggio senza generare risposta. Se non
        c'e' una risposta AI recente il feedback non ha target, ma il
        messaggio resta comunque gestito (un pollice non va mai all'LLM)."""
        try:
            ultimo_ai = await self.repo.get_last_ai_outbound_message(
                org_id, str(msg["conversation_id"])
            )
            if ultimo_ai:
                await self.repo.registra_feedback(
                    organization_id=org_id,
                    message_id=ultimo_ai["id"],
                    conversation_id=str(msg["conversation_id"]),
                    source="customer_emoji",
                    value=value,
                )
                logger.info(
                    "feedback cliente %s su risposta AI %s (org %s)",
                    value, ultimo_ai["id"], org_id,
                )
        except Exception as e:
            logger.error("Registrazione feedback emoji fallita msg %s: %s", msg["id"], e)
        # Il feedback emoji non esegue alcuna chiamata di rete esterna (nessun invio a Meta/AI).
        # La persistenza del feedback avviene interamente su DB locale; è sicuro finalizzare subito.
        await self._finalize_message(msg["id"], handling_type="feedback", organization_id=org_id)

    async def _finalize_message(self, msg_id: str, handling_type: str, organization_id,
                                meta_message_id: str | None = None) -> bool:
        """
        Punto unico di finalizzazione condiviso per tutti i flussi.
        Marca il messaggio come inviato a Meta (sent_at) e come risolto (replied_at/status=handled).
        Viene chiamato SOLO DOPO che qualsiasi side-effect esterno (invio Meta) ha avuto successo confermato.
        """
        if meta_message_id:
            await self.repo.mark_message_sent(msg_id, meta_message_id, organization_id)
        return await self.repo.try_mark_replied(msg_id, handling_type=handling_type,
                                                 organization_id=organization_id)

    async def _send_ai_reply(self, org_id, msg, content, tenant_config, testo_risposta,
                             handling_type="ai_handled") -> dict:
        canale = msg.get("canale") or "whatsapp"
        if canale == "instagram":
            return await self._send_instagram_reply(org_id, msg, content, testo_risposta, handling_type=handling_type)
        to_number = content.get("from", "")
        if not to_number or not tenant_config:
            logger.warning("Impossibile inviare risposta AI per messaggio %s: numero o tenant_config mancante", msg["id"])
            return {}
        payload = {"to": to_number, "type": "text", "text": {"body": testo_risposta}}
        try:
            return await self.service.send_whatsapp_message(
                org_id=org_id,
                to_number=to_number,
                payload=payload,
                category="service",
                meta_client=None,
                tenant_config=tenant_config,
                handling_type=handling_type,
            )
        except self.service.MessageUsageExceeded:
            logger.warning("Quota messaggi esaurita per org %s: risposta AI non inviata", org_id)
            raise
        except Exception as e:
            logger.error("Invio risposta AI fallito per messaggio %s: %s", msg["id"], e)
            raise

    async def _send_instagram_reply(self, org_id, msg, content, testo_risposta,
                                    handling_type="ai_handled") -> dict:
        """Invio della risposta AI via Instagram DM. Se l'org non ha un
        account Instagram collegato (non dovrebbe accadere: il webhook
        arriva solo per account registrati) logga e non crasha."""
        to_ig_id = content.get("from", "")
        if not to_ig_id:
            logger.warning("Impossibile inviare risposta AI Instagram per messaggio %s: mittente mancante", msg["id"])
            return {}
        from src.instagram.config import load_instagram_config
        from src.instagram.repository import InstagramRepository
        from src.instagram.service import InstagramService

        try:
            ig_config = await load_instagram_config(
                org_id, self.app_config.encryption_key, InstagramRepository(self.repo.pool)
            )
            if not ig_config:
                logger.warning("Org %s: account Instagram non configurato, risposta AI non inviata", org_id)
                return {}
            return await InstagramService(self.repo).send_instagram_message(
                org_id=org_id,
                to_ig_id=to_ig_id,
                text=testo_risposta,
                ig_config=ig_config,
                handling_type=handling_type,
            )
        except Exception as e:
            logger.error("Invio risposta AI Instagram fallito per messaggio %s: %s", msg["id"], e)
            raise
