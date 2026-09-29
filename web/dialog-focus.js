(() => {
  const returnTargets = new WeakMap();
  const focusableSelector = [
    "a[href]",
    "button:not([disabled])",
    "input:not([disabled])",
    "select:not([disabled])",
    "textarea:not([disabled])",
    "[tabindex]:not([tabindex='-1'])",
  ].join(",");

  function dialogWithin(container) {
    if (container.matches("[role='dialog'], [role='alertdialog']")) return container;
    return container.querySelector("[role='dialog'], [role='alertdialog']");
  }

  function focusableWithin(dialog) {
    return [...dialog.querySelectorAll(focusableSelector)].filter((element) => (
      !element.hidden
      && !element.closest("[hidden]")
      && element.getAttribute("aria-hidden") !== "true"
      && element.tabIndex >= 0
    ));
  }

  function open(container, { restoreTarget = document.activeElement, initialFocus = null } = {}) {
    const dialog = dialogWithin(container);
    if (!dialog) return;
    returnTargets.set(container, restoreTarget);
    container.hidden = false;
    const target = initialFocus || dialog.querySelector("[autofocus]") || focusableWithin(dialog)[0] || dialog;
    target.focus({ preventScroll: true });
  }

  function close(container, { restoreFocus = true, fallbackFocus = null } = {}) {
    container.hidden = true;
    const returnTarget = returnTargets.get(container);
    returnTargets.delete(container);
    if (!restoreFocus) return;

    const target = returnTarget && returnTarget.isConnected && !returnTarget.closest("[hidden]")
      ? returnTarget
      : fallbackFocus;
    if (target && target.isConnected && !target.disabled && !target.closest("[hidden]")) {
      target.focus({ preventScroll: true });
    }
  }

  function handleKeydown(container, event, onEscape) {
    const dialog = dialogWithin(container);
    if (!dialog) return;
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      onEscape();
      return;
    }
    if (event.key !== "Tab") return;

    const elements = focusableWithin(dialog);
    if (!elements.length) {
      event.preventDefault();
      return;
    }
    const first = elements[0];
    const last = elements[elements.length - 1];
    if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && (document.activeElement === last || !dialog.contains(document.activeElement))) {
      event.preventDefault();
      first.focus();
    }
  }

  window.MelpisDialogFocus = Object.freeze({ open, close, handleKeydown });
})();
