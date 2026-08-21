-- Migration 043: Upgrade ai_reply_cache from TEXT to JSONB with backward compatibility
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns 
    WHERE table_name = 'messages' AND column_name = 'ai_reply_cache' AND data_type = 'text'
  ) THEN
    ALTER TABLE messages
      ALTER COLUMN ai_reply_cache TYPE JSONB USING (
        CASE 
          WHEN ai_reply_cache IS NULL THEN NULL
          WHEN ai_reply_cache::text ~ '^\s*\{' THEN ai_reply_cache::jsonb
          ELSE jsonb_build_object('text', ai_reply_cache, 'richiede_umano', false)
        END
      );
  ELSIF NOT EXISTS (
    SELECT 1 FROM information_schema.columns 
    WHERE table_name = 'messages' AND column_name = 'ai_reply_cache'
  ) THEN
    ALTER TABLE messages ADD COLUMN ai_reply_cache JSONB;
  END IF;
END $$;
