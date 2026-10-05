import uuid
from datetime import datetime, timedelta, timezone

from src.core.db.scoping import TenantScopedRepository


class ReviewRepository(TenantScopedRepository):
    """Repository specializzato per Recensioni Google/Manuali, Approvazioni e Sentiment Analytics."""

    _CAMPI_REVIEW_AGGIORNABILI = frozenset({
        "bozza_risposta", "sentiment", "categoria",
        "richiede_revisione_urgente", "stato", "external_id",
        "published_at", "is_anonymized",
    })

    def __init__(self, pool):
        self.pool = pool

    async def create_review(self, organization_id, testo,
                             valutazione_stelle=None, fonte="manuale",
                             autore="", contact_id=None,
                             external_id=None, bozza_risposta="",
                             sentiment="", categoria="",
                             richiede_revisione_urgente=False,
                             stato="nuova"):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO reviews (id, organization_id, contact_id, testo,
                                     valutazione_stelle, fonte, autore,
                                     external_id, bozza_risposta, sentiment,
                                     categoria, richiede_revisione_urgente, stato)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                RETURNING *
            """, uuid.uuid4(), organization_id, contact_id, testo,
            valutazione_stelle, fonte, autore,
            external_id, bozza_risposta, sentiment,
            categoria, richiede_revisione_urgente, stato)
            return dict(row)

    async def get_review(self, organization_id, review_id):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM reviews WHERE organization_id = $1 AND id = $2",
                organization_id, review_id,
            )
            return dict(row) if row else None

    async def get_review_by_external_id(self, organization_id, external_id):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM reviews WHERE organization_id = $1 AND external_id = $2",
                organization_id, external_id,
            )
            return dict(row) if row else None

    async def list_reviews(self, organization_id, stato=None, fonte=None,
                           page=1, limit=20):
        offset = (page - 1) * limit
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT * FROM reviews
                   WHERE organization_id = $1
                     AND ($2::text IS NULL OR stato = $2)
                     AND ($3::text IS NULL OR fonte = $3)
                   ORDER BY created_at DESC LIMIT $4 OFFSET $5""",
                organization_id, stato or None, fonte or None, limit, offset,
            )
            return [dict(r) for r in rows]

    async def count_reviews(self, organization_id, stato=None, fonte=None) -> int:
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                """SELECT COUNT(*) FROM reviews
                   WHERE organization_id = $1
                     AND ($2::text IS NULL OR stato = $2)
                     AND ($3::text IS NULL OR fonte = $3)""",
                organization_id, stato or None, fonte or None,
            )

    async def update_review(self, organization_id, review_id, **kwargs):
        if not kwargs:
            return None
        campi_non_ammessi = set(kwargs) - self._CAMPI_REVIEW_AGGIORNABILI
        if campi_non_ammessi:
            raise ValueError(f"Campi non aggiornabili: {sorted(campi_non_ammessi)}")
        fields = (
            "bozza_risposta", "sentiment", "categoria",
            "richiede_revisione_urgente", "stato", "external_id",
            "published_at", "is_anonymized",
        )
        values = [organization_id, review_id]
        for field in fields:
            values.extend((field in kwargs, kwargs.get(field)))
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE reviews SET
                       bozza_risposta = CASE WHEN $3 THEN $4 ELSE bozza_risposta END,
                       sentiment = CASE WHEN $5 THEN $6 ELSE sentiment END,
                       categoria = CASE WHEN $7 THEN $8 ELSE categoria END,
                       richiede_revisione_urgente = CASE WHEN $9 THEN $10 ELSE richiede_revisione_urgente END,
                       stato = CASE WHEN $11 THEN $12 ELSE stato END,
                       external_id = CASE WHEN $13 THEN $14 ELSE external_id END,
                       published_at = CASE WHEN $15 THEN $16 ELSE published_at END,
                       is_anonymized = CASE WHEN $17 THEN $18 ELSE is_anonymized END
                   WHERE organization_id = $1 AND id = $2
                   RETURNING *""",
                *values,
            )
            return dict(row) if row else None

    async def approve_review(self, organization_id, review_id):
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT * FROM reviews WHERE organization_id = $1 AND id = $2 FOR UPDATE",
                    organization_id, review_id,
                )
                if row is None:
                    return None
                review = dict(row)
                if review["stato"] == "pubblicata":
                    return review
                updated = await conn.fetchrow(
                    "UPDATE reviews SET stato = 'approvata' WHERE organization_id = $1 AND id = $2 RETURNING *",
                    organization_id, review_id,
                )
                return dict(updated)

    async def get_review_analytics(self, organization_id, giorni=90):
        cutoff = datetime.now(timezone.utc) - timedelta(days=giorni)
        async with self.pool.acquire() as conn:
            sentiment_trend = await conn.fetch("""
                SELECT DATE(created_at) AS giorno,
                       sentiment,
                       COUNT(*) AS cnt
                FROM reviews
                WHERE organization_id = $1
                  AND created_at >= $2
                  AND is_anonymized = FALSE
                GROUP BY giorno, sentiment
                ORDER BY giorno
            """, organization_id, cutoff)
            star_dist = await conn.fetch("""
                SELECT valutazione_stelle, COUNT(*) AS cnt
                FROM reviews
                WHERE organization_id = $1
                  AND created_at >= $2
                GROUP BY valutazione_stelle
                ORDER BY valutazione_stelle
            """, organization_id, cutoff)
            cat_dist = await conn.fetch("""
                SELECT categoria, COUNT(*) AS cnt
                FROM reviews
                WHERE organization_id = $1
                  AND created_at >= $2
                  AND categoria != ''
                GROUP BY categoria
                ORDER BY cnt DESC
            """, organization_id, cutoff)
            fonte_dist = await conn.fetch("""
                SELECT fonte, COUNT(*) AS cnt
                FROM reviews
                WHERE organization_id = $1
                  AND created_at >= $2
                GROUP BY fonte
                ORDER BY cnt DESC
            """, organization_id, cutoff)
            return {
                "sentiment_trend": [dict(r) for r in sentiment_trend],
                "star_distribution": [dict(r) for r in star_dist],
                "category_distribution": [dict(r) for r in cat_dist],
                "source_distribution": [dict(r) for r in fonte_dist],
            }
