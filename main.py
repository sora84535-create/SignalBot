"""
╔══════════════════════════════════════════════════════════════════╗
║          MEXC SIGNAL BOT — Professional Trading Signals          ║
║       SMC/ICT + Volume + Spread + AI Assistant + News            ║
╚══════════════════════════════════════════════════════════════════╝
"""

import asyncio
import logging
import sys
import os
from datetime import datetime

from src.bot import TelegramBot
from src.utils.logger import setup_logger
from config.settings import settings

logger = setup_logger("main")


async def main():
    logger.info("=" * 60)
    logger.info("  MEXC SIGNAL BOT v3.0 — Starting...")
    logger.info(f"  Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    logger.info("=" * 60)

    bot = TelegramBot()

    try:
        await bot.start()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        await bot.stop()


if __name__ == "__main__":
    asyncio.run(main())
