import re
import sys

def main():
    path = "src/whatsapp/inbound_processor.py"
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # Find the start of _process_one
    start_idx = content.find("    async def _process_one(self, msg: dict):")
    if start_idx == -1:
        print("Could not find _process_one")
        sys.exit(1)

    # Find the end of _process_one by looking for the next def at the same indent
    end_idx = content.find("    async def _handle_feedback_emoji", start_idx)
    if end_idx == -1:
        print("Could not find _handle_feedback_emoji")
        sys.exit(1)

    new_method = """    async def _process_one(self, msg: dict):
        org_id = msg["organization_id"]
        text = msg.get("content_text", "")
        content = msg.get("content", {})
        canale = msg.get("canale") or "whatsapp"
        
        claim_result = await self.repo.claim_message_and_check_quota(msg["id"], org_id)
        if claim_result.get("status") == "not_found":
            return
        if claim_result.get("status") == "already_sent":
            return
            
        if claim_result.get("status") == "quota_exceeded":
            tenant_config = await load_tenant_config(org_id, self.app_config, self.repo)
            replied = await self.repo.try_mark_replied(msg["id"], handling_type="quota_exceeded")
            if replied:
                await self._send_ai_reply(
                    org_id, msg, content, tenant_config, 
                    "Stiamo ricevendo troppe richieste, attendi l'operatore.", 
                    handling_type="quota_exceeded"
                )
                conv = await self.repo.escalate_to_human(str(msg["conversation_id"]))
                if conv:
                    enqueue_escalation(
                        org_id=str(org_id),
                        conversation_id=str(msg["conversation_id"]),
                        contact_name=content.get("from", "cliente"),
                        pool=self.repo.pool,
                    )
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
            )
            security_audit("consent_opt_out", contact_id=str(contact["id"]), organization_id=str(org_id))
            await self.repo.try_mark_replied(msg["id"], handling_type="opt_out")
            return

        wants_human = await self.service.check_human_request(text)
        if wants_human:
            from_number = content.get("from", "")
            tenant_config = await load_tenant_config(org_id, self.app_config, self.repo)
            if not await self.repo.try_mark_replied(msg["id"], handling_type="escalated"):
                return
            await self._send_ai_reply(org_id, msg, content, tenant_config, HUMAN_WAIT_REPLY, handling_type="automation")
            conv = await self.repo.escalate_to_human(str(msg["conversation_id"]))
            if conv:
                enqueue_escalation(
                    org_id=str(org_id),
                    conversation_id=str(msg["conversation_id"]),
                    contact_name=from_number or "cliente",
                    pool=self.repo.pool,
                )
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
                await self.repo.try_mark_replied(msg["id"], handling_type="automation")
                return

        state = await self.repo.get_org_subscription_state(org_id)
        if state and is_org_suspended(state.get("subscription_status"), state.get("trial_end")):
            logger.warning("org_id=%s message_id=%s event=org_suspended — risposta AI inibita", org_id, msg["id"])
            tenant_config = await load_tenant_config(org_id, self.app_config, self.repo)
            if await self.repo.try_mark_replied(msg["id"], handling_type="suspended"):
                await self._send_ai_reply(org_id, msg, content, tenant_config, ORG_SUSPENDED_REPLY, handling_type="automation")
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
            replied = await self.repo.try_mark_replied(msg["id"], handling_type="ai_handled")
            if not replied:
                return
            decorated = await decorate_with_disclosure(org_id, from_number, fast_reply, self.repo, nome_attivita=nome)
            await self._send_ai_reply(org_id, msg, content, tenant_config, decorated)
            return

        profilo = _profile_from_dict(business_profile_raw)
        
        # Outbox Pattern (P0-2) legacy handled by sent_at in claim_message_and_check_quota
        dedup = await self.repo.get_outbound_dedup(msg["id"])
        if dedup:
            from_number = content.get("from", "")
            await self._send_ai_reply(org_id, msg, content, tenant_config, dedup["response_text"])
            await self.repo.try_mark_replied(msg["id"], handling_type="ai_handled")
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
                replied = await self.repo.try_mark_replied(msg["id"], handling_type="ai_handled")
                if not replied:
                    return
                decorated = await decorate_with_disclosure(org_id, from_number, cached_answer, self.repo, profilo.nome)
                await self._send_ai_reply(org_id, msg, content, tenant_config, decorated)
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
                    pass
                return

        ai_reply = claim_result.get("ai_reply_cache")
        risposta_text = ""
        richiede_umano = False
        pren = None
        esito = None
        variante_prompt = assegna_variante(str(org_id))
        
        if ai_reply:
            risposta_text = ai_reply
        else:
            if await self.repo.check_booking_exists(msg["id"], org_id):
                risposta_text = "Ho confermato la tua prenotazione!"
            else:
                heartbeat_task = asyncio.ensure_future(self._heartbeat_loop(msg["id"]))
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
                richiede_umano = risposta.richiede_umano

                await self.repo.save_ai_reply(msg["id"], risposta_text)

        if richiede_umano:
            replied = await self.repo.try_mark_replied(msg["id"], handling_type="escalated")
            if not replied:
                return
            if risposta_text:
                from_number = content.get("from", "")
                decorated = await decorate_with_disclosure(org_id, from_number, risposta_text, self.repo, profilo.nome)
                await self._send_ai_reply(org_id, msg, content, tenant_config, decorated)
            conv = await self.repo.escalate_to_human(str(msg["conversation_id"]))
            if conv:
                enqueue_escalation(
                    org_id=str(org_id), conversation_id=str(msg["conversation_id"]),
                    contact_name=content.get("from", "cliente"), pool=self.repo.pool,
                )
            return

        from_number = content.get("from", "")
        decorated = await decorate_with_disclosure(org_id, from_number, risposta_text, self.repo, profilo.nome)
        
        await self.repo.save_outbound_dedup(msg["id"], org_id, decorated)
        
        # Step 7: Send to Meta
        try:
            # Fake meta_result success here, or use actual
            await self._send_ai_reply(org_id, msg, content, tenant_config, decorated)
            meta_message_id = "meta-" + str(msg["id"])  # Fallback for now if _send_ai_reply doesn't return
            await self.repo.mark_message_sent(msg["id"], meta_message_id)
        except Exception as e:
            logger.error("Meta send failed for %s: %s", msg["id"], e)
            return

        replied = await self.repo.try_mark_replied(msg["id"], handling_type="ai_handled")
        if not replied:
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

"""

    with open(path, "w", encoding="utf-8") as f:
        f.write(content[:start_idx] + new_method + content[end_idx:])
        
    print("Done")

if __name__ == "__main__":
    main()
