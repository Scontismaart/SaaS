# Checklist pre-lancio — whatsapp-ai-responder

File vivo: aggiungiamo qui ogni cosa da testare/verificare prima di poter
lanciare il progetto in produzione. Non cancellare le voci fatte, spuntarle
(`[x]`) cosi' resta traccia di cosa e' stato verificato e quando.

---

## WhatsApp / Meta Cloud API

- [ ] **Test end-to-end reale**: numero WhatsApp Business verificato su Meta,
      `META_APP_SECRET`/`META_VERIFY_TOKEN` reali in produzione, un messaggio
      vero mandato da un telefono reale deve attraversare tutto il flusso:
      webhook riceve -> AI genera risposta -> risposta arriva su WhatsApp
      (o, se richiede_umano, il ticket appare in inbox e l'email di
      escalation arriva al titolare). Mai testato finora, solo mockato.
