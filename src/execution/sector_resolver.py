"""Dynamic sector resolver with local cache and remote Yahoo Finance fallback mapping."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict
import yfinance as yf

from src.utils.logger import get_logger

logger = get_logger(__name__)

class SectorResolver:
    """Dynamically resolves ticker sectors using local cache and remote API fallback."""

    def __init__(
        self,
        cache_path: Path | str,
        fallback_mappings: Dict[str, str] | None = None
    ) -> None:
        self.cache_path = Path(cache_path)
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Load baseline hardcoded map
        self.cache: Dict[str, str] = fallback_mappings or {
            "AAPL": "Technology",
            "MSFT": "Technology",
            "GOOGL": "Technology",
            "AMZN": "Consumer Cyclical",
            "TSLA": "Consumer Cyclical",
            "NVDA": "Technology",
            "META": "Technology",
            "SPY": "Index",
            "QQQ": "Index",
            "JPM": "Financial Services",
            "PLTR": "Technology",
        }
        
        self._load_cache()

    def _load_cache(self) -> None:
        """Load cached sector mappings from disk."""
        if self.cache_path.exists():
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    disk_cache = json.load(f)
                    if isinstance(disk_cache, dict):
                        self.cache.update(disk_cache)
                logger.info(f"Loaded {len(self.cache)} sector mappings from cache.")
            except Exception as e:
                logger.error(f"Failed to load sector cache from {self.cache_path}: {e}")

    def _save_cache(self) -> None:
        """Save updated sector mappings to disk atomically."""
        tmp_file = self.cache_path.with_suffix(".json.tmp")
        try:
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, indent=4)
            tmp_file.replace(self.cache_path)
        except Exception as e:
            logger.error(f"Failed to write sector cache: {e}")
            if tmp_file.exists():
                try:
                    tmp_file.unlink()
                except Exception:
                    pass

    def resolve(self, symbol: str) -> str:
        """Resolve the sector of a symbol. Fetches via yfinance if missing from cache."""
        symbol = symbol.upper().strip()
        if not symbol:
            return "Unknown"

        # Check Cache
        if symbol in self.cache:
            return self.cache[symbol]

        # Handle indices/ETFs explicitly
        if symbol in ("SPY", "QQQ", "IWM", "DIA"):
            self.cache[symbol] = "Index"
            self._save_cache()
            return "Index"

        # Remote Fallback
        logger.info(f"Cache miss for {symbol}. Resolving sector dynamically from Yahoo Finance...")
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            sector = info.get("sector")
            
            if not sector:
                # Some ETFs return empty sector; check quoteType
                quote_type = info.get("quoteType")
                if quote_type in ("ETF", "MUTUALFUND"):
                    sector = "ETF"
                else:
                    sector = "Unknown"
            
            # Update Cache
            self.cache[symbol] = sector
            self._save_cache()
            logger.info(f"Dynamically resolved {symbol} -> Sector: {sector}")
            return sector
        except Exception as e:
            logger.error(f"Failed to resolve sector dynamically for {symbol}: {e}")
            # Do not cache "Unknown" to retry later
            return "Unknown"
