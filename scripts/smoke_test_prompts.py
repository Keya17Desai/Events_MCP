"""Smoke test: render each MCP Prompt with sample args.

Prompts are pure text generators — they return the string the LLM will
execute. This script just calls each one with example args and prints
the rendered prompt so you can sanity-check the wording before exposing
it to a real Claude session.

Run with:
    uv run python scripts/smoke_test_prompts.py
"""
from __future__ import annotations

from events_mcp.prompts.discovery import (
    compare_events,
    event_night_plan,
    genre_picks,
    surprise_me,
)


def _section(title: str, body: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print("=" * 60)
    print(body)


def main() -> None:
    _section(
        "/event_night_plan(city='Mumbai', date='2026-05-10', budget='₹2000')",
        event_night_plan(city="Mumbai", date="2026-05-10", budget="₹2000"),
    )

    _section(
        "/genre_picks(genre='rock', city='New York')",
        genre_picks(genre="rock", city="New York"),
    )

    _section(
        "/compare_events(event_id_a='vvG1iZ4...', event_id_b='vvG1iZ9...')",
        compare_events(event_id_a="vvG1iZ4abc", event_id_b="vvG1iZ9xyz"),
    )

    _section(
        "/surprise_me(city='London')",
        surprise_me(city="London"),
    )


if __name__ == "__main__":
    main()
