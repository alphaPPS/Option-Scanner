#!/usr/bin/env python3
"""
Delta Put Scanner — Robinhood
====================================
Scans a list of tickers for the put option expiring on a given date
with delta closest to the target delta, and prints a formatted table.

Usage:
    python3 put_scanner.py -f tickers.list -d 0.10 -t 15May2026
    python3 put_scanner.py -f tickers.list -d 0.10 -t 5/15/2026
    python3 put_scanner.py -f tickers.list -d 0.10 -t 2026-05-15
    python3 put_scanner.py -f tickers.list -d 0.10          (defaults to next Friday)

Arguments:
    -f  Path to a text file with one ticker per line (required)
    -d  Target delta as a positive number, e.g. 0.10 (default: 0.10)
    -t  Expiry date in any of these formats:
            15May2026   15may2026   15MAY2026
            5/15/2026   05/15/2026
            2026-05-15

Requirements:
    pip3 install robin_stocks tabulate
"""

import os
import sys
import getpass
import argparse
from datetime import date, timedelta

try:
    import robin_stocks.robinhood as rh
except ImportError:
    print("Missing library. Run:  pip3 install robin_stocks tabulate")
    sys.exit(1)

try:
    from tabulate import tabulate
except ImportError:
    print("Missing library. Run:  pip3 install tabulate")
    sys.exit(1)


# ── Date parsing ──────────────────────────────────────────────────────────────

def parse_expiry(date_str: str) -> str:
    """
    Accept multiple date formats and return YYYY-MM-DD.
    Supported:
        15May2026  /  15may2026  /  15MAY2026
        5/15/2026  /  05/15/2026
        2026-05-15
    """
    from datetime import datetime

    date_str = date_str.strip()
    formats = [
        "%d%b%Y",    # 15May2026
        "%m/%d/%Y",  # 5/15/2026 or 05/15/2026
        "%Y-%m-%d",  # 2026-05-15
        "%d-%b-%Y",  # 15-May-2026
        "%b%d%Y",    # May152026
    ]
    for fmt in formats:
        try:
            parsed = datetime.strptime(date_str, fmt)
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            continue

    print(f"❌  Could not parse date: '{date_str}'")
    print("    Accepted formats:  15May2026  |  5/15/2026  |  2026-05-15")
    sys.exit(1)


def next_friday() -> str:
    """Return the date of next Friday as YYYY-MM-DD."""
    today = date.today()
    days_ahead = (4 - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")


# ── CLI Arguments ─────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="Robinhood delta put scanner",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("-f", "--file", required=True,
                        help="Path to ticker list file (one ticker per line)")
    parser.add_argument("-d", "--delta", type=float, default=0.10,
                        help="Target delta absolute value (default: 0.10)")
    parser.add_argument("-t", "--target-date", default=None,
                        help=(
                            "Expiry date. Accepted formats:\n"
                            "  15May2026   5/15/2026   2026-05-15\n"
                            "  (default: next Friday)"
                        ))
    return parser.parse_args()


def load_tickers(filepath: str) -> list:
    if not os.path.exists(filepath):
        print(f"❌  Ticker file not found: {filepath}")
        sys.exit(1)
    with open(filepath) as f:
        tickers = [
            line.strip().upper()
            for line in f
            if line.strip() and not line.startswith("#")
        ]
    if not tickers:
        print(f"❌  No tickers found in {filepath}")
        sys.exit(1)
    return tickers


# ── Robinhood helpers ─────────────────────────────────────────────────────────

def login():
    print("\n── Robinhood Login ──────────────────────────────")
    token_path = os.path.expanduser("~/.tokens/robinhood.pickle")
    if os.path.exists(token_path):
        print("Found saved session, attempting auto-login...")
    else:
        print("No saved session found — please enter credentials.")

    username = input("Robinhood email: ").strip()
    password = getpass.getpass("Password: ")

    login_data = rh.login(
        username=username,
        password=password,
        expiresIn=86400,
        store_session=True,
    )
    if not login_data:
        print("❌  Login failed. Check credentials.")
        sys.exit(1)
    print("✓ Logged in successfully\n")


def get_stock_price(ticker: str):
    try:
        quote = rh.stocks.get_latest_price(ticker)
        if quote and quote[0]:
            return float(quote[0])
    except Exception:
        pass
    return None


def get_analyst_rating(ticker: str):
    """Return Buy% from analyst ratings, or None if unavailable."""
    try:
        ratings = rh.stocks.get_ratings(ticker)
        if not ratings:
            return None
        s = ratings.get("summary", {})
        buys  = int(s.get("num_buy_ratings",  0) or 0)
        holds = int(s.get("num_hold_ratings", 0) or 0)
        sells = int(s.get("num_sell_ratings", 0) or 0)
        total = buys + holds + sells
        if total == 0:
            return None
        return round((buys / total) * 100, 1)
    except Exception:
        return None


