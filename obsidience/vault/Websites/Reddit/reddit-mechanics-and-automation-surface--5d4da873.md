---
kind: knowledge
title: Reddit — mechanics and automation surface
---

Reddit is organized into communities, posts, and threaded comments. For current interaction, distinguish the consumer interface from the documented data surface instead of assuming that every historical sort remains visible in every client.

## Current sorting model

Reddit's current Help Center documents post/search sorting by Relevance, Hot, Top, New, and Comment Count, with time filters for bounded Top-style views. It documents Relevance, Top, and New for the current comment interface. Reddit's official API documentation separately exposes listing endpoints such as best, hot, new, top, controversial, and comments/article. Treat the current page or returned schema as evidence; do not infer that an older client option is still present.

## Reliable agent routes

1. For read-only structured retrieval, prefer Reddit's documented API or JSON response where the current endpoint and access policy permit it. Honor authentication, rate limits, pagination, deletions, and truncation; a partial listing is not the complete discussion.
2. For browser interaction, navigate directly to the exact thread or listing URL. The old.reddit.com surface can be useful when it currently serves a simpler server-rendered page, but it is compatibility behavior rather than a guaranteed permanent API. Verify the actual DOM before relying on it.
3. When a sort is URL-addressable on the current surface, use the exact URL once and verify the resulting sort label or ordering. Do not fight a dynamic dropdown with repeated clicks.
4. Use the browser/data tool for retrieval and reserve computer_use for a visible interaction that the structured route cannot complete.

## Boundaries and owner context

The owner browses r/LivestreamFail and other communities in Microsoft Edge on the main display. Do not store or infer Reddit account details, cookies, credentials, votes, subscriptions, or private messages. Do not claim a post or comment was submitted, voted, saved, or sorted unless the current tool result or screen verifies that exact postcondition.
