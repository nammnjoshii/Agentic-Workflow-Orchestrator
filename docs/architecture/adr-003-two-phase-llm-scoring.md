# ADR-003: Two-Phase LLM Scoring

**Date:** 2025-12
**Status:** Accepted

## Context

Each pipeline run produces 30–80 raw listings. Full deep-score LLM calls on all
listings would cost ~$0.24–$0.64 per run. The majority of listings are irrelevant
(construction, hardware, staffing-only) and don't require structured analysis.

## Decision

Two-phase scoring:
1. **Phase 1 (pre-filter):** Fast/small LLM scores each listing 0–100 on surface
   relevance. Listings below `FILTER_THRESHOLD` (default: 60) are dropped.
2. **Phase 2 (deep score):** Capable/large LLM produces a 9-field structured JSON
   analysis on the filtered subset only.

## Rationale

1. **Cost:** Phase 1 costs ~$0.0000008/call. Filtering from 60 to 8–12 listings
   before Phase 2 ($0.003/call) reduces per-run LLM cost by ~75–85%.
2. **Quality:** Phase 2 uses a larger model with full capability profile context,
   prompt caching enabled, and structured output validation. Accuracy is not sacrificed.
3. **Calibration:** `ScoringAssuranceAnalyst` validates scored output against a
   10-case golden calibration set to detect scoring drift across pipeline versions.

## Tradeoff

Recall risk: a listing below the Phase 1 threshold is never deep-scored. Threshold is
configurable via `FILTER_THRESHOLD` env var. Lower threshold = higher recall, higher
cost. Set threshold based on acceptable miss rate for your use case.

## Rejected Alternative

Single-phase scoring with the capable model on all listings. Rejected: 5–8x cost
increase with no quality gain on listings that are obviously irrelevant by surface
keywords alone.
