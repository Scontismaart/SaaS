# P0 Blockers Implementation Plan

## P0-1: Broken Booking Idempotency
**Problem**: Booking creation isn't idempotent because it relies on a random `uuid4`. A worker crash leaves the message in the queue but the booking in the DB, causing duplicates.
**Solution**:
1. **DB Migration**: Add a new column and unique index to track the source message instead of relying on `(data, ora)` which is fragile and error-prone for legitimate concurrent bookings.
   ```sql
   ALTER TABLE bookings ADD COLUMN source_message_id VARCHAR(255);
   CREATE UNIQUE INDEX idx_bookings_source_message ON bookings (organization_id, source_message_id) WHERE source_message_id IS NOT NULL;
   ```
2. **`src/core/db/repository.py`**:
   - Update `create_booking` signature to include `source_message_id=None`.
   - Ensure the query safely handles the `UNIQUE` constraint without breaking the outer `async with conn.transaction():` Postgres block.
   - **Crucial**: Use `INSERT ... ON CONFLICT (organization_id, source_message_id) DO NOTHING RETURNING *`. If the returning is empty (it was a duplicate), do a subsequent `SELECT` to fetch the existing booking. Do NOT use `try...except UniqueViolationError` inside the transaction block, as it aborts the Postgres transaction.
3. **`src/core/bookings/service.py`**:
   - Update `BookingService.create_booking` signature to accept `source_message_id=None` and pass it to `self.repo.create_booking`.
4. **`src/whatsapp/inbound_processor.py`**:
   - In `_process_one`, when calling `self.booking_service.create_booking(...)`, pass `source_message_id=str(msg["id"])`.
   - **Integration with P0-2**: If the `BookingService` returns an already existing booking (because this is a retry), skip the LLM generation phase and rely on the outbound idempotency or short-circuit to avoid sending a duplicate "Booking confirmed" message to the customer.
5. **Testing**: Write or update `test_booking_idempotency_on_crash` in `tests/whatsapp/test_inbound_processor.py`.

## P0-2: Premature Message State Update
**Problem**: The worker marks messages as `ai_handled` before sending them to Meta. If the Meta API fails, the message is permanently lost. A naive retry might also re-invoke the LLM, burning money and generating non-deterministic responses.
**Solution**:
1. **`src/whatsapp/inbound_processor.py`**:
   - In `_process_one`, swap the execution order: call `_send_ai_reply` *first*, and only if it succeeds, call `try_mark_replied`.
2. **Outbound Idempotency & Cost Saving (Outbox Pattern)**:
   - *Since Meta's Cloud API does not natively support strict header-based idempotency for standard sends*, we must implement a local outbox or dedup state.
   - **Implementation**: 
     - Before invoking the LLM, check if a generated response already exists for this `msg["id"]` (e.g. in a new `outbound_dedup` table or as a column on `messages`).
     - If it exists, skip the LLM (saving cost) and attempt to resend the cached response.
     - Update the `outbound_dedup` state after a successful HTTP send.
3. **Testing**: Write or update `test_message_retained_on_api_failure` to verify 500 errors from Meta keep the message in a retryable state without regenerating the LLM prompt.

## P0-3: Infinite Cost Vulnerability
**Problem**: The Business tier has `None` for limits, enabling infinite LLM costs. Moreover, a check-then-act race condition in Python allows concurrent workers to bypass the limit.
**Solution**:
1. **`src/core/billing/plans.py`**:
   - Update the `PLANS` dictionary limits to match the specifications:
     - `Starter`: `messages_limit=300` (was 500)
     - `Pro`: `messages_limit=1200` (was 2000)
     - `Business`: `messages_limit=5000` (was None)
2. **Atomic Increment in DB (`src/core/db/repository.py`)**:
   - Implement an atomic check-and-set: `UPDATE organizations SET messages_used_this_period = messages_used_this_period + 1 WHERE id = $1 AND (messages_limit IS NULL OR messages_used_this_period < messages_limit) RETURNING *`.
3. **`src/whatsapp/inbound_processor.py`**:
   - Call the atomic DB increment early in `_process_one`.
   - **UX Handling**: If the DB returns nothing (cap reached), do NOT drop silently. Send a fallback string (e.g., "Stiamo ricevendo troppe richieste, attendi l'operatore") via `_send_ai_reply`, call `try_mark_replied(handling_type="quota_exceeded")`, and escalate to human.
4. **Testing**: Write or update `test_pricing_enforcement_business_tier` to simulate concurrent burst traffic hitting the limit.

## P0-4: No Cancellation UI
**Problem**: Customers cannot cancel subscriptions from the frontend.
**Solution**:
1. **`web/index.html`**:
   - Add a Manage Subscription button in `.topbar-right` right next to the login button:
     ```html
     <button type="button" class="accesso-btn" id="billing-btn" hidden>Gestisci Abbonamento</button>
     ```
2. **`web/app.js`**:
   - Update `aggiornaBottoneAccesso()` to toggle the button visibility based on session state:
     ```javascript
     const billingBtn = document.getElementById("billing-btn");
     if (billingBtn) billingBtn.hidden = !sessione;
     ```
   - Bind a click event listener to the button to trigger the Stripe Customer Portal endpoint:
     ```javascript
     document.getElementById("billing-btn")?.addEventListener("click", async () => {
       try {
         // The backend endpoint is /create-portal-session (verified)
         const res = await apiFetch(`${API_BASE}/api/billing/create-portal-session`, { method: "POST" });
         if (res.ok) {
           const data = await res.json();
           if (data.url) window.location.href = data.url;
         } else {
           alert("Impossibile aprire il portale abbonamenti. Riprova più tardi.");
         }
       } catch (e) {
         console.error("Errore apertura portal billing:", e);
         alert("Errore di connessione.");
       }
     });
     ```
3. **Backend Verification**: The backend endpoints `/api/billing/create-portal-session` and the Stripe webhook `customer.subscription.deleted` are already correctly implemented in `routes.py` and `webhook_handler.py`.
4. **Testing**: Write or update `test_cancellation_downgrades_to_readonly` verifying the UI/API integration.
