const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");

const root = path.resolve(__dirname, "../..");
const html = fs.readFileSync(path.join(root, "web/index.html"), "utf8");
const sharedSource = fs.readFileSync(path.join(root, "web/dashboard-shared.js"), "utf8");
const dialogFocusSource = fs.readFileSync(path.join(root, "web/dialog-focus.js"), "utf8");
const source = fs.readFileSync(path.join(root, "web/dashboard-team.js"), "utf8");

function deferred() {
  let resolve;
  const promise = new Promise((yes) => { resolve = yes; });
  return { promise, resolve };
}

function response(status, body) {
  return { status, ok: status >= 200 && status < 300, async json() { return body; } };
}

function fixture(apiFetch, { role = "owner", userId = "user-1", organizationId = "org-1",
  useSharedConfirmation = false } = {}) {
  const dom = new JSDOM(html, { url: "https://melpis.test/app/team", runScripts: "outside-only" });
  const { window } = dom;
  const context = {
    userId, sessionOrganizationId: organizationId, selectedOrganizationId: organizationId,
    view: "team", transition: 1, epoch: 1,
  };
  const requests = [];
  const toasts = [];
  let confirmResult = Promise.resolve(true);
  window.eval(dialogFocusSource);
  const trackedApiFetch = (url, options = {}) => {
    const promise = apiFetch(url, options);
    requests.push({ url, options, promise });
    return promise;
  };
  window.eval(sharedSource);
  window.eval(source);
  const module = window.MelpisDashboardTeam.create({
    API_BASE: "",
    apiFetch: trackedApiFetch,
    _escapeHtml: window.MelpisDashboardShared.escapeHtml,
    _tDash: (_key, fallback, values = {}) => Object.entries(values).reduce(
      (text, [key, value]) => text.replaceAll(`{{${key}}}`, String(value)), fallback,
    ),
    localeCorrente: () => "it-IT",
    toast: (...args) => toasts.push(args),
    confermaDestructiva: (...args) => {
      fixture.lastConfirmation = args;
      return useSharedConfirmation ? window.MelpisDashboardShared.confirmDestructive(...args) : confirmResult;
    },
    _estraiMessaggioErroreApi: (_res, data, fallback) => data?.detail || fallback,
    getContext: () => ({ ...context }),
    getSession: () => ({ user_id: context.userId, organization_id: context.sessionOrganizationId, ruolo: role }),
    apriView() {},
  });
  return {
    dom, window, document: window.document, context, module, requests, toasts,
    setConfirmResult(value) { confirmResult = value; },
  };
}

const membersData = (members = []) => ({ members, total: members.length, users_limit: 10, can_add_more: true });
const owner = { user_id: "owner-1", nome: "Titolare", email: "owner@example.test", ruolo: "owner", joined_at: null };
const staff = { user_id: "staff-1", nome: "Staff Uno", email: "staff@example.test", ruolo: "staff", joined_at: null };
const manager = { user_id: "manager-1", nome: "Manager Uno", email: "manager@example.test", ruolo: "manager", joined_at: null };

async function settle() {
  for (let index = 0; index < 16; index += 1) await Promise.resolve();
}

async function loadTeam(h) {
  const loading = h.module.caricaTeam();
  await Promise.all(h.requests.map((request) => request.promise));
  await loading;
  await settle();
}

function standardApi(members = [owner, manager, staff]) {
  return async (url) => {
    if (url === "/api/team/organizations") return response(200, { organizations: [{ id: "org-1", name: "Org One" }] });
    if (url === "/api/team/invitations") return response(200, { invitations: [] });
    if (url === "/api/team/members") return response(200, membersData(members));
    return response(500, { detail: "unexpected request" });
  };
}

