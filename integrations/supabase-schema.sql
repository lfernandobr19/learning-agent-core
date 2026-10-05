-- Learning Agent — tabela de sync
-- Rode no Supabase: SQL Editor → New query → Run

CREATE TABLE IF NOT EXISTS learning_snapshots (
    id TEXT PRIMARY KEY,
    data JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE learning_snapshots ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Allow anon access" ON learning_snapshots;

CREATE POLICY "Allow anon access" ON learning_snapshots
    FOR ALL USING (true) WITH CHECK (true);

-- Conversas first-class (IDE / Home / apps)
CREATE TABLE IF NOT EXISTS ravenna_conversations (
    id TEXT PRIMARY KEY,
    channel TEXT NOT NULL DEFAULT 'ide',
    title TEXT NOT NULL DEFAULT 'Nova conversa',
    archived BOOLEAN NOT NULL DEFAULT FALSE,
    project_name TEXT DEFAULT '',
    project_root TEXT DEFAULT '',
    workspace_root_ids JSONB DEFAULT '[]'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    user_id TEXT DEFAULT 'default'
);

CREATE TABLE IF NOT EXISTS ravenna_chat_messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES ravenna_conversations(id) ON DELETE CASCADE,
    channel TEXT NOT NULL DEFAULT 'ide',
    role TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    media_json JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ravenna_msgs_conv
    ON ravenna_chat_messages(conversation_id, created_at);

ALTER TABLE ravenna_conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE ravenna_chat_messages ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Allow anon access conversations" ON ravenna_conversations;
DROP POLICY IF EXISTS "Allow anon access messages" ON ravenna_chat_messages;

CREATE POLICY "Allow anon access conversations" ON ravenna_conversations
    FOR ALL USING (true) WITH CHECK (true);

CREATE POLICY "Allow anon access messages" ON ravenna_chat_messages
    FOR ALL USING (true) WITH CHECK (true);

SELECT id, updated_at FROM learning_snapshots;
