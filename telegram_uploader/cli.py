import argparse
import os
import sys
from .config import ensure_credentials, clear_config
from .compressor import parse_zip_option
from .uploader import TelegramUploader


def run_server():
    from .downloader import run_bot
    run_bot()


def main():
    parser = argparse.ArgumentParser(
        prog="telegram-uploader",
        description="Upload files to Telegram via Pyrogram",
    )
    parser.add_argument("path", nargs="?", help="File path")
    parser.add_argument("-F", "--file", dest="files", action="append", default=None,
                        metavar="PATH", help="Add a file (repeatable)")
    parser.add_argument("--folder", metavar="DIR", help="Send every file in DIR (alphabetical order)")
    parser.add_argument("--chat", metavar="CHAT_ID", default=None, help="Chat ID (default: Saved Messages)")
    parser.add_argument("--premium", action="store_true", help="Use the higher 3995M limit")
    parser.add_argument("--zip", metavar="SIZE[/LEVEL]", default=None,
                        help="Force 7z compression at SIZE (e.g. 100M, 1G, 100M/9). Optional LEVEL 0-9")

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--video", action="store_true", help="Send as video")
    mode_group.add_argument("--image", action="store_true", help="Send as photo")
    mode_group.add_argument("--audio", action="store_true", help="Send as audio")

    parser.add_argument("-IB", "--media-batch", dest="media_batch", action="store_true",
                        help="Group images and videos in batches of up to 10")
    parser.add_argument("--server", action="store_true", help="Start the download bot instead of uploading")
    parser.add_argument("-RC", "--remove_api", action="store_true",
                        help="Clear stored API credentials and session (empties config.json)")

    args = parser.parse_args()

    if args.remove_api:
        removed = clear_config()
        print("API credentials removed (config.json emptied).")
        if removed:
            print("Sessions removed:")
            for p in removed:
                print(f"  - {p}")
        else:
            print("No session files found.")
        return

    if args.server:
        try:
            run_server()
        except KeyboardInterrupt:
            pass
        finally:
            print()
            print("Force Exit (Ctrl+C)")
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(0)
        return

    sources = []
    if args.path:
        sources.append(args.path)
    if args.files:
        sources.extend(args.files)

    if args.folder and sources:
        parser.error("Use --folder or files, not both")
    if not args.folder and not sources:
        parser.error("You must provide a path, -F/--file or --folder")

    if args.video:
        mode = "video"
    elif args.image:
        mode = "image"
    elif args.audio:
        mode = "audio"
    else:
        mode = "document"

    zip_option = None
    if args.zip is not None:
        try:
            zip_option = parse_zip_option(args.zip, premium=args.premium)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    api_id, api_hash = ensure_credentials()

    uploader = None
    try:
        uploader = TelegramUploader(
            api_id, api_hash,
            premium=args.premium,
            zip_option=zip_option,
        )
        uploader.start()
        if args.folder:
            uploader.send_folder(args.folder, chat_id=args.chat, mode=mode, media_batch=args.media_batch)
        else:
            for s in sources:
                if not os.path.isfile(s):
                    print(f"Error: file does not exist: {s}", file=sys.stderr)
                    sys.exit(1)
            uploader.send_files(sources, chat_id=args.chat, mode=mode, media_batch=args.media_batch)
    except KeyboardInterrupt:
        print()
        print("Force Exit (Ctrl+C)")
        sys.stdout.flush()
        sys.stderr.flush()
        if uploader is not None:
            try:
                uploader.stop()
            except Exception:
                pass
        os._exit(0)
    else:
        if uploader is not None:
            uploader.stop()
        if uploader.errors:
            print()
            print("Errors:")
            for path, msg in uploader.errors:
                print(f"  - {path}: {msg}")
