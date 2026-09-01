-- 044: campo descrizione breve del profilo attività.
-- Raccolto dalla dashboard (Impostazioni -> Profilo attività) e iniettato
-- nel system prompt del responder; prima di questa migration il valore
-- raccolto dalla UI veniva scartato silenziosamente.
ALTER TABLE onboarding_profiles
    ADD COLUMN IF NOT EXISTS descrizione TEXT NOT NULL DEFAULT '';
