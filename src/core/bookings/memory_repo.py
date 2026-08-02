"""InMemoryBookingRepo — fallback per demo mode (nessun database).

Implementa i metodi di CoreRepository che BookingService usa nel flusso
dashboard (list, create, settings, semaforo). La logica di calcolo della
disponibilita' resta in BookingService: questo repo fornisce solo lo stato
in-memory con gli stessi tipi (date/time) della controparte PostgreSQL.

Nota: confirm/mark_no_show/mark_completed accedono a repo.pool direttamente
e non sono coperti qui — non fanno parte del percorso frontend demo.
"""

import uuid
from datetime import date, time
from copy import deepcopy


SLOT_ORE = [f"{h:02d}:00" for h in range(24)]


class InMemoryBookingRepo:
    def __init__(self):
        self._bookings: list[dict] = []
        self._settings: dict[str, dict] = {}
        self.pool = None

    # ── Bookings ──────────────────────────────────────────────

    async def create_booking(self, organization_id, nome_cliente, data, ora, coperti,
                             telefono="", note="", stato="in_attesa", origine="Dashboard",
                             richiede_intervento=False, id_conversazione=None,
                             contact_id=None, richiede_deposito=False,
                             completata_at=None, tipo_evento=""):
        if isinstance(data, str):
            data = date.fromisoformat(data)
        if isinstance(ora, str):
            ore, minuti = ora.split(":")
            ora = time(int(ore), int(minuti))
        booking = {
            "id": uuid.uuid4(),
            "organization_id": organization_id,
            "contact_id": contact_id,
            "nome_cliente": nome_cliente,
            "telefono": telefono,
            "data": data,
            "ora": ora,
            "coperti": coperti,
            "note": note,
            "stato": stato,
            "origine": origine,
            "richiede_intervento": richiede_intervento,
            "id_conversazione": id_conversazione,
            "richiede_deposito": richiede_deposito,
            "completata_at": completata_at,
            "tipo_evento": tipo_evento,
        }
        self._bookings.append(booking)
        return deepcopy(booking)

    async def get_booking(self, organization_id, booking_id):
        for b in self._bookings:
            if b["organization_id"] == organization_id and str(b["id"]) == str(booking_id):
                return deepcopy(b)
        return None

    async def list_bookings(self, organization_id, data=None):
        if data is not None and isinstance(data, str):
            data = date.fromisoformat(data)
        rows = [
            b for b in self._bookings
            if b["organization_id"] == organization_id
            and (data is None or b["data"] == data)
        ]
        rows.sort(key=lambda b: (b["data"], b["ora"]))
        return [deepcopy(b) for b in rows]

    async def list_bookings_by_stato(self, organization_id, stato):
        rows = [
            b for b in self._bookings
            if b["organization_id"] == organization_id and b["stato"] == stato
        ]
        rows.sort(key=lambda b: (b["data"], b["ora"]))
        return [deepcopy(b) for b in rows]

    async def update_booking_status(self, organization_id, booking_id, stato):
        for b in self._bookings:
            if b["organization_id"] == organization_id and str(b["id"]) == str(booking_id):
                b["stato"] = stato
                return deepcopy(b)
        return None

    async def update_booking_reminder_status(self, organization_id, booking_id,
                                             reminder_status, responded_at=None):
        for b in self._bookings:
            if b["organization_id"] == organization_id and str(b["id"]) == str(booking_id):
                b["reminder_status"] = reminder_status
                if responded_at:
                    b["reminder_responded_at"] = responded_at
                return deepcopy(b)
        return None

    # ── Booking settings ──────────────────────────────────────

    async def get_booking_settings(self, organization_id):
        return deepcopy(self._settings.get(str(organization_id))) if self._settings.get(str(organization_id)) else None

    async def upsert_booking_settings(self, organization_id, fasce_orarie=None,
                                      capienze_orarie=None):
        key = str(organization_id)
        current = deepcopy(self._settings.get(key)) or {
            "fasce_orarie": SLOT_ORE,
            "capienze_orarie": {f: 40 for f in SLOT_ORE},
            "config": {},
        }
        current["fasce_orarie"] = fasce_orarie or SLOT_ORE
        current["capienze_orarie"] = capienze_orarie or {f: 40 for f in SLOT_ORE}
        self._settings[key] = current
        return deepcopy(current)

    async def upsert_booking_settings_config(self, organization_id, config):
        key = str(organization_id)
        current = deepcopy(self._settings.get(key)) or {
            "fasce_orarie": SLOT_ORE,
            "capienze_orarie": {f: 40 for f in SLOT_ORE},
            "config": {},
        }
        current["config"] = config or {}
        self._settings[key] = current
        return deepcopy(current)
