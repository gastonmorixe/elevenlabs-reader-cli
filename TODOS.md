# TODOS

Context: After the previous fix, streaming resumes past 1251 chars but there is a long, audible gap before the next segment starts. Logs show we receive two aligned blocks, then wait ~20s (keepalive pings) until `isFinal` arrives, close the socket, and only then reconnect. Additionally, overlap gating advanced the absolute character position even when dropping overlapped blocks, which could skip content.

## Goals
- Remove long silence between segments by proactively rolling over the WebSocket when the server stalls, instead of waiting for `isFinal`.
- Ensure next connection starts exactly where the last played audio ended (no skips), by updating progress only when audio is actually accepted/played.

## Plan
1) Diagnose gap cause and progress drift
   - The gap occurs because the client waits for `isFinal` if the per-connection budget wasn’t reached (e.g., 1251 < 1348). The server idles ~20s before sending `isFinal`. Also, progress (`abs_char_pos`) advanced on dropped overlapped blocks leading to potential skips.

2) Fix progress advancement gating
   - Only advance `abs_char_pos` when `accept_audio` is true (i.e., the audio was actually accepted/played). Do not advance on dropped blocks.

3) Derive `next_position` from played audio
   - Stop computing the next start position using cumulative aligned chars for the connection. Instead, set `next_position = abs_char_pos` (the durable end of actually played content).

4) Add idle-timeout rollover
   - Replace the `async for` recv loop with a `recv()` wrapped in `asyncio.wait_for` and an `idle_timeout` (≈1.5s). If we’ve already received any aligned audio in this connection and no new message arrives by the timeout, proactively break and reconnect from `abs_char_pos`.

5) Logging improvements
   - Add concise logs for accepted vs dropped aligned blocks per connection so it’s easy to verify continuity.

## Execution Log
- [x] Wrote this TODOS and plan
- [x] Changed progress advancement to only move when audio is accepted
- [x] Set next position from `abs_char_pos`
- [x] Implemented idle-timeout rollover using `wait_for` and per-connection state
- [x] Added summary logs per connection
- [x] Sanity pass and final notes

## Docs Merge Plan (now)

Goals:
- Consolidate all documentation into root README.md (keep TODOS.md separate).
- Remove duplicated/outdated files after merging.

Steps:
1) Inventory .md files and assess unique, accurate content
2) Fold authentication details into README (endpoint, headers) [done]
3) Fold FREE WS streaming details into README (idle + budget rollover, `char_count` termination) [done]
4) Add concise Security & Ethics section [done]
5) Remove redundant Markdown files (AUTHENTICATION.md, FREE_WEBSOCKET_STREAMING.md, WEBSOCKET_ANALYSIS.md) [done]

## README Polish & ToC

Goals:
- Add a clean, linked Table of Contents at the top.
- Ensure anchors match section headings and remove stale references.
- Improve readability with section separators and consistent style.

Execution:
- [x] Inserted ToC with links to all major sections and subsections
- [x] Verified anchors for all headings exist and navigate correctly
- [x] Removed stale link to deleted FREE_WEBSOCKET_STREAMING.md
- [x] Updated Project Structure to reflect consolidated docs

Backlog (nice-to-haves):
- [ ] Optional "Quick Links" bar (Quick Start • How It Works • Methods • Args)
- [ ] Optional collapsible details for advanced sections to streamline scanning