test("Team renders role-specific controls for owner, manager, and staff", async (t) => {
  for (const role of ["owner", "manager", "staff"]) {
    const h = fixture(standardApi(), { role });
    t.after(() => h.dom.window.close());
    h.module.onEnter();
    await loadTeam(h);
    assert.equal(h.document.querySelectorAll("#team-members-tbody tr[data-user-id]").length, 3);
    if (role === "owner") {
      assert.ok(h.document.querySelector("#team-members-tbody .team-change-role"));
      assert.ok(h.document.querySelector("#team-members-tbody .team-delete-btn"));
      assert.notEqual(h.document.getElementById("team-add-card").style.display, "none");
    } else if (role === "manager") {
      assert.equal(h.document.querySelector("#team-members-tbody .team-change-role"), null);
      assert.ok(h.document.querySelector("#team-members-tbody .team-delete-btn"), "manager may manage staff members");
      assert.equal(h.document.querySelector('#team-add-ruolo option[value="manager"]').disabled, true);
    } else {
      assert.equal(h.document.querySelector("#team-members-tbody .team-delete-btn"), null);
      assert.equal(h.document.querySelector("#team-members-tbody .team-change-role"), null);
      assert.equal(h.document.getElementById("team-add-card").style.display, "none");
    }
  }
});

test("Team keeps denied and MFA-required mutations from showing success", async (t) => {
  for (const denied of [
    response(401, { detail: "session expired" }),
    response(403, { detail: "organization denied" }),
    response(403, { detail: "MFA required", code: "mfa_required" }),
  ]) {
    let mutationCalls = 0;
    const h = fixture(async (url, options = {}) => {
      if (url === "/api/team/organizations") return response(200, { organizations: [{ id: "org-1", name: "Org One" }] });
      if (url === "/api/team/invitations") return response(200, { invitations: [] });
      if (url === "/api/team/members" && options.method !== "PATCH") return response(200, membersData([owner, staff]));
      mutationCalls += 1;
      return denied;
    });
    t.after(() => h.dom.window.close());
    h.module.onEnter();
    await loadTeam(h);
    const roleSelect = h.document.querySelector('.team-change-role[data-user-id="staff-1"]');
    assert.ok(roleSelect, "owner has the role control");
    roleSelect.value = "manager";
    roleSelect.dispatchEvent(new h.window.Event("change", { bubbles: true }));
    await Promise.all(h.requests.map((request) => request.promise));
    await settle();
    assert.equal(mutationCalls, 1);
    assert.equal(h.toasts.some((toast) => toast[1] === "success"), false);
  }
});

test("Team invite submit is single-flight while a request is pending", async (t) => {
  const pendingInvite = deferred();
  let inviteCalls = 0;
  const h = fixture(async (url, options = {}) => {
    if (url === "/api/team/organizations") return response(200, { organizations: [{ id: "org-1", name: "Org One" }] });
    if (url === "/api/team/invitations") return response(200, { invitations: [] });
    if (url === "/api/team/members" && options.method !== "POST") return response(200, membersData([owner]));
    inviteCalls += 1;
    return pendingInvite.promise;
  });
  t.after(() => h.dom.window.close());
  h.module.onEnter();
  await loadTeam(h);
  h.document.getElementById("team-add-email").value = "new@example.test";
  const form = h.document.getElementById("team-add-form");
  form.dispatchEvent(new h.window.Event("submit", { bubbles: true, cancelable: true }));
  form.dispatchEvent(new h.window.Event("submit", { bubbles: true, cancelable: true }));
  await settle();
  assert.equal(inviteCalls, 1, "the same pending invitation cannot be submitted twice");
  pendingInvite.resolve(response(200, {}));
  await Promise.all(h.requests.map((request) => request.promise));
  await settle();
  assert.equal(h.toasts.filter((toast) => toast[1] === "success").length, 1);
});

test("Team ignores responses from a previous organization and after logout", async (t) => {
  const pendingOldOrg = deferred();
  const pendingLogout = deferred();
  let memberLoads = 0;
  const h = fixture(async (url) => {
    if (url === "/api/team/organizations") return response(200, { organizations: [{ id: "org-1", name: "Org One" }] });
    if (url === "/api/team/invitations") return response(200, { invitations: [] });
    if (url === "/api/team/members") {
      memberLoads += 1;
      if (memberLoads === 1) return pendingOldOrg.promise;
      if (memberLoads === 3) return pendingLogout.promise;
      return response(200, membersData([owner]));
    }
    return response(500, {});
  });
  t.after(() => h.dom.window.close());
  h.module.onEnter();
  const oldOrgLoad = h.module.caricaTeam();
  await settle();
  h.context.selectedOrganizationId = "org-2";
  pendingOldOrg.resolve(response(200, membersData([{ ...staff, nome: "Tenant A secret" }])));
  await oldOrgLoad;
  await settle();
  assert.doesNotMatch(h.document.getElementById("team-members-tbody").textContent, /Tenant A secret/);

  h.module.onExit();
  h.context.selectedOrganizationId = "org-1";
  h.context.transition += 1;
  h.module.onEnter();
  await loadTeam(h);
  const logoutLoad = h.module.caricaTeam();
  await settle();
  h.module.invalidate();
  h.context.userId = null;
  pendingLogout.resolve(response(200, membersData([{ ...staff, nome: "Late after logout" }])));
  await logoutLoad;
  await settle();
  assert.doesNotMatch(h.document.getElementById("team-members-tbody").textContent, /Late after logout/);
});

