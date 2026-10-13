import argparse
import os
import sys
from .config import ensure_credentials
from .compressor import parse_zip_option
from .uploader import TelegramUploader


def main():
    parser = argparse.ArgumentParser(prog="telegram-uploader", description="Upload files to Telegram via Pyrogram")
    parser.add_argument("path", nargs="?", help="File path")
    parser.add_argument("--video", action="store_true", help="Send as video with duration and thumbnail")
    parser.add_argument("--folder", metavar="DIR", help="Send every file in DIR (alphabetical order)")
    parser.add_argument("--chat", metavar="CHAT_ID", default=None, help="Chat ID (default: Saved Messages)")
    parser.add_argument("--premium", action="store_true", help="Use the higher 3995M limit")
    parser.add_argument("--zip", metavar="SIZE[/LEVEL]", default=None,
                        help="Force 7z compression at SIZE (e.g. 100M, 1G, 100M/9). Optional LEVEL 0-9")
    args = parser.parse_args()

    if not args.path and not args.folder:
        parser.error("Debes indicar un path o --folder")
    if args.path and args.folder:
        parser.error("Usa path o --folder, no ambos")

    zip_option = None
    if args.zip is not None:
        try:
            zip_option = parse_zip_option(args.zip, premium=args.premium)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    api_id, api_hash = ensure_credentials()

    uploader = TelegramUploader(
        api_id, api_hash,
        premium=args.premium,
        zip_option=zip_option,
    )
    uploader.start()
    try:
        if args.folder:
            uploader.send_folder(args.folder, chat_id=args.chat, as_video=args.video)
        else:
            if not os.path.isfile(args.path):
                print(f"Error: no existe {args.path}", file=sys.stderr)
                sys.exit(1)
            uploader.send_file(args.path, chat_id=args.chat, as_video=args.video)
    finally:
        uploader.stop()

    if uploader.errors:
        print()
        print("Errores:")
        for path, msg in uploader.errors:
            print(f"  - {path}: {msg}")


if __name__ == "__main__":
    main()
