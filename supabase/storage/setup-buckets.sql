-- Storage Buckets Setup Script
-- 
-- IMPORTANT: The storage schema requires elevated permissions.
-- If you get "permission denied for schema storage" error,
-- use the Supabase Dashboard UI instead:
--
-- 1. Go to Storage in Supabase Dashboard
-- 2. Click "Create a new bucket"
-- 3. Create bucket with name: knowledge-base
--    - Public: false
--    - File size limit: 10MB
--    - Allowed MIME types: text/markdown, text/plain
-- 4. Create bucket with name: review-artifacts
--    - Public: false
--    - File size limit: 50MB
--    - Allowed MIME types: application/pdf, application/vnd.openxmlformats-officedocument.wordprocessingml.document, etc.
--
-- After creating buckets via Dashboard, run the RLS policies below.

-- ============================================================================
-- CREATE STORAGE BUCKETS
-- ============================================================================

-- Knowledge Base Bucket (stores MD files)
INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
  'knowledge-base',
  'knowledge-base',
  false,  -- private bucket
  10485760,  -- 10MB file size limit
  ARRAY['text/markdown', 'text/plain']
)
ON CONFLICT (id) DO NOTHING;

-- Review Artifacts Bucket (stores uploaded solution artifacts)
INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
  'review-artifacts',
  'review-artifacts',
  false,  -- private bucket
  52428800,  -- 50MB file size limit
  ARRAY[
    'application/pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/msword',
    'application/vnd.ms-powerpoint',
    'application/vnd.ms-excel',
    'text/plain'
  ]
)
ON CONFLICT (id) DO NOTHING;

-- ============================================================================
-- ROW LEVEL SECURITY POLICIES FOR STORAGE
-- ============================================================================

-- Knowledge Base Bucket Policies
-- Public read access for Edge Functions
CREATE POLICY "Public read access for knowledge-base"
ON storage.objects FOR SELECT
TO anon, authenticated
USING (bucket_id = 'knowledge-base');

-- Service role can write to knowledge-base
CREATE POLICY "Service role can write to knowledge-base"
ON storage.objects FOR INSERT
TO service_role
WITH CHECK (bucket_id = 'knowledge-base');

CREATE POLICY "Service role can update knowledge-base"
ON storage.objects FOR UPDATE
TO service_role
WITH CHECK (bucket_id = 'knowledge-base');

CREATE POLICY "Service role can delete knowledge-base"
ON storage.objects FOR DELETE
TO service_role
USING (bucket_id = 'knowledge-base');

-- Review Artifacts Bucket Policies
-- SA can upload to their own review folder
CREATE POLICY "SA can upload to review-artifacts"
ON storage.objects FOR INSERT
TO authenticated
WITH CHECK (
  bucket_id = 'review-artifacts' AND
  auth.uid()::text = (storage.foldername(name))[1]
);

-- SA can read their own artifacts
CREATE POLICY "SA can read own artifacts"
ON storage.objects FOR SELECT
TO authenticated
USING (
  bucket_id = 'review-artifacts' AND
  auth.uid()::text = (storage.foldername(name))[1]
);

-- EA can read all artifacts
CREATE POLICY "EA can read all artifacts"
ON storage.objects FOR SELECT
TO authenticated
USING (
  bucket_id = 'review-artifacts' AND
  EXISTS (
    SELECT 1 FROM auth.users 
    WHERE auth.users.id = auth.uid() 
    AND auth.users.raw_user_meta_data->>'role' = 'ea'
  )
);

-- Service role full access
CREATE POLICY "Service role full access to review-artifacts"
ON storage.objects FOR ALL
TO service_role
USING (bucket_id = 'review-artifacts')
WITH CHECK (bucket_id = 'review-artifacts');

-- ============================================================================
-- HELPER FUNCTION FOR FOLDER NAME EXTRACTION
-- ============================================================================
CREATE OR REPLACE FUNCTION storage.foldername(path text)
RETURNS text[] AS $$
BEGIN
  -- Extract folder path from storage path
  -- Example: 'review-id/file.pdf' -> ARRAY['review-id']
  SELECT regexp_split_to_array(path, '/');
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;