test("Team confirmation cannot delete after org change, and detached rows cannot mutate another scope", async (t) => {
  const confirmation = deferred();
  const calls = [];
  const h = fixture(async (url, options = {}) => {
    calls.push({ url, options });
    if (url === "/api/team/organizations") return response(200, { organizations: [{ id: "org-1", name: "Org One" }] });
    if (url === "/api/team/invitations") return response(200, { invitations: [] });
    if (url === "/api/team/members") return response(200, membersData([owner, staff]));
    return response(200, {});
  });
  t.after(() => h.dom.window.close());
  h.setConfirmResult(confirmation.promise);
  h.module.onEnter();
  await loadTeam(h);
  const oldRow = h.document.querySelector('.team-delete-btn[data-user-id="staff-1"]');
  oldRow.click();
  await settle();
  h.context.selectedOrganizationId = "org-2";
  confirmation.resolve(true);
  await settle();
  assert.equal(calls.some((call) => call.options.method === "DELETE"), false, "confirmation is bound to its original organization scope");

  h.context.selectedOrganizationId = "org-1";
  h.module.onExit(); h.context.transition += 1; h.module.onEnter();
  await loadTeam(h);
  const detached = h.document.querySelector('.team-delete-btn[data-user-id="staff-1"]');
  detached.remove();
  detached.click();
  await settle();
  assert.equal(calls.some((call) => call.options.method === "DELETE"), false, "a detached old row cannot initiate a tenant mutation");
});

test("Team treats member names, email, and user IDs as hostile DOM data", async (t) => {
  const hostile = {
    user_id: 'user"><img src=x onerror="alert(1)">',
    nome: '<svg onload="window.compromised=true">',
    email: 'x"><img src=x onerror="window.compromised=true">@example.test',
    ruolo: "staff", joined_at: null,
  };
  const h = fixture(standardApi([owner, hostile]));
  t.after(() => h.dom.window.close());
  h.module.onEnter();
  await loadTeam(h);
  const tbody = h.document.getElementById("team-members-tbody");
  assert.equal(tbody.querySelector("img, svg[onload], [onerror]"), null);
  assert.equal(h.window.compromised, undefined);
  const row = [...tbody.querySelectorAll("tr[data-user-id]")].find((candidate) => candidate.textContent.includes(hostile.email));
  assert.ok(row);
  assert.equal(row.dataset.userId, hostile.user_id);
  assert.equal(row.querySelector(".team-avatar-circle").textContent, "<S", "hostile initials remain text instead of becoming an element");
  assert.ok(row.textContent.includes(hostile.email), "the hostile email is rendered as visible text");
});

test("concurrent Team refresh calls share one set of requests", async (t) => {
  const organizations = deferred();
  const invitations = deferred();
  const members = deferred();
  const h = fixture((url) => {
    if (url.endsWith("/organizations")) return organizations.promise;
    if (url.endsWith("/invitations")) return invitations.promise;
    return members.promise;
  });
  t.after(() => h.dom.window.close());
  h.module.onEnter();
  const first = h.module.caricaTeam();
  const second = h.module.caricaTeam();
  assert.equal(first, second);
  assert.equal(h.requests.filter((request) => request.url.endsWith("/organizations")).length, 1);
  assert.equal(h.requests.filter((request) => request.url.endsWith("/invitations")).length, 1);
  organizations.resolve(response(200, { organizations: [{ id: "org-1", name: "Org One" }] }));
  invitations.resolve(response(200, { invitations: [] }));
  await settle();
  assert.equal(h.requests.filter((request) => request.url.endsWith("/members")).length, 1);
  members.resolve(response(200, membersData([owner])));
  await Promise.all([first, second]);
});

