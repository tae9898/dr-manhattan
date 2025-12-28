"""
List all currently active crypto weekly markets
"""

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Optional

import requests
from dotenv import load_dotenv

import dr_manhattan

load_dotenv()

@dataclass
class CryptoWeeklyMarket:
    token_symbol: str
    expiry_time: datetime
    strike_price: Optional[float] = None
    range_low: Optional[float] = None
    range_high: Optional[float] = None
    market_type: Literal["strike_price", "range", "other"] = "strike_price"

    def __str__(self) -> str:
        expiry_str = self.expiry_time.strftime('%Y-%m-%d %H:%M UTC')
        if self.market_type == "range":
            return f"{self.token_symbol} Range ${self.range_low:,.2f} - ${self.range_high:,.2f} ({expiry_str})"
        elif self.market_type == "strike_price":
            price_str = f"${self.strike_price:,.2f}" if self.strike_price else "TBD"
            return f"{self.token_symbol} Strike {price_str} ({expiry_str})"
        else:
            return f"{self.token_symbol} Weekly ({expiry_str})"

def find_all_active_crypto_weekly_markets(exchange, limit=200):
    """
    Find all currently active crypto weekly markets.

    Returns a list of (Market, CryptoWeeklyMarket) tuples.
    """
    TAG_WEEKLY = "102264"

    url = f"{exchange.BASE_URL}/markets"
    params = {
        "active": "true",
        "closed": "false",
        "tag_id": TAG_WEEKLY,
        "limit": limit,
        "order": "volume",
        "ascending": "false",
    }

    response = requests.get(url, params=params, timeout=10)
    data = response.json()

    all_markets = []
    if isinstance(data, list):
        for market_data in data:
            market = exchange._parse_market(market_data)
            if market:
                all_markets.append(market)

    # Regex patterns
    # Tokens to look for
    tokens_regex = r"Bitcoin|Ethereum|Solana|Ripple|XRP|BTC|ETH|SOL|DOGE|Cardano|ADA|BNB|Avalanche|AVAX"
    
    # Pattern for "Above/Below" strike markets
    # e.g. "Will the price of Solana be above $100 on December 29?"
    strike_pattern = re.compile(
        rf"Will (?:the price of )?(?P<token>{tokens_regex})\s+.*?"
        r"(?P<direction>above|below|greater than|less than|over|under)\s+"
        r"[\$]?(?P<price>[\d,]+(?:\.\d+)?)",
        re.IGNORECASE,
    )

    # Pattern for "Between" range markets
    # e.g. "Will the price of Bitcoin be between $82,000 and $84,000 on December 28?"
    range_pattern = re.compile(
        rf"Will (?:the price of )?(?P<token>{tokens_regex})\s+.*?"
        r"between\s+[\$]?(?P<low>[\d,]+(?:\.\d+)?)\s+and\s+[\$]?(?P<high>[\d,]+(?:\.\d+)?)",
        re.IGNORECASE
    )

    # Fallback pattern for simple "Token Weekly" etc if needed
    # (Leaving it out for now to avoid false positives)

    active_crypto_markets = []

    for market in all_markets:
        # Must be binary and open
        if not market.is_binary or not market.is_open:
            continue

        expiry = market.close_time if market.close_time else datetime.now(timezone.utc)
        
        # Check for Range markets first (more specific)
        range_match = range_pattern.search(market.question)
        if range_match:
            parsed_token = exchange.normalize_token(range_match.group("token"))
            low_price = float(range_match.group("low").replace(",", ""))
            high_price = float(range_match.group("high").replace(",", ""))
            
            crypto_market = CryptoWeeklyMarket(
                token_symbol=parsed_token,
                expiry_time=expiry,
                range_low=low_price,
                range_high=high_price,
                market_type="range"
            )
            active_crypto_markets.append((market, crypto_market))
            continue

        # Check for Strike markets
        strike_match = strike_pattern.search(market.question)
        if strike_match:
            parsed_token = exchange.normalize_token(strike_match.group("token"))
            price = float(strike_match.group("price").replace(",", ""))
            
            crypto_market = CryptoWeeklyMarket(
                token_symbol=parsed_token,
                expiry_time=expiry,
                strike_price=price,
                market_type="strike_price"
            )
            active_crypto_markets.append((market, crypto_market))
            continue

    return active_crypto_markets


def main():
    # Initialize Polymarket exchange
    exchange = dr_manhattan.Polymarket(
        {
            "private_key": os.getenv("POLYMARKET_PRIVATE_KEY"),
            "funder": os.getenv("POLYMARKET_FUNDER"),
        }
    )

    print("\n" + "=" * 80)
    print("CURRENTLY ACTIVE CRYPTO WEEKLY MARKETS")
    print("=" * 80)

    # Find all active markets
    active_markets = find_all_active_crypto_weekly_markets(exchange, limit=200)

    if not active_markets:
        print("\nNo currently active crypto weekly markets found.")
        print("\n" + "=" * 80 + "\n")
        return

    # Group by token
    by_token = {}
    for market, crypto_info in active_markets:
        token = crypto_info.token_symbol
        if token not in by_token:
            by_token[token] = []
        by_token[token].append((market, crypto_info))

    # Display grouped by token
    now = datetime.now(timezone.utc)

    for token in sorted(by_token.keys()):
        markets = by_token[token]
        # Sort markets by expiry then type
        markets.sort(key=lambda x: (x[1].expiry_time, x[1].market_type))
        
        print(f"\n{token} Markets ({len(markets)} active):")
        print("-" * 80)

        for market, crypto_info in markets:
            if crypto_info.expiry_time.tzinfo is None:
                # Assume UTC if naive, or convert carefully. 
                # market.close_time from exchange might be naive or aware.
                # Let's handle it safely.
                expiry_aware = crypto_info.expiry_time.replace(tzinfo=timezone.utc)
            else:
                expiry_aware = crypto_info.expiry_time

            time_left = (expiry_aware - now).total_seconds()
            hours_left = time_left / 3600
            days_left = hours_left / 24

            if days_left >= 1:
                time_str = f"{days_left:.1f}d left"
            else:
                time_str = f"{hours_left:.1f}h left"

            price_yes = market.prices.get("Yes", 0)
            price_no = market.prices.get("No", 0)
            # Some markets might use other outcomes, but usually Yes/No for these structure
            
            # If prices are empty, try getting them from bestBid/Ask if available (handled in _parse_market roughly)
            # or just show what we have.

            print(f"  {market.question}")
            print(
                f"    Expiry: {crypto_info.expiry_time.strftime('%Y-%m-%d %H:%M UTC')} ({time_str})"
            )
            print(f"    Prices: YES={price_yes:.4f} | NO={price_no:.4f}")
            print(f"    Liquidity: ${market.liquidity:,.2f}")
            print(f"    Volume: ${market.volume:,.2f}")
            print()

    print("=" * 80)
    print(f"Total: {len(active_markets)} active crypto weekly markets")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
