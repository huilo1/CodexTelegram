from __future__ import annotations

import argparse
import asyncio
import logging

from .bot import CodexTelegramBot
from .config import Settings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Codex Telegram bot")
    parser.add_argument("--env-file", default=".env", help="Path to environment file")
    return parser.parse_args()


def run() -> None:
    args = parse_args()
    settings = Settings(_env_file=args.env_file)
    configure_logging(settings)
    bot = CodexTelegramBot(settings)
    asyncio.run(bot.start())


def configure_logging(settings: Settings) -> None:
    log_level = getattr(logging, settings.codex_log_level.upper(), logging.INFO)
    log_path = settings.codex_log_file
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        logging.StreamHandler(),
        logging.FileHandler(log_path, encoding="utf-8"),
    ]
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )


if __name__ == "__main__":
    run()
