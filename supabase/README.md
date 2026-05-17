# Supabase Backend for ARB AI Agent

This directory contains the Supabase backend implementation for the Architecture Review Board (ARB) AI Agent system, including database migrations, Edge Functions, and storage configuration.

## Architecture Overview

The system uses a context-stuffing approach where:
- Knowledge base MD files are stored in Supabase Storage
- Review artifacts (PDF/DOCX/PPTX) are uploaded to Supabase Storage
- Edge Function orchestrates domain validation agents
- LLM (Claude/GPT-4o) processes the context-stuffed prompt
- Results are stored in PostgreSQL with normalized tables

## Directory Structure

```
supa_backend/
├── migrations/                          # Database migrations
│   ├── 001_initial_metadata_schema.sql  # UI metadata tables (existing)
│   ├── 002_ai_agent_schema.sql          # AI agent tables
│   └── 003_seed_md_files.sql            # Seed MD files
├── supabase_functions/                  # Edge Functions
│   └── review-orchestrator/             # Main orchestrator function
│       ├── index.ts                      # Entry point
│       ├── deno.json                     # Deno configuration
│       ├── agents/                       # Domain validation agents
│       │   ├── domain-agent.ts            # Base class
│       │   ├── orchestrator.ts           # Orchestrator agent
│       │   ├── general.ts                # General domain
│       │   ├── business.ts               # Business domain
│       │   ├── application.ts            # Application domain
│       │   ├── integration.ts            # Integration domain
│       │   ├── data.ts                   # Data domain
│       │   ├── security.ts               # Security domain
│       │   ├── infrastructure.ts         # Infrastructure domain
│       │   ├── devsecops.ts              # DevSecOps domain
│       │   └── nfr.ts                    # NFR domain
│       └── utils/                        # Utility modules
│           ├── llm.ts                     # LLM API integration
│           └── text-extraction.ts         # Document text extraction
└── storage/                             # Storage configuration
    └── setup-buckets.sql                 # Storage buckets setup
```

## Setup Instructions

### 1. Create Supabase Project

