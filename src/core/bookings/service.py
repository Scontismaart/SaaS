from datetime import datetime, date, time, timezone
import logging

from src.models.schemas import DisponibilitaSlot

logger = logging.getLogger(__name__)

STATI_OCCUPATI = {"in_attesa", "confermata", "da_verificare", "completata"}
STATI_LIBERI = {"cancellata", "cancellato", "rifiutata", "no_show"}
SLOT_ORE = [f"{h:02d}:00" for h in range(24)]


class SlotPienoError(ValueError):
    def __init__(self, message, alternative=None):
        super().__init__(message)
        self.alternative = alternative or []


class BookingService:
    def __init__(self, repo, whatsapp_service=None, app_config=None, calendar_service=None):
        self.repo = repo
        self.whatsapp = whatsapp_service
        self.app_config = app_config
        self.calendar_service = calendar_service

    # ── Disponibilità ──────────────────────────────────────────

    async def _coperti_prenotati(self, org_id, data, ora):
        bookings = await self.repo.list_bookings(org_id, data)
        fascia = f"{int(ora[:2]):02d}:00"
        occupati = 0
        for b in bookings:
            if b["stato"] in STATI_LIBERI:
                continue
            ora_b = b["ora"]
            if isinstance(ora_b, time):
                ora_b = ora_b.strftime("%H:%M")
            b_fascia = f"{int(ora_b[:2]):02d}:00"
            if b_fascia == fascia:
                occupati += (b["coperti"] or 0)
        return occupati

    async def _get_capienze(self, org_id):
        settings = await self.repo.get_booking_settings(org_id)
        if settings and settings.get("capienze_orarie"):
            return settings["capienze_orarie"]
        return {f: 40 for f in SLOT_ORE}

    async def verifica_disponibilita(self, org_id, data, ora, coperti=None):
        prenotati = await self._coperti_prenotati(org_id, data, ora)
        fascia = f"{int(ora[:2]):02d}:00"
        capienze = await self._get_capienze(org_id)
        massimi = capienze.get(fascia, 40)
        liberi = max(massimi - prenotati, 0)
        alternative = []
        if coperti and coperti > liberi:
            alternative = [
                f for f in SLOT_ORE
                if f != fascia and (capienze.get(f, 0) - await self._coperti_prenotati(org_id, data, f)) >= coperti
            ][:2]
        if liberi <= 0:
            stato = "rosso"
        elif liberi <= max(4, round(massimi * 0.2)):
            stato = "giallo"
        else:
            stato = "verde"
        return DisponibilitaSlot(
            data=data, ora=ora,
            coperti_massimi=massimi, coperti_prenotati=prenotati,
            coperti_liberi=liberi, stato=stato, alternative=alternative,
        )

    async def semaforo_giorno(self, org_id, data):
        capienze = await self._get_capienze(org_id)
        bookings = await self.repo.list_bookings(org_id, data)
        slots = []
        for fascia in SLOT_ORE:
            if capienze.get(fascia, 0) <= 0:
                continue
            prenotati = 0
            for b in bookings:
                if b["stato"] in STATI_LIBERI:
                    continue
                ora_b = b["ora"]
                if isinstance(ora_b, time):
                    ora_b = ora_b.strftime("%H:%M")
                b_fascia = f"{int(ora_b[:2]):02d}:00"
                if b_fascia == fascia:
                    prenotati += (b["coperti"] or 0)
            massimi = capienze[fascia]
            liberi = max(massimi - prenotati, 0)
            if liberi <= 0:
                stato = "rosso"
            elif liberi <= max(4, round(massimi * 0.2)):
                stato = "giallo"
            else:
                stato = "verde"
            slots.append(DisponibilitaSlot(
                data=data, ora=fascia,
                coperti_massimi=massimi, coperti_prenotati=prenotati,
                coperti_liberi=liberi, stato=stato, alternative=[],
            ))
        return slots

    async def prossimi_giorni_semaforo(self, org_id, giorni=7):
        from datetime import timedelta
        oggi = datetime.now().date()
        slots = []
        for offset in range(giorni):
            giorno = (oggi + timedelta(days=offset)).strftime("%Y-%m-%d")
            slots.extend(await self.semaforo_giorno(org_id, giorno))
        return slots

    # ── Creazione ──────────────────────────────────────────────

    async def create_booking(self, org_id, nome_cliente, data, ora, coperti,
                              telefono="", note="", tipo_evento="", origine="Dashboard",
                              richiede_intervento=False, id_conversazione="", source_message_id=None):
        disp = await self.verifica_disponibilita(org_id, data, ora, coperti)
        if coperti > disp.coperti_liberi:
            raise SlotPienoError(
                f"slot pieno per {coperti} coperti alle {ora}",
                alternative=disp.alternative,
            )
        richiede_dep = await self._valuta_richiede_deposito(
            org_id, coperti=coperti, tipo_evento=tipo_evento, ora=ora, data=data
        )
        booking = await self.repo.create_booking(
            organization_id=org_id, nome_cliente=nome_cliente,
            telefono=telefono, data=data, ora=ora, coperti=coperti,
            note=note, tipo_evento=tipo_evento, stato="in_attesa", origine=origine,
            richiede_deposito=richiede_dep,
            richiede_intervento=richiede_intervento,
            id_conversazione=id_conversazione or None,
            source_message_id=source_message_id,
        )
        if self.calendar_service:
            try:
                await self.calendar_service.sync_booking_state(booking, org_id)
            except Exception:
                logger.exception("calendar=sync_fail create_booking id=%s", booking.get("id"))
        return booking

    async def _get_booking_or_raise(self, org_id, booking_id):
        b = await self.repo.get_booking(org_id, booking_id)
        if not b:
            raise ValueError(f"booking {booking_id} non trovato")
        return b

    # ── WhatsApp ───────────────────────────────────────────────

    async def _load_tenant_config(self, org_id):
        if not self.app_config or not self.whatsapp:
            return None
        from src.whatsapp.config import load_tenant_config
        return await load_tenant_config(org_id, self.app_config, self.whatsapp.repo)

    async def _send_whatsapp(self, org_id, to_number, text, category="service"):
        if not self.whatsapp or not to_number:
            return
        tenant = await self._load_tenant_config(org_id)
        if not tenant:
            return
        try:
            await self.whatsapp.send_whatsapp_message(
                org_id=org_id, to_number=to_number,
                payload={"to": to_number, "type": "text", "text": {"body": text}},
                category=category, meta_client=None, tenant_config=tenant,
            )
        except Exception as e:
            logger.error("WhatsApp send failed for org %s: %s", org_id, e)

    # ── Lifecycle ──────────────────────────────────────────────

    async def confirm(self, org_id, booking_id):
        b = await self._get_booking_or_raise(org_id, booking_id)
        updated = await self.repo.update_booking_status(org_id, booking_id, "confermata")
        msg = f"La tua prenotazione del {b['data']} alle {b['ora']} per {b['coperti']} persone e' confermata!"
        await self._send_whatsapp(org_id, b["telefono"], msg)
        if b.get("richiede_deposito"):
            cfg = await self._get_deposito_config(org_id)
            importo = (cfg or {}).get("importo_default", 10.0)
            valuta = (cfg or {}).get("valuta", "EUR")
            try:
                link = await self._genera_payment_link(org_id, booking_id, importo, valuta)
                async with self.repo.pool.acquire() as conn:
                    await conn.execute("""
                        UPDATE bookings SET payment_link = $3,
                            payment_link_created_at = NOW(), payment_status = 'pending'
                        WHERE organization_id = $1 AND id = $2
                    """, org_id, booking_id, link)
                updated["payment_link"] = link
                updated["payment_status"] = "pending"
                await self._send_whatsapp(org_id, b["telefono"],
                    f"Per confermare, versa il deposito di {valuta} {importo:.2f}: {link}")
            except Exception as e:
                logger.error("Failed to generate payment link for booking %s: %s", booking_id, e)
        if self.calendar_service:
            try:
                await self.calendar_service.sync_booking_state(updated, org_id)
            except Exception:
                logger.exception("calendar=sync_fail confirm id=%s", booking_id)
        return updated

    async def reject(self, org_id, booking_id, motivo=""):
        b = await self._get_booking_or_raise(org_id, booking_id)
        updated = await self.repo.update_booking_status(org_id, booking_id, "rifiutata")
        msg = f"La tua prenotazione del {b['data']} alle {b['ora']} non puo' essere confermata."
        if motivo:
            msg += f" Motivo: {motivo}"
        await self._send_whatsapp(org_id, b["telefono"], msg)
        if self.calendar_service:
            try:
                await self.calendar_service.sync_booking_state(updated, org_id)
            except Exception:
                logger.exception("calendar=sync_fail reject id=%s", booking_id)
        return updated

    async def cancel(self, org_id, booking_id):
        booking = await self.repo.update_booking_status(org_id, booking_id, "cancellata")
        if self.calendar_service:
            try:
                await self.calendar_service.sync_booking_state(booking, org_id)
            except Exception:
                logger.exception("calendar=sync_fail cancel id=%s", booking_id)
        return booking

    async def mark_no_show(self, org_id, booking_id):
        async with self.repo.pool.acquire() as conn:
            row = await conn.fetchrow("""
                UPDATE bookings SET stato = 'no_show', no_show_at = NOW(), updated_at = NOW()
                WHERE organization_id = $1 AND id = $2
                RETURNING *
            """, org_id, booking_id)
            booking = dict(row) if row else None
        if booking and self.calendar_service:
            try:
                await self.calendar_service.sync_booking_state(booking, org_id)
            except Exception:
                logger.exception("calendar=sync_fail mark_no_show id=%s", booking_id)
        return booking

    async def mark_completed(self, org_id, booking_id):
        async with self.repo.pool.acquire() as conn:
            row = await conn.fetchrow("""
                UPDATE bookings SET stato = 'completata', completata_at = NOW(), updated_at = NOW()
                WHERE organization_id = $1 AND id = $2
                RETURNING *
            """, org_id, booking_id)
            booking = dict(row) if row else None
        if booking and self.calendar_service:
            try:
                await self.calendar_service.sync_booking_state(booking, org_id)
            except Exception:
                logger.exception("calendar=sync_fail mark_completed id=%s", booking_id)
        return booking

    async def aggiorna_impostazioni(self, org_id, capienze_orarie=None,
                                     coperti_massimi=40, fasce_orarie=None, config=None):
        if capienze_orarie is None and fasce_orarie is None:
            return await self.repo.upsert_booking_settings_config(org_id, config or {})
        if config:
            current = await self.repo.get_booking_settings(org_id)
            merged = dict(current.get("config") or {}) if current else {}
            merged.update(config)
            await self.repo.upsert_booking_settings_config(org_id, merged)
        if capienze_orarie is not None or fasce_orarie is not None:
            await self.repo.upsert_booking_settings(
                org_id,
                fasce_orarie=fasce_orarie or [f"{h:02d}:00" for h in range(24)],
                capienze_orarie=capienze_orarie or {f: coperti_massimi for f in SLOT_ORE},
            )
        return await self.repo.get_booking_settings(org_id)

    # ── Reminder ──────────────────────────────────────────────

    REMINDER_CONFIRM_KEYWORDS = {"si", "confermo", "conferma", "ok", "okay", "certo", "sicuro"}
    REMINDER_REJECT_KEYWORDS = {"no", "annulla", "cancella", "non vengo", "non posso"}

    async def handle_reminder_reply(self, org_id, from_number, text):
        bookings = await self.repo.list_bookings_by_stato(org_id, "confermata")
        pending = [
            b for b in bookings
            if b.get("reminder_status") == "sent"
               and b.get("telefono", "").strip() == from_number.strip()
        ]
        if not pending:
            return None
        b = pending[0]
        text_lower = text.lower().strip()
        confirmed = any(kw in text_lower for kw in self.REMINDER_CONFIRM_KEYWORDS)
        rejected = any(kw in text_lower for kw in self.REMINDER_REJECT_KEYWORDS)
        if confirmed and not rejected:
            await self.repo.update_booking_reminder_status(
                org_id, b["id"], "confirmed", datetime.now(timezone.utc)
            )
            await self._send_whatsapp(org_id, from_number,
                "Grazie, la tua prenotazione e' confermata! Ti aspettiamo.")
            return "confirmed"
        elif rejected:
            await self.repo.update_booking_status(org_id, b["id"], "cancellata")
            await self.repo.update_booking_reminder_status(
                org_id, b["id"], "rejected", datetime.now(timezone.utc)
            )
            await self._send_whatsapp(org_id, from_number,
                "Prenotazione cancellata. Per qualsiasi altra richiesta, siamo a disposizione.")
            return "rejected"
        else:
            await self.repo.update_booking_reminder_status(
                org_id, b["id"], "flagged", datetime.now(timezone.utc)
            )
            return "flagged"

    # ── Deposito ───────────────────────────────────────────────

    async def _get_deposito_config(self, org_id):
        settings = await self.repo.get_booking_settings(org_id)
        if not settings:
            return None
        config = settings.get("config") or {}
        return config.get("deposito")

    async def _valuta_richiede_deposito(self, org_id, coperti=0, tipo_evento="", ora="", data=""):
        cfg = await self._get_deposito_config(org_id)
        if not cfg or not cfg.get("enabled"):
            return False
        criteri = cfg.get("criteri") or {}
        coperti_min = criteri.get("coperti_min")
        if coperti_min is not None and coperti >= coperti_min:
            return True
        tipi = criteri.get("tipi_evento") or []
        if tipo_evento and tipo_evento in tipi:
            return True
        fasce = criteri.get("fasce") or []
        ora_fascia = f"{int(ora[:2]):02d}:00"
        if ora_fascia in fasce:
            return True
        date_specifiche = criteri.get("date") or []
        if data in date_specifiche:
            return True
        return False

    async def _genera_payment_link(self, org_id, booking_id, importo, valuta="EUR"):
        import stripe
        link = stripe.PaymentLink.create(
            line_items=[{
                "price_data": {
                    "unit_amount": int(round(importo * 100)),
                    "currency": valuta.lower(),
                    "product_data": {"name": "Deposito prenotazione"},
                },
                "quantity": 1,
            }],
            metadata={"booking_id": str(booking_id), "organization_id": str(org_id)},
            after_completion={"type": "redirect", "redirect": {"url": ""}},
        )
        return link.url
