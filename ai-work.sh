#!/usr/bin/env bash
#
# ai-work.sh — Orchestratore multi-agente
#
# Esegue un task software attraverso una pipeline di agenti specializzati:
#   manager (pianifica) -> implementer (implementa, TDD) -> redteam (rivista avversaria)
#   -> arbitro (decide continue/redo/stop) -> test/verifica -> commit -> PR.
#
# 4 livelli di complessità:
#   S  : solo implementer (nessuna pianificazione manageriale)
#   M  : manager + implementer + redteam
#   L  : manager + implementer + redteam + arbitro
#   XL : come L, ma il redteam lavora in parallelo (2 revisori)
#
# Il repair loop (max 3 iterazioni, variabile MAX_REPAIR) si applica a OGNI livello
# quando i test falliscono, non solo a L/XL.
#
# Uso:
#   ./ai-work.sh "descrizione del task"
#   ./ai-work.sh -L "descrizione del task"
#   ./ai-work.sh -S @file-con-task.md        (leggere il task da file)
#
# Opzioni:
#   -S|-M|-L|-XL   livello di complessità (default: rilevamento automatico)
#   @file.md       descrizione del task letta dal file
#   --dry-run      valida la meccanica (preflight, working tree pulito, baseline
#                  lint, branch) e si ferma senza invocare alcun agente/LLM
#
# Ambiente (override facoltativi):
#   AI_MODEL       modello usato dagli agenti (default: opencode/deepseek-v4-flash-free)
#   OPENCODE       eseguibile opencode (default: opencode)
#   MAX_REPAIR     iterazioni max del repair loop (default: 3)
#   AI_AUTO=0      non usare --auto (chiedi conferma permessi)
#
# ==============================================================================

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT_DIR="$SCRIPT_DIR/.agent"
PROMPTS_DIR="$AGENT_DIR/prompts"

OPENCODE="${OPENCODE:-opencode}"
MODEL="${AI_MODEL:-opencode/deepseek-v4-flash-free}"
MAX_REPAIR="${MAX_REPAIR:-3}"
AUTO_FLAG="--auto"
if [ "${AI_AUTO:-1}" = "0" ]; then AUTO_FLAG=""; fi

STAMP="$(date +%Y-%m-%d)"
LOGFILE="$AGENT_DIR/state/ai-work.log"
LEVEL=""
TASK_ARG=""
DRY_RUN=0

# ----------------------------------------------------------------------------
# Utility
# ----------------------------------------------------------------------------

log() {
  local msg="[$(date +%H:%M:%S)] $*"
  echo "$msg"
  mkdir -p "$(dirname "$LOGFILE")"
  echo "$msg" >> "$LOGFILE"
}

die() {
  log "ERRORE: $*"
  exit 1
}

# Controllo pre-volo: verifica le dipendenze ambientali una sola volta, PRIMA di
# qualunque step della pipeline (manager/implementer/redteam/arbiter) e del repair
# loop. Se qualcosa manca, lo script si ferma subito senza consumare chiamate a modelli.
preflight_check() {
  log "Controllo pre-volo (una sola volta, prima di qualunque step della pipeline)..."
  local ok=1

  # Docker attivo: richiesto dai test core (testcontainers pgvector)
  if command -v docker >/dev/null 2>&1; then
    if ! docker info >/dev/null 2>&1; then
      log "ERRORE: Docker non attivo: avvialo prima di eseguire ai-work.sh"
      ok=0
    fi
  else
    log "ERRORE: comando 'docker' non trovato (richiesto dai test core)"
    ok=0
  fi

  # ENCRYPTION_KEY richiesta dai test (come in CI)
  if [ -z "${ENCRYPTION_KEY:-}" ]; then
    log "ERRORE: variabile ENCRYPTION_KEY non impostata (richiesta dai test)"
    ok=0
  fi

  # ruff richiesto dal gate lint
  if ! python -m ruff --version >/dev/null 2>&1; then
    log "ERRORE: ruff non disponibile (richiesto dal gate lint). Installa: pip install ruff"
    ok=0
  fi

  if [ "$ok" -eq 0 ]; then
    die "Controllo pre-volo fallito: correggi i problemi sopra e riavvia lo script."
  fi
  log "Controllo pre-volo OK (Docker attivo, ENCRYPTION_KEY e ruff presenti)."
}