1. Go to [supabase.com](https://supabase.com) and create a new project
2. Note your project URL and anon/service role keys
3. Enable required extensions: `uuid-ossp`, `pgcrypto`

### 2. Run Database Migrations

Run migrations in order using the Supabase SQL Editor:

```sql
-- Run in Supabase SQL Editor
-- Migration 001: UI Metadata Schema (if not already run)
-- Copy contents from backend/migrations/001_initial_metadata_schema.sql

-- Migration 002: AI Agent Schema
-- Copy contents from supa_backend/migrations/002_ai_agent_schema.sql

-- Migration 003: Seed MD Files
-- Copy contents from supa_backend/migrations/003_seed_md_files.sql
```

### 3. Setup Storage Buckets

Run the storage setup script:

```sql
-- Copy contents from supa_backend/storage/setup-buckets.sql
```

This creates two buckets:
- `knowledge-base`: Stores EA principles, standards, policies (MD files)
- `review-artifacts`: Stores uploaded solution artifacts (PDF/DOCX/PPTX)

### 4. Upload Knowledge Base Files

Upload your MD files to the `knowledge-base` bucket:

1. Go to Supabase Storage → `knowledge-base` bucket
2. Upload files from `knowledge-base/` directory:
   - `ea-principles.md`
   - `ea-standards.md`
   - `integration-principles.md`
   - `architecture-review-taxonomy.md`
3. Update the `md_files` table with actual content (see sync script below)

### 5. Configure Edge Function Environment Variables

Set the following environment variables in Supabase Edge Functions:

```
SUPABASE_URL=your-project-url
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
OPENAI_API_KEY=your-openai-api-key  # or ANTHROPIC_API_KEY
```

### 6. Deploy Edge Function

Using Supabase CLI:

```bash
# Install Supabase CLI
npm install -g supabase

# Login
supabase login

# Link to your project
supabase link --project-ref your-project-ref

# Deploy the function
supabase functions deploy review-orchestrator
```

Or use the Supabase Dashboard:
1. Go to Edge Functions
2. Create new function: `review-orchestrator`
3. Copy contents from `supabase_functions/review-orchestrator/index.ts`
4. Set environment variables
5. Deploy

### 7. Configure User Roles

Set up user roles in `auth.users` metadata:

```sql
-- Update user role metadata
UPDATE auth.users
SET raw_user_meta_data = jsonb_build_object(
  'role', 'ea'  -- or 'sa', 'arb_reviewer'
)
WHERE id = 'user-uuid';
```

Roles:
- `sa`: Solution Architect (can create and review own submissions)
- `ea`: Enterprise Architect (can review all submissions, override decisions)
- `arb_reviewer`: ARB Reviewer (read-only access to approved reviews)

### 8. Sync MD Files Content

Update the `md_files` table with actual content from Storage:

```sql
-- Update md_files content from storage
-- This can be done via Edge Function or manual update
UPDATE md_files
SET content = (
  SELECT encode(
    decode(
      -- Read file from storage
      -- This requires a function or manual update
      'file-content-here',
      'base64'
    ),
    'escape'
  )
)
WHERE filename = 'ea-principles.md';
```

Or create a sync Edge Function to automate this.

## Database Schema

### AI Agent Tables

- `md_files`: Knowledge base metadata
- `reviews`: Main review records
- `domain_scores`: Normalized domain scores
- `findings`: Normalized findings
- `adrs`: Architecture Decision Records
- `actions`: Action items
- `audit_log`: Audit trail

### Relationships

```
reviews (1) ----< (N) domain_scores
reviews (1) ----< (N) findings
reviews (1) ----< (N) adrs
reviews (1) ----< (N) actions
reviews (1) ----< (N) audit_log
```

## Edge Function: review-orchestrator

### Request Format

```json
{
  "reviewId": "uuid-of-review-record"
}
```

### Response Format

```json
{
  "success": true,
  "reviewId": "uuid",
  "report": { /* full LLM response */ },
  "decision": "approve|approve_with_conditions|defer|reject"
}
```

### Processing Flow

1. Fetch review record from database
2. Load MD files based on scope tags
3. Download and extract text from artifact
4. Run domain validation agents
5. Assemble context-stuffed prompt
6. Call LLM (Claude/GPT-4o)
7. Parse and store results in normalized tables
8. Update review status to `ea_review`

## Testing

### Test Edge Function

```bash
# Using curl
curl -X POST \
  'https://your-project-ref.supabase.co/functions/v1/review-orchestrator' \
  -H 'Authorization: Bearer your-anon-key' \
  -H 'Content-Type: application/json' \
  -d '{"reviewId": "test-uuid"}'
```

### Test Database Queries

```sql
-- Check reviews
SELECT * FROM reviews ORDER BY created_at DESC LIMIT 10;

-- Check findings
SELECT * FROM findings WHERE severity = 'critical';

-- Check domain scores
SELECT r.solution_name, ds.domain, ds.score
FROM reviews r
JOIN domain_scores ds ON r.id = ds.review_id
ORDER BY r.created_at DESC;

-- Check audit log
SELECT * FROM audit_log ORDER BY created_at DESC LIMIT 20;
```

## Monitoring

### Key Metrics to Monitor

- Edge Function invocations (free tier: 50K/month)
- Database storage (free tier: 500MB)
- File storage (free tier: 1GB)
- LLM API costs
- Processing time per review

### Alerts

Set up alerts at:
- 70% database storage capacity
- 70% file storage capacity
- 80% Edge Function invocation limit
- Processing time > 120 seconds
- Error rate > 5%

## Troubleshooting

### Common Issues

**Edge Function timeout**
- Increase timeout in Supabase settings
- Optimize MD file loading
- Reduce artifact size

**LLM API errors**
- Check API key configuration
- Verify model availability
- Check rate limits

**Text extraction failures**
- Ensure file type is supported
- Check file size limits
- Consider using document processing service for complex formats

### Debug Mode

Enable additional logging in Edge Function:

```typescript
console.log('Debug info:', { /* data */ })
```

View logs in Supabase Dashboard → Edge Functions → Logs.

## Security Considerations

- RLS policies are enabled on all tables
- Service role key used only in Edge Functions
- API keys stored as environment variables
- Storage buckets are private with appropriate policies
- Audit log tracks all state changes

## Cost Estimation

### Free Tier (Pilot Phase)
- Database: 500MB (sufficient for ~100 reviews)
- Storage: 1GB (sufficient for ~50 reviews with artifacts)
- Edge Functions: 50K invocations/month
- LLM API: Depends on usage (~$0.01-0.05 per review)

### Pro Tier (Production)
- Database: $25/month for 8GB
- Storage: $21/month for 100GB
- Edge Functions: $10/month for 500K invocations
- LLM API: Depends on volume

## Next Steps

1. Complete Supabase project setup
2. Run all migrations
3. Upload knowledge base files
4. Deploy Edge Function
5. Test with sample review
6. Integrate with React frontend
7. Set up monitoring and alerts
8. Document deployment process

## Additional Resources

- [Supabase Documentation](https://supabase.com/docs)
- [Edge Functions Guide](https://supabase.com/docs/guides/functions)
- [RLS Policies](https://supabase.com/docs/guides/auth/row-level-security)
- [Storage API](https://supabase.com/docs/guides/storage)
