from __future__ import annotations

import argparse


def main():
    parser = argparse.ArgumentParser(prog="ignis")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.command == "serve":
        import uvicorn
        uvicorn.run("ignis.api:create_app", factory=True, host=args.host, port=args.port, workers=1)


if __name__ == "__main__":
    main()
