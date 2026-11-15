# Provider status — 2026-11-15

Actual native Gemini requests, no mock results:

- Both existing credential slots tested with `gemini-3.5-flash-lite`: HTTP success, STOP, `OK`. Each prompt5/output1 tokens. See `evidence/provider_probe.json`.
- `gemini-embedding-001` real batch endpoint returned1 vector of768 dimensions. See `evidence/embedding_probe.json`. Documents are actually indexed via this API and cosine+BM25+RRF implemented. Coverage is per version, never assumed complete.
- `models.list` includes Hydrogen, Flash Lite, embedding. Listing is not availability proof. Hydrogen live QA evidence is recorded separately when complete.
- Gemini route uses existing operator-configured SOCKS proxy in local `.env`. No global proxy configuration changed. Both credentials conservatively mapped to one quota group until actual independent project mapping is verified. No quota multiplied by key count.
- Native API keys server-only, `.env` mode600. `.env.example` safe. MiniMax Plan and unprotected Bailian models are not runtime routes. No paid fallback implemented; setting ALLOW_PAID_FALLBACK does not enable a paid route.

Limits are the user's supplied snapshot, not fetched official remaining balance: Hydrogen5RPM/250K input TPM/20RPD; Flash Lite15RPM/250K/500RPD; embedding100RPM/30K/1000RPD. Quota transactions reserve against project+model, daily timezone America/Los_Angeles; one outstanding request per project/model. Failures and unknown timeouts count. UTF8-byte upper estimate plus overhead protects TPM before actual usage correction. Official Gemini input tokenizer is not yet integrated; conservative reservation may underuse capacity.

Global persistent Hydrogen initial budget4calls; per workspace default2/day; one synthesis normally1call. Increasing budget requires explicit further evaluation authorization. Translation batches use Flash Lite and persistent per-block completion. Provider logs expose controlled error categories, no request URLs or credentials.

Official documents checked: [Hydrogen](https://aistudio.google.com/docs/models/gemini-4-hydrogen), [project rate limits](https://aistudio.google.com/docs/rate-limits), [embedding API](https://aistudio.google.com/api-reference/embeddings). Local counts exclude other applications sharing the same cloud project; official current balance and free-tier billing protection remain operator-side configuration.
