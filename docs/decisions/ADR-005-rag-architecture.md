# ADR 005: RAG Architecture

## Context
We need to provide accurate, business-specific answers about an organization's operations without high latency and excessive LLM API costs.

## Decision
We use `pgvector` for storing and retrieving document chunks. A semantic embedding cache (`faq_cache`) is used for frequently asked questions to intercept common queries before they reach the LLM, reducing costs and response times.
