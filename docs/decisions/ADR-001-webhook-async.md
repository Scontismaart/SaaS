# ADR 001: Why webhook processing is asynchronous

## Context
Meta webhooks require a fast response. If we wait for the LLM to generate a reply, we risk hitting timeout limits, causing Meta to retry the webhook and degrading our sender score.

## Decision
Webhooks are immediately validated (HMAC/dedup), saved to PostgreSQL (`received_pending_ai`), and a 200 OK is returned. A separate worker (`InboundProcessor`) asynchronously picks up messages for LLM/RAG processing.
