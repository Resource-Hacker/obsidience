---
type: knowledge
title: Reddit mechanics and automation surface
---

Reddit is organized into communities, posts, and threaded comments. For current interaction, distinguish the consumer interface from the documented data surface instead of assuming that every historical sort remains visible in every client.

## Current sorting model

Reddit exposes different sorting and filtering choices across its consumer
clients and documented data interfaces. Treat the current page, API response,
or returned schema as evidence; do not infer that an option from an older
client is still present.

## Reliable agent routes

1. For read-only retrieval, prefer `web.search` and `web.fetch` against an exact
   thread or documented endpoint where the current access policy permits it.
   Honor authentication, rate limits, pagination, deletions, and truncation; a
   partial listing is not the complete discussion.
2. For browser interaction, navigate directly to the exact thread or listing URL. The old.reddit.com surface can be useful when it currently serves a simpler server-rendered page, but it is compatibility behavior rather than a guaranteed permanent API. Verify the actual DOM before relying on it.
3. When a sort is URL-addressable on the current surface, use the exact URL once and verify the resulting sort label or ordering. Do not fight a dynamic dropdown with repeated clicks.
4. Reserve `computer.act` for one explicitly requested, visible interaction
   that a read-only route cannot complete. Its single-click result still needs
   a fresh verified postcondition.

## Boundaries and owner context

The owner browses r/LivestreamFail and other communities in Microsoft Edge on the main display. Do not store or infer Reddit account details, cookies, credentials, votes, subscriptions, or private messages. Do not claim a post or comment was submitted, voted, saved, or sorted unless the current tool result or screen verifies that exact postcondition.