# Verifica che il working tree sia pulito: nessun codice entra nella storia senza review.
# Se ci sono modifiche non committate, lo script si ferma: il task parte da una base pulita.
clean_tree_check() {
  log "Verifica working tree pulito..."
  local dirty
  dirty="$(git status --porcelain)"
  if [ -n "$dirty" ]; then
    log "ERRORE: working tree sporco. Committa o fai stash delle modifiche prima di eseguire ai-work.sh:"
    echo "$dirty" | sed 's/^/  /'
    die "Working tree non pulito: nessuna modifica preesistente deve entrare nel task."
  fi
  log "Working tree pulito."
}

# Conteggio errori ruff sul repo (1 riga = 1 errore, formato concise).
# ruff esce non-zero quando trova errori: `|| true` per non far scattare set -e pipefail.
count_lint_errors() {
  python -m ruff check src/ tests/ --output-format concise 2>/dev/null | wc -l || true
}

# Baseline errori ruff catturata all'avvio: il gate fallisce solo se il delta cresce.
LINT_BASELINE=""
capture_lint_baseline() {
  LINT_BASELINE="$(count_lint_errors)"
  log "Baseline lint: $LINT_BASELINE errori ruff preesistenti."
}

# File toccati dal task (working tree pulito all'avvio => sono esattamente i file del run).
# --diff-filter=ACMR esclude i file cancellati (ruff --fix su path cancellato darebbe errore).
task_files() {
  {
    git diff --name-only --diff-filter=ACMR HEAD
    git ls-files --others --exclude-standard
  } | sort -u
}

# Autofix ruff (safe fix, zero chiamate a modelli) solo sui file del task.
run_lint_autofix() {
  local files
  files="$(task_files)"
  if [ -z "$files" ]; then
    log "Autofix lint: nessun file del task."
    return 0
  fi
  log "Autofix lint sui file del task..."
  # shellcheck disable=SC2086
  python -m ruff check --fix $files || true
}

# Gate duro: fallisce solo se il conteggio attuale supera la baseline (nuovi errori
# non risolvibili da autofix). Gli errori preesistenti restano ignorati.
check_lint_regression() {
  local now
  now="$(count_lint_errors)"
  if [ "$now" -gt "$LINT_BASELINE" ]; then
    log "REGRESSIONE LINT: $((now - LINT_BASELINE)) nuovi errori ruff (baseline $LINT_BASELINE -> $now) non risolti da autofix"
    return 1
  fi
  log "Lint OK: $now errori ruff (baseline $LINT_BASELINE), nessuna regressione"
  return 0
}

# ----------------------------------------------------------------------------
# Metrics
# ----------------------------------------------------------------------------

METRICS_FILE="$AGENT_DIR/state/metrics.jsonl"

# Una riga JSON per step: timestamp, step, livello, esito, durata.
log_metric() {
  local step="$1" esito="$2" durata="$3"
  mkdir -p "$(dirname "$METRICS_FILE")"
  printf '{"timestamp":"%s","step":"%s","livello":"%s","esito":"%s","durata_sec":%.2f}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$step" "$LEVEL" "$esito" "$durata" \
    >> "$METRICS_FILE"
}

# Esegue un comando misurandone la durata e loggando la metrica al termine.
run_timed() {
  local step="$1"
  shift
  local start end dur esito rc=0
  start="$(date +%s)"
  "$@" || rc=$?
  end="$(date +%s)"
  dur=$((end - start))
  esito="pass"
  [ "$rc" -ne 0 ] && esito="fail"
  log_metric "$step" "$esito" "$dur"
  return "$rc"
}

