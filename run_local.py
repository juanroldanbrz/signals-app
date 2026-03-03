#!/usr/bin/env python3
"""
Run the Signals app locally with uvicorn.

Usage:
    uv run python run_local.py
    uv run python run_local.py --port 8080
    uv run python run_local.py --no-reload
"""
import argparse
import os
import sys
from pathlib import Path


def check_env():
    env_file = Path(".env")
    if not env_file.exists():
        example = Path(".env.example")
        if example.exists():
            print("⚠  No .env file found. Copy .env.example and fill in your values:")
            print("   cp .env.example .env")
        else:
            print("⚠  No .env file found. Required variables:")
            print("   GEMINI_API_KEY=your_key_here")
            print("   MONGO_URI=mongodb://localhost:27017")
            print("   MONGO_DB=signals")
        sys.exit(1)

    missing = []
    for line in env_file.read_text().splitlines():
        if line.startswith("GEMINI_API_KEY="):
            val = line.split("=", 1)[1].strip()
            if not val or val == "your_key_here":
                missing.append("GEMINI_API_KEY")

    if missing:
        print(f"⚠  Missing or placeholder values in .env: {', '.join(missing)}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Run the Signals app locally")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    parser.add_argument("--no-reload", action="store_true", help="Disable auto-reload")
    args = parser.parse_args()

    check_env()

    import uvicorn

    print(f"\n  Signals app starting...")
    print(f"  URL:    http://{args.host}:{args.port}")
    print(f"  Reload: {'off' if args.no_reload else 'on'}")
    print(f"  Press Ctrl+C to stop\n")

    uvicorn.run(
        "src.main:app",
        host=args.host,
        port=args.port,
        reload=not args.no_reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
