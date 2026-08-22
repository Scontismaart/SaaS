# Architect Addendum: P0 Blockers Implementation v2

## 1. Approval and Conceptual Review
The `P0_implementation_plan_v2.md` is conceptually approved. The approach to use a single explicit database transaction (`SELECT ... FOR UPDATE` combined with atomic quota increments) fundamentally resolves the root causes of the concurrency and double-billing issues (P0-1, P0-2, P0-3) identified in v1. 

By pushing the synchronization logic down to the Postgres level, we ensure exactly-once processing semantics without brittle Python-level locks. 

## 2. Definitive SQL Migration Logic
The following SQL must be added to a new Alembic/migration file to apply the schema changes from §1.

```sql
-- Migration: Add messaging state tracking and idempotency 
ALTER TABLE messages
  ADD COLUMN billed_at TIMESTAMPTZ,
  ADD COLUMN ai_reply_cache TEXT,
  ADD COLUMN ai_reply_generated_at TIMESTAMPTZ,
  ADD COLUMN sent_at TIMESTAMPTZ,
  ADD COLUMN meta_message_id VARCHAR(255),
  ADD COLUMN quota_exceeded_at TIMESTAMPTZ;

-- Note: Ensure that bookings table has source_message_id if not already present
-- ALTER TABLE bookings ADD COLUMN source_message_id VARCHAR(255);
```

## 3. Updated Python Function Signatures & Pseudo-Code

### `repository.py`

```python
class MessageRepository:
    
    async def claim_message_and_check_quota(self, msg_id: str, org_id: str) -> dict:
        """
        Executes Steps 1-5 of the plan inside a SINGLE transaction.
        
        Uses SELECT ... FOR UPDATE to lock the message row.
        Atomically checks and increments org quota if not billed.
        
        Returns a dictionary indicating the action to take:
        {
            "status": "already_sent" | "quota_exceeded" | "claimed",
            "ai_reply_cache": Optional[str],
        }
        """
        # BEGIN TRANSACTION
        # SELECT ... FROM messages WHERE id = msg_id FOR UPDATE
        # IF sent_at IS NOT NULL: return {"status": "already_sent"}
        # IF billed_at IS NULL:
        #     UPDATE organizations SET messages_used_this_period = messages_used_this_period + 1 
        #         WHERE id = org_id AND messages_used_this_period < limit RETURNING messages_used_this_period
        #     IF 0 rows returned: 
        #         UPDATE messages SET quota_exceeded_at = now() WHERE id = msg_id
        #         return {"status": "quota_exceeded"}
        #     UPDATE messages SET billed_at = now() WHERE id = msg_id
        # COMMIT TRANSACTION
        # return {"status": "claimed", "ai_reply_cache": <cache>}
        pass

    async def check_booking_exists(self, msg_id: str, org_id: str) -> bool:
        """
        Integration for P0-1 (Idempotency).
        Checks if a booking has already been created for this source_message_id.
        """
        pass
        
    async def save_ai_reply(self, msg_id: str, reply: str) -> None:
        """
        Saves the expensive AI reply to the DB (Step 6).
        """
        # UPDATE messages SET ai_reply_cache = reply, ai_reply_generated_at = now() 
        # WHERE id = msg_id
        pass
        
    async def mark_message_sent(self, msg_id: str, meta_message_id: str) -> None:
        """
        Marks message as finally delivered to Meta (Step 7).
        """
        # UPDATE messages SET sent_at = now(), meta_message_id = meta_message_id 
        # WHERE id = msg_id
        pass
```

### `inbound_processor.py`

```python
async def _process_one(msg_id: str, org_id: str, ...):
    # Step 1-5: Atomic DB lock and quota claim
    claim_result = await repo.claim_message_and_check_quota(msg_id, org_id)
    
    if claim_result["status"] == "already_sent":
        # Message handled in a previous run. Done.
        return 
        
    if claim_result["status"] == "quota_exceeded":
        # Step 5 UX: Send generic fallback directly (bypass AI) & notify human
        await send_quota_exceeded_fallback(msg_id, org_id)
        return
        
    # Step 6: AI Reply Logic
    ai_reply = claim_result.get("ai_reply_cache")
    if not ai_reply:
        # P0-1 Check: Was this a booking message that crashed after booking creation?
        if await repo.check_booking_exists(msg_id, org_id):
            ai_reply = generate_standard_booking_confirmation()
        else:
            # Perform expensive AI call outside of DB transactions
            ai_reply = await genera_risposta_ai(...)
            await repo.save_ai_reply(msg_id, ai_reply)
            
    # Step 7: Send to Meta
    # Network call outside of DB transactions
    meta_result = await invia_a_meta(ai_reply, msg_id)
    if meta_result.success:
        await repo.mark_message_sent(msg_id, meta_result.id)
        # try_mark_replied(msg_id)  # Maintain original mark_replied behavior
    else:
        # Meta failed. Do nothing, leaving sent_at as NULL.
        # Next retry will claim the message, see billed_at is set, skip billing,
        # see ai_reply_cache is set, skip AI, and retry Meta directly.
        pass
```