# slug dal titolo del task
slugify() {
  echo "$1" \
    | tr '[:upper:]' '[:lower:]' \
    | sed -E 's/[^a-z0-9]+/-/g; s/^-+|-+$//g' \
    | cut -c1-60
}

run_role() {
  local role="$1" prompt_file="$2" input="$3" agent="$4"
  log "=== Ruolo: $role (agent=$agent) ==="
  mkdir -p "$AGENT_DIR/state"
  local message
  message="$(cat "$prompt_file")
---
TASK INPUT:
$input"
  local start dur rc=0
  start="$(date +%s)"
  "$OPENCODE" run "$AUTO_FLAG" --agent "$agent" --model "$MODEL" --format default "$message" \
    2>&1 | tee "$AGENT_DIR/state/${role}-${STAMP}.log" || rc=$?
  dur=$(( $(date +%s) - start ))
  if [ "$rc" -eq 0 ]; then
    log_metric "$role" "pass" "$dur"
  else
    log_metric "$role" "fail" "$dur"
  fi
  return "$rc"
}

run_manager() {
  [ -f "$PROMPTS_DIR/manager.txt" ] || die "prompt manager.txt mancante"
  run_role "manager" "$PROMPTS_DIR/manager.txt" "$TASK_INPUT" "manager"
}

run_implementer() {
  [ -f "$PROMPTS_DIR/implementer.txt" ] || die "prompt implementer.txt mancante"
  run_role "implementer" "$PROMPTS_DIR/implementer.txt" "$TASK_INPUT" "implementer"
}

run_redteam() {
  local n="${1:-1}"
  [ -f "$PROMPTS_DIR/redteam.txt" ] || die "prompt redteam.txt mancante"
  if [ "$n" -gt 1 ]; then
    # redteam in parallelo (livello XL)
    log "=== Redteam parallelo (x$n) ==="
    local pids=()
    local i
    for i in $(seq 1 "$n"); do
      run_role "redteam-$i" "$PROMPTS_DIR/redteam.txt" "$TASK_INPUT" "redteam" &
      pids+=("$!")
    done
    for pid in "${pids[@]}"; do wait "$pid"; done
  else
    run_role "redteam" "$PROMPTS_DIR/redteam.txt" "$TASK_INPUT" "redteam"
  fi
}

run_arbiter() {
  [ -f "$PROMPTS_DIR/arbiter.txt" ] || die "prompt arbiter.txt mancante"
  run_role "arbiter" "$PROMPTS_DIR/arbiter.txt" "$TASK_INPUT" "arbiter"
}

# Esegue i test e distingue:
#   ritorno 0 = test PASS
#   ritorno 1 = test FAIL per motivi di codice (correggibile dall'implementer)
#   ritorno 2 = test FAIL per motivi ambientali (Docker/DB non raggiungibili)
# Logga la metrica "test" con esito e durata in ogni caso.
run_tests() {
  log "Esecuzione test..."
  local outfile="$AGENT_DIR/state/test-output-${STAMP}.log"
  mkdir -p "$AGENT_DIR/state"
  local start dur
  start="$(date +%s)"
  if PYTHONUTF8=1 python -m pytest -v --tb=short > "$outfile" 2>&1; then
    log "Test: PASS"
    dur=$(( $(date +%s) - start ))
    log_metric "test" "pass" "$dur"
    return 0
  fi
  if grep -Eiq \
      -e "docker|testcontainers" \
      -e "connection (refused|error)" \
      -e "econnrefused" \
      -e "cannot connect" \
      -e "could not connect" \
      -e "socket\.gaierror" \
      -e "could not translate host" \
      -e "errno.?111" \
      "$outfile"; then
    log "Test: FAIL (ambientale) — Docker/DB non raggiungibile durante l'esecuzione"
    tail -n 15 "$outfile"
    dur=$(( $(date +%s) - start ))
    log_metric "test" "fail_ambientale" "$dur"
    return 2
  fi
  log "Test: FAIL (codice)"
  tail -n 15 "$outfile"
  dur=$(( $(date +%s) - start ))
  log_metric "test" "fail" "$dur"
  return 1
}

