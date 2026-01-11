# Cursor Prompt: Refactor HLS delivery to “signed playlists + presigned segments” (Vultr Object Storage private)

## Goal
We cannot make Vultr buckets public. Refactor the video delivery so Expo AV can play HLS by:
- Serving **rewritten `.m3u8` playlists** from our FastAPI backend
- Ensuring **every nested playlist + every segment** is accessible via **presigned GET URLs**
- Avoiding proxying video bytes through our backend (segments should be direct from Vultr via presigned URLs, ideally via 302 redirect)

This must work for:
- master playlists referencing variant playlists
- variant playlists referencing segments
- relative paths inside playlists
- querystrings already present in URIs
- both `.ts` and `.m4s` segments (and `.key` if present)

## High-level design
Add an HLS gateway to the “video link service” backend (the one that knows object storage):

Endpoints:
1) `GET /hls/{key:path}`
   - If `key` ends with `.m3u8`: fetch object from Vultr (private), rewrite it so that all URI lines become calls back to our API:
     - nested `.m3u8` references -> `/hls/<resolved_key>`
     - segment references -> `/hls-seg/<resolved_key>` (or also `/hls/<resolved_key>` but then redirect based on extension)
   - Return rewritten playlist with correct headers.

2) `GET /hls-seg/{key:path}`
   - Generate a presigned GET URL for `key`
   - Return `302` redirect to that presigned URL (or `307` to preserve method)
   - Also support HEAD for debugging

Why this pattern:
- We only rewrite playlists once (and recursively for nested playlists).
- Segments never go through our backend; the client downloads them directly via presigned URLs.
- If we later add auth, we can gate `/hls/*` and `/hls-seg/*`.

## Implementation requirements (must-haves)
### S3 client (Vultr)
- Use boto3 (preferred) OR aiobotocore if already async.
- Must support custom `endpoint_url` for Vultr region, and access/secret keys from env.
- Must be consistent about host style. Use one style everywhere:
  - Prefer: path-style presigning (endpoint + bucket + key in path) if Vultr requires it
  - Or virtual-hosted style if it works in your region
- Add a single config toggle: `S3_ADDRESSING_STYLE=path|virtual` defaulting to whichever we implement.

Env vars:
- `VULTR_S3_ENDPOINT=https://<region>.vultrobjects.com`
- `VULTR_S3_BUCKET=<bucket>`
- `VULTR_ACCESS_KEY=...`
- `VULTR_SECRET_KEY=...`
- `PRESIGN_EXPIRES_SECONDS=3600` (default 1 hour)

### Playlist rewriting rules
Given a requested playlist key like `hls/abc/master.m3u8`:
- Determine playlist “dir”: `hls/abc/`
- Parse playlist as UTF-8 text.
- For each line:
  - If empty -> keep
  - If starts with `#` -> keep as-is
  - Else it's a URI line. Resolve it:
    - If line is absolute URL (`http://` or `https://`):
      - If it points to our own API already -> keep
      - Else leave it as-is (do not try to presign random hosts)
    - If it’s relative:
      - Resolve against playlist dir with POSIX rules
      - Ensure no `..` escapes outside allowed prefix (security)
- Rewrite URI lines:
  - If resolved target endswith `.m3u8` -> `/hls/<resolved_key>`
  - Else -> `/hls-seg/<resolved_key>`
- Preserve any querystrings/fragments in the original line when resolving/rewriting.

Security:
- Prevent path traversal: after resolving, normalize and reject if it escapes the base prefix (e.g. not starting with `hls/`).
- Allowlist prefix: only keys under `hls/` are permitted.

Headers:
- For `.m3u8` responses:
  - `Content-Type: application/vnd.apple.mpegurl` (or `application/x-mpegURL`)
  - `Cache-Control: no-store` for playlists (safe default)
- For redirect responses:
  - `Cache-Control: private, max-age=60` (optional)
- Add CORS allowing the Expo app origin (or `*` for hackathon if needed).

### Presigning
When generating presigned URLs:
- Use `get_object` (or equivalent) presigned URL.
- Expires = `PRESIGN_EXPIRES_SECONDS` (default 3600).
- Must presign using the exact same endpoint/host style that the client will request.
- Include a debug mode that logs:
  - resolved key
  - generated presigned URL host
  - expiry
  - addressing style used

### Observability / debugging
Add structured logs:
- when serving `/hls/*.m3u8`: log requested key, object size, number of rewritten URIs
- when redirecting `/hls-seg/*`: log key + first 80 chars of URL (no secrets)
If Vultr returns error:
- return `502` with a short message and log full exception
Add a `GET /hls-debug/presign?key=...` endpoint (protected or only in dev) that returns:
- resolved key
- presigned url (full)
- so we can paste into browser/curl to confirm it works

## Files/Modules to create or update
- `app/services/s3_client.py` (or similar): builds boto3 client with endpoint and addressing style
- `app/services/hls_rewrite.py`: functions:
  - `rewrite_playlist(text: str, playlist_key: str, api_base: str) -> str`
  - `resolve_hls_uri(playlist_key: str, uri_line: str) -> str`
- `app/api/routes/hls.py`: routes:
  - `GET /hls/{key:path}`
  - `GET /hls-seg/{key:path}`
  - optional `GET /hls-debug/presign`
- Update main FastAPI app router include.

## Acceptance tests (must pass)
1) Requesting `/hls/hls/<video>/master.m3u8` returns 200, correct content-type, and contains rewritten lines pointing to our API.
2) Requesting `/hls/<...>/variant.m3u8` also returns 200 and rewritten segment lines.
3) Requesting `/hls-seg/<...>/seg-0001.ts` returns 302/307 to a presigned Vultr URL.
4) Opening the presigned URL directly in browser/curl returns 200 (no 403).
5) Expo AV plays the HLS stream end-to-end.

## Implementation details / tricky cases to handle
- Some playlists use `./seg.ts` or `subdir/seg.ts` or `../` (normalize safely)
- Some HLS outputs include `#EXT-X-KEY:METHOD=AES-128,URI="key.key"`; you MUST rewrite the URI inside quotes too.
  - So in rewriting, handle:
    - plain URI lines (most)
    - tag lines containing `URI="..."` (at least EXT-X-KEY, also EXT-X-MEDIA)
  - For `URI="..."` values:
    - resolve similarly and rewrite to `/hls-seg/<resolved_key>` (or `/hls/<...>` if it endswith .m3u8)
- Keep everything else unchanged.

## Deliverable
Implement the above refactor with clean, readable code and minimal dependencies. Make sure it is robust and logs enough to debug any remaining 403 issues (signature mismatch, endpoint mismatch, clock skew).

When done, print quick manual test commands in the PR description:
- curl the master playlist
- grep for `/hls-seg/`
- curl -I the redirect endpoint
- curl -I the presigned location URL

Start now by scanning the existing codebase to find:
- where we currently generate HLS URLs
- what Vultr endpoint format we use today
- whether we already have boto3 configured
Then implement the new endpoints and swap the frontend to call `/hls/<key-to-master.m3u8>` instead of direct Vultr URLs.
