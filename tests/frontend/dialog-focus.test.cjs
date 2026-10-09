const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const { JSDOM } = require("jsdom");

const focusSource = fs.readFileSync("web/dialog-focus.js", "utf8");
const appSource = fs.readFileSync("web/app.js", "utf8");
const sharedSource = fs.readFileSync("web/dashboard-shared.js", "utf8");
const pageSource = fs.readFileSync("web/index.html", "utf8");

test("dashboard dialogs manage initial focus, keyboard loop, Escape, and focus return", () => {
  const dom = new JSDOM(`
    <button id="trigger">Open</button>
    <div id="modal" hidden>
      <section role="dialog" aria-modal="true" aria-labelledby="title">
        <h2 id="title">Dialog</h2>
        <button id="first">First</button>
        <button id="hidden" hidden>Hidden</button>
        <button id="last">Last</button>
      </section>
    </div>
  `, { runScripts: "outside-only" });
  dom.window.eval(focusSource);

  const { document, MelpisDialogFocus } = dom.window;
  const trigger = document.getElementById("trigger");
  const modal = document.getElementById("modal");
  const first = document.getElementById("first");
  const last = document.getElementById("last");
  trigger.focus();

  MelpisDialogFocus.open(modal);
  assert.equal(modal.hidden, false);
  assert.equal(document.activeElement, first);

  last.focus();
  const tab = new dom.window.KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true });
  MelpisDialogFocus.handleKeydown(modal, tab, () => MelpisDialogFocus.close(modal));
  assert.equal(tab.defaultPrevented, true);
  assert.equal(document.activeElement, first);

  const escape = new dom.window.KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true });
  MelpisDialogFocus.handleKeydown(modal, escape, () => MelpisDialogFocus.close(modal));
  assert.equal(modal.hidden, true);
  assert.equal(document.activeElement, trigger);

  MelpisDialogFocus.open(modal);
  first.focus();
  const shiftTab = new dom.window.KeyboardEvent("keydown", {
    key: "Tab", shiftKey: true, bubbles: true, cancelable: true,
  });
  MelpisDialogFocus.handleKeydown(modal, shiftTab, () => MelpisDialogFocus.close(modal));
  assert.equal(shiftTab.defaultPrevented, true);
  assert.equal(document.activeElement, last);
  dom.window.close();
});

test("dashboard booking and confirmation dialogs use the focus manager", () => {
  assert.match(pageSource, /<script src="\/app\/dialog-focus\.js"><\/script>[\s\S]*?<script src="\/app\/app\.js/);
  assert.match(appSource, /MelpisDialogFocus\.handleKeydown\(modal, event/);
  assert.match(appSource, /MelpisDialogFocus\.open\(bookingModal\)/);
  assert.match(appSource, /MelpisDialogFocus\.close\(bookingModal\)/);
  assert.match(sharedSource, /MelpisDialogFocus\.open\(modal, \{ initialFocus: okBtn \}\)/);
});

test("dashboard text controls expose translated accessible names", () => {
  const document = new JSDOM(pageSource).window.document;
  const controls = {
    "review-text": "dashboard:reviews.text_placeholder",
    "review-search-input": "dashboard:reviews.search_placeholder",
    "review-filter-source": "dashboard:reviews.all_sources",
    "doc-query": "dashboard:knowledge.ask_placeholder",
    "ai-cfg-new-rule-input": "settings:ai_configuration.new_rule_placeholder",
  };
  for (const [id, key] of Object.entries(controls)) {
    assert.equal(document.getElementById(id)?.getAttribute("data-i18n-aria"), key, `${id} has a translated accessible name`);
  }
});

test("knowledge tabs support arrow, Home, and End keyboard navigation", () => {
  const source = appSource.match(/function gestisciNavigazioneTabConoscenza\(event\) \{[\s\S]*?\n\}/)?.[0];
  assert.ok(source, "the dashboard must provide keyboard navigation for knowledge tabs");
  const dom = new JSDOM(`
    <div role="tablist">
      <button class="kb-tab-btn" role="tab" data-kb-tab="faq" tabindex="0">FAQ</button>
      <button class="kb-tab-btn" role="tab" data-kb-tab="documenti" tabindex="-1">Documents</button>
      <button class="kb-tab-btn" role="tab" data-kb-tab="web" tabindex="-1">Web</button>
      <button class="kb-tab-btn" role="tab" data-kb-tab="dati-struttura" tabindex="-1">Business data</button>
    </div>
  `, { runScripts: "outside-only" });
  const { document } = dom.window;
  const tabs = [...document.querySelectorAll(".kb-tab-btn[data-kb-tab]")];
  let activeTab = tabs[0].dataset.kbTab;
  const activate = (key) => {
    activeTab = key;
    tabs.forEach((tab) => {
      const active = tab.dataset.kbTab === key;
      tab.tabIndex = active ? 0 : -1;
      tab.setAttribute("aria-selected", String(active));
    });
  };
  const handler = vm.runInNewContext(`${source}; gestisciNavigazioneTabConoscenza`, {
    document,
    impostaTabConoscenza: activate,
  });
  const press = (key, currentTarget) => {
    const event = { key, currentTarget, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; } };
    handler(event);
    return event;
  };

  assert.equal(press("ArrowRight", tabs[0]).defaultPrevented, true);
  assert.equal(activeTab, "documenti");
  assert.equal(document.activeElement, tabs[1]);
  press("ArrowLeft", tabs[0]);
  assert.equal(activeTab, "dati-struttura", "left arrow wraps from the first tab to the last");
  press("End", tabs[0]);
  assert.equal(activeTab, "dati-struttura");
  press("Home", tabs[3]);
  assert.equal(activeTab, "faq");
  assert.equal(tabs.filter((tab) => tab.tabIndex === 0).length, 1);
  dom.window.close();
});