# Step finale di lint: autofix (zero LLM) sui file del task, poi gate duro sulla
# regressione. Ritorna 1 se restano nuovi errori non risolvibili da autofix.
run_lint() {
  log "Esecuzione lint (autofix + gate regressione)..."
  run_lint_autofix
  local start dur
  start="$(date +%s)"
  if check_lint_regression; then
    dur=$(( $(date +%s) - start ))
    log_metric "lint" "pass" "$dur"
    return 0
  fi
  dur=$(( $(date +%s) - start ))
  log_metric "lint" "fail" "$dur"
  return 1
}

# ----------------------------------------------------------------------------
# Pipeline
# ----------------------------------------------------------------------------

# il repair loop si applica a OGNI livello: S, M, L, XL
# - FAIL di codice  -> richiama implementer (consuma un tentativo)
# - FAIL ambientale -> arresta subito, NON consuma tentativi (problema non risolvibile col codice)
repair_loop() {
  local attempt=1
  while [ "$attempt" -le "$MAX_REPAIR" ]; do
    local rc=0
    run_tests || rc=$?
    if [ "$rc" -eq 0 ]; then
      log "TEST PASS (tentativo $attempt/$MAX_REPAIR)"
      return 0
    fi
    if [ "$rc" -eq 2 ]; then
      log "FALLIMENTO AMBIENTALE durante i test: arresto senza consumare tentativi di repair. Verifica Docker/DB."
      return 2
    fi
    log "TEST FAIL (tentativo $attempt/$MAX_REPAIR) — avvio repair loop"

    if [ "$attempt" -ge "$MAX_REPAIR" ]; then break; fi

    # rivista avversaria (non al livello S, solo implementer)
    if [ "$LEVEL" = "M" ] || [ "$LEVEL" = "L" ] || [ "$LEVEL" = "XL" ]; then
      if [ "$LEVEL" = "XL" ]; then run_redteam 2; else run_redteam 1; fi
    fi

    # decisione arbitro (solo L/XL)
    if [ "$LEVEL" = "L" ] || [ "$LEVEL" = "XL" ]; then
      local decision
      decision="$(run_arbiter | tr '[:upper:]' '[:lower:]')"
      if echo "$decision" | grep -q "stop"; then
        log "Arbitro: STOP — lavoro interrotto"
        return 1
      fi
      if echo "$decision" | grep -q "continue"; then
        log "Arbitro: CONTINUE — si prosegue nonostante il fallimento"
        return 0
      fi
      # altrimenti REDO: nuova iterazione
    fi

    attempt=$((attempt + 1))
    log "Nuova iterazione implementer ($attempt/$MAX_REPAIR)"
    run_implementer
  done
  log "Repair loop esaurito (${MAX_REPAIR} iterazioni) — test ancora FAIL"
  return 1
}

# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

# parsa argomenti
while [ $# -gt 0 ]; do
  case "$1" in
    -S) LEVEL="S" ;;
    -M) LEVEL="M" ;;
    -L) LEVEL="L" ;;
    -XL) LEVEL="XL" ;;
    --dry-run) DRY_RUN=1 ;;
    @*) TASK_ARG="$1" ;;
    -*) die "opzione sconosciuta: $1 (usa -S|-M|-L|-XL)" ;;
    *) TASK_ARG="$1" ;;
  esac
  shift
done

[ -n "$TASK_ARG" ] || die "nessun task fornito. Uso: ./ai-work.sh [-S|-M|-L|-XL] \"descrizione\" oppure @file.md"

