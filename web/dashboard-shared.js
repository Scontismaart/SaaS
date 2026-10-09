(function (root) {
  "use strict";

  function escapeHtml(str) {
    return String(str == null ? "" : str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function sanitize(v) {
    if (typeof root.DOMPurify !== "undefined" && typeof root.DOMPurify.sanitize === "function") {
      return root.DOMPurify.sanitize(v == null ? "" : String(v));
    }
    return escapeHtml(v);
  }

  function toast(messaggio, tipo = "info", durata = 4200, azione = null) {
    let container = root.document.getElementById("toast-container");
    if (!container) {
      container = root.document.createElement("div");
      container.id = "toast-container";
      container.setAttribute("role", "status");
      container.setAttribute("aria-live", "polite");
      root.document.body.appendChild(container);
    }
    const el = root.document.createElement("div");
    el.className = `toast toast-${tipo}`;

    const textSpan = root.document.createElement("span");
    textSpan.textContent = messaggio;
    el.appendChild(textSpan);

    if (azione && azione.testo && typeof azione.onClick === "function") {
      const actionBtn = root.document.createElement("button");
      actionBtn.type = "button";
      actionBtn.className = "toast-action-btn";
      actionBtn.textContent = azione.testo;
      actionBtn.style.marginLeft = "8px";
      actionBtn.style.textDecoration = "underline";
      actionBtn.style.fontWeight = "600";
      actionBtn.style.cursor = "pointer";
      actionBtn.style.background = "transparent";
      actionBtn.style.border = "none";
      actionBtn.style.color = "inherit";
      actionBtn.style.font = "inherit";
      actionBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        azione.onClick();
        el.remove();
      });
      el.appendChild(actionBtn);
    }

    container.appendChild(el);
    root.requestAnimationFrame(() => el.classList.add("toast-in"));
    root.setTimeout(() => {
      el.classList.remove("toast-in");
      root.setTimeout(() => el.remove(), 320);
    }, durata);
  }

  function confirmDestructive({ titolo = "Conferma azione", descrizione = "", label = "Conferma" } = {}) {
    return new Promise((resolve) => {
      const modal = root.document.getElementById("confirm-modal");
      const titleEl = root.document.getElementById("confirm-title");
      const descEl = root.document.getElementById("confirm-desc");
      const okBtn = root.document.getElementById("confirm-ok-btn");
      const cancelBtn = root.document.getElementById("confirm-cancel-btn");
      if (!modal || !okBtn || !cancelBtn) {
        resolve(root.confirm(descrizione || titolo));
        return;
      }
      titleEl.textContent = titolo;
      descEl.textContent = descrizione;
      okBtn.textContent = label;
      if (root.MelpisDialogFocus) {
        root.MelpisDialogFocus.open(modal, { initialFocus: okBtn });
      } else {
        modal.hidden = false;
        okBtn.focus();
      }

      const chiudi = (esito) => {
        if (root.MelpisDialogFocus) root.MelpisDialogFocus.close(modal);
        else modal.hidden = true;
        okBtn.removeEventListener("click", onOk);
        cancelBtn.removeEventListener("click", onCancel);
        modal.removeEventListener("keydown", onKey);
        resolve(esito);
      };
      function onOk() { chiudi(true); }
      function onCancel() { chiudi(false); }
      function onKey(e) {
        if (e.key === "Escape") {
          e.stopPropagation();
          chiudi(false);
        } else if (e.key === "Tab") {
          e.preventDefault();
          (root.document.activeElement === okBtn ? cancelBtn : okBtn).focus();
        }
      }
      okBtn.addEventListener("click", onOk);
      cancelBtn.addEventListener("click", onCancel);
      modal.addEventListener("keydown", onKey);
    });
  }

  function toDateKey(d) {
    if (typeof d === "string" && /^\d{4}-\d{2}-\d{2}$/.test(d)) return d;
    const date = d instanceof root.Date ? d : new root.Date(d);
    if (isNaN(date.getTime())) return "";
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  }

  root.MelpisDashboardShared = Object.freeze({ escapeHtml, sanitize, toast, confirmDestructive, toDateKey });
})(window);
