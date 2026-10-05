"""Local-only SDK verification. Never prints credentials or session responses."""
import argparse
from getpass import getpass

from app.brokers.base_broker import BrokerError
from app.brokers.kotak_neo.kotak_broker import KotakNeoBroker
from app.core.config import settings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["quotes", "login"])
    args = parser.parse_args()
    broker = KotakNeoBroker(settings)
    try:
        if args.action == "login":
            broker.login(getpass("Current 6-digit TOTP: "), getpass("6-digit MPIN: "))
            print("Kotak authentication verified. This temporary session will now log out.")
        else:
            for quote in broker.get_quotes():
                print(f"{quote['symbol']}: {quote['ltp']:.2f} ({quote['change_pct']:+.2f}%)")
        return 0
    except BrokerError as exc:
        print(str(exc))
        return 1
    finally:
        broker.close()


if __name__ == "__main__":
    raise SystemExit(main())