test("denied Team member read clears prior tenant data and owner controls", async (t) => {
  let reads = 0;
  const h = fixture(async (url) => {
    if (url.endsWith("/organizations")) return response(200, { organizations: [{ id: "org-1", name: "Org One" }] });
    if (url.endsWith("/invitations")) return response(200, { invitations: [] });
    return ++reads === 1 ? response(200, membersData([owner, staff]))
      : response(403, { detail: "organization denied" });
  });
  t.after(() => h.dom.window.close());
  h.module.onEnter();
  await loadTeam(h);
  assert.equal(h.document.querySelectorAll("#team-members-tbody tr[data-user-id]").length, 2);
  await h.module.caricaTeam();
  assert.equal(h.document.querySelectorAll("#team-members-tbody tr[data-user-id]").length, 0);
  assert.equal(h.document.getElementById("team-stat-limit").textContent, "");
  assert.equal(h.document.getElementById("team-submit-btn").disabled, true);
  assert.equal(h.requests.length, 6);
});

test("a forced staff submission never sends an invitation", async (t) => {
  const h = fixture(standardApi([owner, staff]), { role: "staff" });
  t.after(() => h.dom.window.close());
  h.module.onEnter();
  await loadTeam(h);
  h.document.getElementById("team-add-email").value = "extra@example.test";
  h.document.getElementById("team-add-form").dispatchEvent(
    new h.window.Event("submit", { bubbles: true, cancelable: true }));
  await settle();
  assert.equal(h.requests.some((request) => request.options.method === "POST"), false);
});

test("Team exit closes its own pending confirmation without deleting", async (t) => {
  const h = fixture(standardApi([owner, staff]), { useSharedConfirmation: true });
  t.after(() => h.dom.window.close());
  h.module.onEnter();
  await loadTeam(h);
  h.document.querySelector('.team-delete-btn[data-user-id="staff-1"]').click();
  assert.equal(h.document.getElementById("confirm-modal").hidden, false);
  h.module.onExit();
  await settle();
  assert.equal(h.document.getElementById("confirm-modal").hidden, true);
  assert.equal(h.document.getElementById("confirm-desc").textContent, "");
  assert.equal(h.requests.some((request) => request.options.method === "DELETE"), false);
});

test("Team Escape restores delete focus without mutating, while exit preserves another focus target", async (t) => {
  const h = fixture(standardApi([owner, staff]), { useSharedConfirmation: true });
  t.after(() => h.dom.window.close());
  h.module.onEnter();
  await loadTeam(h);
  const button = h.document.querySelector('.team-delete-btn[data-user-id="staff-1"]');
  button.focus();
  button.click();
  const modal = h.document.getElementById("confirm-modal");
  assert.equal(modal.hidden, false);
  modal.dispatchEvent(new h.window.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  await settle();
  assert.equal(modal.hidden, true);
  assert.equal(h.document.activeElement, button);
  assert.equal(h.requests.some((request) => request.options.method === "DELETE"), false);

  button.click();
  assert.equal(modal.hidden, false);
  const otherTarget = h.document.getElementById("team-add-email");
  otherTarget.focus();
  h.module.onExit();
  await settle();
  assert.equal(modal.hidden, true);
  assert.equal(h.document.activeElement, otherTarget, "leaving the view must not steal focus from its new target");
  assert.equal(h.requests.some((request) => request.options.method === "DELETE"), false);
});

test("Team reentry leaves a single refresh listener", async (t) => {
  const h = fixture(standardApi());
  t.after(() => h.dom.window.close());
  h.module.onEnter();
  await loadTeam(h);
  h.module.onExit();
  h.context.transition += 1;
  h.module.onEnter();
  h.document.getElementById("btn-refresh-team").click();
  await settle();
  assert.equal(h.requests.filter((request) => request.url.endsWith("/members")).length, 2);
});

test("organization lookup failure resolves Team load with an error row", async (t) => {
  const h = fixture(async (url) => {
    if (url.endsWith("/organizations")) throw new Error("network offline");
    if (url.endsWith("/invitations")) return response(200, { invitations: [] });
    return response(200, membersData([owner]));
  });
  t.after(() => h.dom.window.close());
  h.window.console.error = () => {};
  h.module.onEnter();
  await h.module.caricaTeam();
  assert.match(h.document.getElementById("team-members-tbody").textContent, /Errore di connessione/);
  assert.equal(h.requests.some((request) => request.url.endsWith("/members")), false);
});