# lettura task: @file o stringa verbatim
if [ "${TASK_ARG#@}" != "$TASK_ARG" ]; then
  local_file="${TASK_ARG:1}"
  [ -f "$local_file" ] || die "file task non trovato: $local_file"
  TASK_INPUT="$(cat "$local_file")"
else
  TASK_INPUT="$TASK_ARG"
fi

TASK_TITLE="$(echo "$TASK_INPUT" | head -1 | cut -c1-70)"
[ -n "$TASK_TITLE" ] || TASK_TITLE="task"
TASK_SLUG="$(slugify "$TASK_TITLE")"
BRANCH="ai/${TASK_SLUG}"

# rilevamento automatico del livello se non specificato
if [ -z "$LEVEL" ]; then
  case "$TASK_TITLE" in
    *[Ff]ix*|*[Bb]ug*|*correzion*|*typo*|*minore*|*[Cc]orreggi*) LEVEL="S" ;;
    *[Rr]efactor*|*architettur*|*modul*|*integrazion*|*migrazion*) LEVEL="L" ;;
    *) LEVEL="M" ;;
  esac
  log "Livello rilevato automaticamente: $LEVEL"
fi

log "=============================="
log "Task : $TASK_TITLE"
log "Livello : $LEVEL"
log "Branch : $BRANCH"
log "Repair loop max : $MAX_REPAIR iterazioni (tutti i livelli)"
log "=============================="

cd "$SCRIPT_DIR"

# crea le dir runtime (gitignored) se non esistono
mkdir -p "$AGENT_DIR/state" "$AGENT_DIR/plans" "$AGENT_DIR/reviews" "$AGENT_DIR/decisions" "$AGENT_DIR/evaluations"

# controllo pre-volo (ambiente) -> working tree pulito -> baseline lint -> branch
preflight_check
clean_tree_check
capture_lint_baseline

# branch
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "non sei in un repository git"
if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
  git checkout "$BRANCH"
else
  git checkout -b "$BRANCH"
fi

if [ "$DRY_RUN" -eq 1 ]; then
  log "DRY-RUN completato: preflight, working tree pulito, baseline lint e branch ($BRANCH) validati. Nessun agente invocato."
  exit 0
fi

# 1. manager pianifica (TUTTI i livelli tranne S)
if [ "$LEVEL" != "S" ]; then
  run_manager
fi

# 2. implementer
run_implementer

# 3. repair loop (max 3, applicato a ogni livello)
rc=0
repair_loop || rc=$?
if [ "$rc" -ne 0 ]; then
  if [ "$rc" -eq 2 ]; then
    log "Pipeline interrotta per fallimento ambientale (Docker/DB). Nessun tentativo di repair consumato."
  else
    log "Pipeline fallita (test ancora rossi). Verifica manuale necessaria."
  fi
  exit 1
fi

# 4. verifica finale (autofix + gate regressione lint)
if ! run_lint; then
  log "Pipeline interrotta: regressione lint non risolta da autofix. Verifica manuale necessaria."
  exit 1
fi

# 5. commit
if git diff --quiet; then
  log "Nessuna modifica da committare"
else
  git add -A
  git commit -m "feat: $TASK_TITLE (livello $LEVEL)" \
    || log "commit fallito (nessuna modifica?)"
fi

# 6. PR
if command -v gh >/dev/null 2>&1; then
  log "Creazione PR via gh..."
  gh pr create \
    --title "$TASK_TITLE" \
    --body "Task: $TASK_TITLE

- Livello di complessità: $LEVEL
- Branch: \`$BRANCH\`
- Orchestrato da \`ai-work.sh\`" \
    --base main --head "$BRANCH" \
    || log "gh pr create non riuscito — crea la PR manualmente"
else
  echo ""
  echo "gh non disponibile. Crea la PR manualmente:"
  echo "  gh pr create --title \"$TASK_TITLE\" --body \"Task livello $LEVEL\" --base main --head \"$BRANCH\""
fi

log "Pipeline completata. Branch: $BRANCH"
