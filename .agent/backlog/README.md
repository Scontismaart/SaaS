# Backlog

Raccolta dei task futuri o in attesa per l'infrastruttura multi-agente.

## Formato di ogni task

```
task-id:       identificativo univoco (es. TASK-042)
titolo:        titolo breve
complessita:   S | M | L | XL
descrizione:   cosa bisogna realizzare
criteri_acca:  criteri di accettazione verificabili
vincoli:       vincoli tecnici
contesto:      informazioni utili
```

## Regole

- Ogni task parte come file `TASK-<NNN>.md` in questa directory.
- Un task si considera **avviato** quando esiste un branch `ai/<task-slug>`.
- Quando il task è completato (PR creata o comando PR stampato), spostare il file in
  `.agent/plans/` insieme al piano approvato.
- Nuove idee di lavoro vanno registrate qui PRIMA di essere eseguite.
- Il manager usa questi task come input per la pianificazione (vedi `prompts/manager.txt`).

## Convenzioni

- Lingua: italiano.
- Non inserire segreti reali.
- I file vanno numerati in ordine crescente (`TASK-001.md`, `TASK-002.md`, ...).