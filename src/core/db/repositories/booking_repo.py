import json
import uuid
from contextlib import asynccontextmanager
from datetime import date, time

import asyncpg

from src.core.db.scoping import TenantScopedRepository


class BookingRepository(TenantScopedRepository):
    """Repository specializzato per Prenotazioni, Lock di Slot (P0) e Capienze."""

    def __init__(self, pool):
        self.pool = pool

    @asynccontextmanager
    async def slot_lock(self, organization_id, data, ora):
        """Lock consultivo transazionale su una fascia oraria (anti double-booking)."""
        fascia = int(ora[:2]) if isinstance(ora, str) else ora.hour
        chiave = f"{organization_id}|{data}|{fascia}"
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.fetchval("SELECT pg_advisory_xact_lock(hashtext($1))", chiave)
                yield

    async def create_booking(self, organization_id, nome_cliente, data, ora, coperti,
                             telefono="", note="", stato="in_attesa", origine="Dashboard",
                             richiede_intervento=False, id_conversazione=None,
                             contact_id=None, richiede_deposito=False,
                             completata_at=None, tipo_evento="", source_message_id=None):
        if isinstance(data, str):
            data = date.fromisoformat(data)
        if isinstance(ora, str):
            ore, minuti = ora.split(":")
            ora = time(int(ore), int(minuti))
        async with self.pool.acquire() as conn:
            if source_message_id:
                try:
                    row = await conn.fetchrow("""
                        INSERT INTO bookings (id, organization_id, contact_id,
                                              nome_cliente, telefono, data, ora, coperti,
                                              note, stato, origine, richiede_intervento,
                                              id_conversazione, richiede_deposito, completata_at,
                                              tipo_evento, source_message_id)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17)
                        ON CONFLICT (organization_id, source_message_id) WHERE source_message_id IS NOT NULL
                            DO NOTHING
                        RETURNING *
                    """, uuid.uuid4(), organization_id, contact_id,
                    nome_cliente, telefono, data, ora, coperti,
                    note, stato, origine, richiede_intervento,
                    id_conversazione, richiede_deposito, completata_at, tipo_evento, source_message_id)
                except asyncpg.exceptions.UniqueViolationError:
                    row = None
                if not row:
                    row = await conn.fetchrow("""
                        SELECT * FROM bookings WHERE organization_id = $1 AND source_message_id = $2
                    """, organization_id, source_message_id)
                return dict(row) if row else None
            else:
                row = await conn.fetchrow("""
                    INSERT INTO bookings (id, organization_id, contact_id,
                                          nome_cliente, telefono, data, ora, coperti,
                                          note, stato, origine, richiede_intervento,
                                          id_conversazione, richiede_deposito, completata_at,
                                          tipo_evento)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
                    RETURNING *
                """, uuid.uuid4(), organization_id, contact_id,
                nome_cliente, telefono, data, ora, coperti,
                note, stato, origine, richiede_intervento,
                id_conversazione, richiede_deposito, completata_at, tipo_evento)
                return dict(row)

    async def get_booking(self, organization_id, booking_id):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM bookings WHERE organization_id = $1 AND id = $2",
                organization_id, booking_id,
            )
            return dict(row) if row else None

    async def list_bookings(self, organization_id, data=None):
        if data is not None and isinstance(data, str):
            data = date.fromisoformat(data)
        async with self.pool.acquire() as conn:
            if data is not None:
                rows = await conn.fetch(
                    "SELECT * FROM bookings WHERE organization_id = $1 AND data = $2 ORDER BY ora",
                    organization_id, data,
                )
            else:
                rows = await conn.fetch(
                    "SELECT * FROM bookings WHERE organization_id = $1 ORDER BY data DESC, ora",
                    organization_id,
                )
            return [dict(r) for r in rows]

    async def update_booking_status(self, organization_id, booking_id, stato):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                UPDATE bookings SET stato = $3, updated_at = NOW()
                WHERE organization_id = $1 AND id = $2
                RETURNING *
            """, organization_id, booking_id, stato)
            return dict(row) if row else None

    async def update_booking_details(self, organization_id, booking_id,
                                     nome_cliente, telefono, data, ora,
                                     coperti, note, stato):
        if isinstance(data, str):
            data = date.fromisoformat(data)
        if isinstance(ora, str):
            ore, minuti = ora.split(":")
            ora = time(int(ore), int(minuti))
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                UPDATE bookings SET nome_cliente = $3, telefono = $4,
                    data = $5, ora = $6, coperti = $7, note = $8,
                    stato = $9, updated_at = NOW()
                WHERE organization_id = $1 AND id = $2
                RETURNING *
            """, organization_id, booking_id, nome_cliente, telefono,
                data, ora, coperti, note, stato)
            return dict(row) if row else None

    async def update_booking_payment(self, organization_id, booking_id,
                                      payment_status, session_id=None):
        async with self.pool.acquire() as conn:
            if session_id:
                row = await conn.fetchrow("""
                    UPDATE bookings SET payment_status = $3, payment_link = $4,
                        payment_link_created_at = NOW(), updated_at = NOW()
                    WHERE organization_id = $1 AND id = $2
                    RETURNING *
                """, organization_id, booking_id, payment_status, session_id)
            else:
                row = await conn.fetchrow("""
                    UPDATE bookings SET payment_status = $3, updated_at = NOW()
                    WHERE organization_id = $1 AND id = $2
                    RETURNING *
                """, organization_id, booking_id, payment_status)
            return dict(row) if row else None

    async def list_bookings_by_stato(self, organization_id, stato):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM bookings WHERE organization_id = $1 AND stato = $2 ORDER BY data, ora",
                organization_id, stato,
            )
            return [dict(r) for r in rows]

    async def list_bookings_for_reminder(self, organization_id, target_date):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM bookings
                WHERE organization_id = $1 AND data = $2
                  AND stato = 'confermata' AND reminder_status = 'none'
                ORDER BY ora
            """, organization_id, target_date)
            return [dict(r) for r in rows]

    async def update_booking_reminder_status(self, organization_id, booking_id,
                                              reminder_status, responded_at=None):
        async with self.pool.acquire() as conn:
            if responded_at:
                row = await conn.fetchrow("""
                    UPDATE bookings SET reminder_status = $3,
                        reminder_responded_at = $4, updated_at = NOW()
                    WHERE organization_id = $1 AND id = $2
                    RETURNING *
                """, organization_id, booking_id, reminder_status, responded_at)
            else:
                row = await conn.fetchrow("""
                    UPDATE bookings SET reminder_status = $3, updated_at = NOW()
                    WHERE organization_id = $1 AND id = $2
                    RETURNING *
                """, organization_id, booking_id, reminder_status)
            return dict(row) if row else None

    async def mark_reminder_sent(self, organization_id, booking_id):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                UPDATE bookings SET reminder_status = 'sent',
                    reminder_sent_at = NOW(), updated_at = NOW()
                WHERE organization_id = $1 AND id = $2
                RETURNING *
            """, organization_id, booking_id)
            return dict(row) if row else None

    async def list_reminders_timed_out(self, organization_id, cutoff, min_date):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM bookings
                WHERE organization_id = $1
                  AND reminder_status = 'sent'
                  AND reminder_sent_at <= $2
                  AND data >= $3::date
            """, organization_id, cutoff, min_date)
            return [dict(r) for r in rows]

    async def list_bookings_da_verificare(self, organization_id, target_date):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM bookings
                WHERE organization_id = $1 AND data = $2
                  AND stato = 'confermata'
                  AND completata_at IS NULL AND no_show_at IS NULL
                ORDER BY ora
            """, organization_id, target_date)
            return [dict(r) for r in rows]

    async def upsert_booking_settings_config(self, organization_id, config):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO booking_settings (id, organization_id, config)
                VALUES ($1, $2, $3::jsonb)
                ON CONFLICT (organization_id) DO UPDATE
                    SET config = $3::jsonb, updated_at = NOW()
                RETURNING *
            """, uuid.uuid4(), organization_id, json.dumps(config))
            result = dict(row)
            if isinstance(result.get("config"), str):
                result["config"] = json.loads(result["config"])
            return result

    async def get_booking_settings(self, organization_id):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM booking_settings WHERE organization_id = $1",
                organization_id,
            )
            if row is None:
                return None
            result = dict(row)
            if isinstance(result.get("fasce_orarie"), str):
                result["fasce_orarie"] = json.loads(result["fasce_orarie"])
            if isinstance(result.get("capienze_orarie"), str):
                result["capienze_orarie"] = json.loads(result["capienze_orarie"])
            if isinstance(result.get("config"), str):
                result["config"] = json.loads(result["config"])
            return result

    async def upsert_booking_settings(self, organization_id, fasce_orarie,
                                       capienze_orarie, slot_minutes=60):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO booking_settings (id, organization_id, slot_minutes,
                                              fasce_orarie, capienze_orarie)
                VALUES ($1, $2, $3, $4::jsonb, $5::jsonb)
                ON CONFLICT (organization_id) DO UPDATE
                    SET slot_minutes = $3,
                        fasce_orarie = $4::jsonb,
                        capienze_orarie = $5::jsonb,
                        updated_at = NOW()
                RETURNING *
            """, uuid.uuid4(), organization_id, slot_minutes,
            json.dumps(fasce_orarie), json.dumps(capienze_orarie))
            result = dict(row)
            if isinstance(result.get("fasce_orarie"), str):
                result["fasce_orarie"] = json.loads(result["fasce_orarie"])
            if isinstance(result.get("capienze_orarie"), str):
                result["capienze_orarie"] = json.loads(result["capienze_orarie"])
            return result

    async def check_booking_exists(self, msg_id: str, org_id: str) -> bool:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id FROM bookings WHERE organization_id = $1::uuid AND source_message_id = $2",
                org_id, str(msg_id)
            )
            return bool(row)
