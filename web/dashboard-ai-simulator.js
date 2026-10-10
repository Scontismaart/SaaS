(function attachDashboardAiSimulator(root, factory) {
  const api = factory(root);
  if (root) root.MelpisDashboardAiSimulator = api;
})(typeof window !== "undefined" ? window : globalThis, function createDashboardAiSimulator(root) {
  "use strict";
  return Object.freeze({
    create(deps) {
      const { API_BASE, apiFetch, PROFILO_ID, getContext,
        aggiornaRiepilogo, aggiornaPrioritari, aggiornaReport,
        aggiornaPrenotazioni, aggiornaSemaforo, aggiornaNotifiche } = deps;
      const document = root.document;
      const crypto = root.crypto;
      const chatBody = document.getElementById("chat-body");
      const chatForm = document.getElementById("chat-form");
      const chatInput = document.getElementById("chat-input");
      const chatSuggestions = document.getElementById("chat-suggestions");
      const chatStatus = document.getElementById("chat-status");
      const originalChatHtml = chatBody.innerHTML;
      const originalStatus = chatStatus.textContent;
      const controls = [chatInput, ...chatForm.querySelectorAll("button"), ...chatSuggestions.querySelectorAll("button")];
      let active = false;
      let destroyed = false;
      let epoch = 0;
      let entryScope = null;
      let conversationId = null;
      let pendingMessage = false;
      let controlStates = null;

      function scopeKey() {
        const context = getContext();
        return JSON.stringify([context?.userId, context?.sessionOrganizationId, context?.selectedOrganizationId]);
      }

      function capture() { return { context: getContext(), epoch }; }

      function current(token) {
        const now = getContext();
        return active && !destroyed && token.epoch === epoch && now?.view === "assistente"
          && now?.userId && now?.sessionOrganizationId
          && JSON.stringify(now) === JSON.stringify(token.context);
      }

      function disableControls() {
        if (!controlStates) controlStates = controls.map((control) => ({ control, disabled: control.disabled }));
        controls.forEach((control) => { control.disabled = true; });
      }

      function restoreControls(clear = false) {
        controlStates?.forEach(({ control, disabled }) => { control.disabled = disabled; });
        if (clear) controlStates = null;
      }

      function clearTransient() {
        epoch += 1;
        rimuoviTyping();
        chatStatus.textContent = originalStatus;
        restoreControls();
      }

      function clearPrivateDOM() {
        chatBody.innerHTML = originalChatHtml;
        chatInput.value = "";
        conversationId = null;
      }

      function aggiungiBollaChat({ testo, mittente, escalation = false, categoria = null }) {
        const bubble = document.createElement("div");
        bubble.classList.add("bubble");
        if (mittente === "cliente") bubble.classList.add("bubble-out");
        else {
          bubble.classList.add("bubble-ai");
          if (escalation) bubble.classList.add("escalated");
        }
        const p = document.createElement("p");
        p.textContent = testo;
        bubble.appendChild(p);
        if (mittente === "ai") {
          const tag = document.createElement("span");
          tag.classList.add("bubble-tag");
          tag.textContent = escalation
            ? "Segnalato a un umano"
            : `Gestito dall'assistente${categoria ? " \u00b7 " + categoria : ""}`;
          bubble.appendChild(tag);
        }
        chatBody.appendChild(bubble);
        chatBody.scrollTop = chatBody.scrollHeight;
      }

      function mostraTyping() {
        const typing = document.createElement("div");
        typing.classList.add("bubble-typing");
        typing.id = "typing-indicator";
        typing.innerHTML = "<span></span><span></span><span></span>";
        chatBody.appendChild(typing);
        chatBody.scrollTop = chatBody.scrollHeight;
      }

      function rimuoviTyping() {
        document.getElementById("typing-indicator")?.remove();
      }

      async function inviaMessaggio(testo) {
        const token = capture();
        if (!current(token) || pendingMessage) return;
        const message = testo.trim();
        if (!message) return;
        pendingMessage = true;
        disableControls();
        aggiungiBollaChat({ testo: message, mittente: "cliente" });
        chatStatus.textContent = "sta scrivendo\u2026";
        mostraTyping();
        try {
          const res = await apiFetch(`${API_BASE}/api/messaggio?profilo_id=${PROFILO_ID}`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "Idempotency-Key": crypto.randomUUID(),
            },
            body: JSON.stringify({
              testo: message,
              id_conversazione: conversationId ||= crypto.randomUUID(),
            }),
          });
          if (!current(token)) return;
          rimuoviTyping();
          if (!res.ok) {
            const errBody = await res.json().catch(() => null);
            if (!current(token)) return;
            throw new Error(errBody?.detail || `Errore HTTP ${res.status}`);
          }
          const data = await res.json();
          if (!current(token)) return;
          aggiungiBollaChat({
            testo: data.risposta,
            mittente: "ai",
            escalation: data.richiede_umano,
            categoria: data.categoria,
          });
          await aggiornaRiepilogo();
          if (!current(token)) return;
          await aggiornaPrioritari();
          if (!current(token)) return;
          await aggiornaReport();
          if (!current(token)) return;
          await aggiornaPrenotazioni();
          if (!current(token)) return;
          await aggiornaSemaforo();
          if (!current(token)) return;
          await aggiornaNotifiche();
          if (!current(token)) return;
        } catch (err) {
          if (current(token)) {
            rimuoviTyping();
            aggiungiBollaChat({
              testo: "Non riesco a contattare il server dell'assistente.",
              mittente: "ai",
              escalation: true,
              categoria: "errore tecnico",
            });
          }
        } finally {
          pendingMessage = false;
          restoreControls(true);
          if (current(token)) {
            rimuoviTyping();
            chatStatus.textContent = originalStatus;
          }
        }
      }

      chatForm.addEventListener("submit", (e) => {
        e.preventDefault();
        const testo = chatInput.value.trim();
        if (!testo || pendingMessage) return;
        chatInput.value = "";
        inviaMessaggio(testo);
      });

      chatSuggestions.addEventListener("click", (e) => {
        const chip = e.target.closest(".suggestion-chip");
        if (!chip || pendingMessage) return;
        inviaMessaggio(chip.textContent);
      });

      return Object.freeze({
        onEnter() {
          if (destroyed) return;
          const scope = scopeKey();
          if (entryScope !== null && entryScope !== scope) {
            clearTransient();
            clearPrivateDOM();
          }
          entryScope = scope;
          active = true;
          if (pendingMessage) disableControls();
        },
        onExit() { active = false; clearTransient(); },
        invalidate() { active = false; destroyed = true; clearTransient(); clearPrivateDOM(); },
      });
    },
  });
});