def find_best_put(ticker: str, expiry: str, target_delta: float, delta_tol: float):
    try:
        options = rh.options.find_options_by_expiration(
            inputSymbols=ticker,
            expirationDate=expiry,
            optionType="put",
            info=None,
        )
    except Exception as e:
        return {"error": str(e)}

    if not options:
        return None

    best = None
    best_diff = float("inf")

    for opt in options:
        try:
            delta_raw = opt.get("delta")
            if delta_raw is None:
                continue
            delta = float(delta_raw)
            abs_delta = abs(delta)
            diff = abs(abs_delta - target_delta)
            if diff < best_diff:
                best_diff = diff
                best = opt
        except (TypeError, ValueError):
            continue

    if best is None:
        return None

    try:
        mark = (float(best.get("bid_price", 0) or 0) +
                float(best.get("ask_price", 0) or 0)) / 2
    except Exception:
        mark = None

    abs_delta = abs(float(best.get("delta", 0) or 0))
    within_tol = abs(abs_delta - target_delta) <= delta_tol
    iv_raw = best.get("implied_volatility")
    iv = float(iv_raw) * 100 if iv_raw else None

    return {
        "strike":  float(best.get("strike_price", 0) or 0),
        "mark":    mark,
        "bid":     float(best.get("bid_price", 0) or 0),
        "ask":     float(best.get("ask_price", 0) or 0),
        "delta":   float(best.get("delta", 0) or 0),
        "iv":      iv,
        "oi":      int(best.get("open_interest", 0) or 0),
        "volume":  int(best.get("volume", 0) or 0),
        "status":  "OK" if within_tol else "~",
        "error":   None,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    args         = parse_args()
    tickers      = load_tickers(args.file)
    target_delta = args.delta
    delta_tol    = 0.05
    expiry       = parse_expiry(args.target_date) if args.target_date else next_friday()

    print(f"\n{'='*62}")
    print(f"  Delta Put Scanner")
    print(f"  Expiry : {expiry}")
    print(f"  Target : delta ~ -{target_delta:.2f}  (+-{delta_tol:.2f})")
    print(f"  Tickers: {len(tickers)}")
    print(f"{'='*62}\n")

    login()

    rows = []

    for i, ticker in enumerate(tickers, 1):
        print(f"[{i:2}/{len(tickers)}] {ticker:<6} ", end="", flush=True)

        stock_price   = get_stock_price(ticker)
        analyst_buy   = get_analyst_rating(ticker)
        result        = find_best_put(ticker, expiry, target_delta, delta_tol)

        analyst_str = f"{analyst_buy:.1f}" if analyst_buy is not None else "-"

        if result is None:
            print("no options chain found")
            rows.append([ticker,
                         f"{stock_price:.2f}" if stock_price else "-",
                         "-", "-", "-", "-", "-", "-", "-", "-", "no chain", "-", "-", analyst_str])
            continue

        if "error" in result and result["error"]:
            print(f"error: {result['error'][:60]}")
            rows.append([ticker,
                         f"{stock_price:.2f}" if stock_price else "-",
                         "-", "-", "-", "-", "-", "-", "-", "-", "error", "-", "-", analyst_str])
            continue

        print(f"strike=${result['strike']:.2f}  delta={result['delta']:.4f}  mark=${result['mark']:.2f}")

        # Weekly % return = (Mark / Strike) * 100
        if result['mark'] and result['strike']:
            weekly_ret = (result['mark'] / result['strike']) * 100
            annual_ret = weekly_ret * 52
        else:
            weekly_ret = None
            annual_ret = None

        rows.append([
            ticker,
            f"{stock_price:.2f}"      if stock_price       else "-",
            f"{result['strike']:.2f}" if result['strike']  else "-",
            f"{result['mark']:.3f}"   if result['mark']    else "-",
            f"{result['bid']:.2f}"    if result['bid']     else "-",
            f"{result['ask']:.2f}"    if result['ask']     else "-",
            f"{result['delta']:.4f}"  if result['delta']   else "-",
            f"{result['iv']:.1f}"     if result['iv']      else "-",
            str(result['oi'])         if result['oi']      else "-",
            str(result['volume'])     if result['volume']  else "-",
            result['status'],
            f"{weekly_ret:.2f}"       if weekly_ret is not None else "-",
            f"{annual_ret:.2f}"       if annual_ret is not None else "-",
            analyst_str,
        ])

    # ── Print table ───────────────────────────────────────────────────────────
    headers = [
        "Ticker", "Stock$", "Strike", "Mark", "Bid", "Ask",
        "Delta", "IV%", "OpenInt", "Volume", "Status", "Weekly%", "Annual%", "Buy%"
    ]

    print(f"\n{'='*62}")
    print(f"  RESULTS  --  Puts expiring {expiry}  @  ~{target_delta:.2f} delta")
    print(f"{'='*62}\n")
    print(tabulate(rows, headers=headers, tablefmt="simple", stralign="right"))
    print(f"\n  OK = delta within +-{delta_tol:.2f} of target   ~ = closest available")

    # ── CSV export ────────────────────────────────────────────────────────────
    from datetime import datetime as _dt
    timestamp = _dt.now().strftime("%Y%m%d_%H%M%S")
    csv_path = f"put_scan_{expiry}_d{target_delta:.2f}_{timestamp}.csv"
    with open(csv_path, "w") as f:
        f.write(",".join(headers) + "\n")
        for row in rows:
            f.write(",".join(str(c) for c in row) + "\n")
    print(f"\n  Saved -> {csv_path}\n")

    rh.logout()
    print("  Session closed. Done.\n")


if __name__ == "__main__":
    main()
