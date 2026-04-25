# Architecture Overview

## Product split

- Bot 1: News Radar Bot
  - collects fresh relevant items
  - applies deterministic filtering and dedupe
  - sends high-quality Telegram cards
  - builds the weekly corpus
- Bot 2: Weekly Digest Bot
  - reads the stored weekly corpus
  - selects the five strongest stories
  - writes and sends the editorial digest

## Core rules

- Direct sources outrank wrappers
- Google News is a narrow competitor-check layer only
- Competitor mentions are a priority signal across all source types
- Freshness uses published date first and rejects missing published dates by default
- Bot 1 favors recall with sane filters; Bot 2 performs the harder editorial selection
