from pyrogram import Client, filters
from pyrogram.types import Message
import asyncio
import os
import re
import glob
import shlex
import shutil
import subprocess
from urllib.parse import urlparse
from .config import ensure_credentials, SESSION_PATH, ensure_session_dir

API_ID, API_HASH = ensure_credentials()
ensure_session_dir()

app = Client(
    SESSION_PATH,
    api_id=API_ID,
    api_hash=API_HASH,
)


def human_size(n):
    units = ["B", "KB", "MB", "GB", "TB"]
    f = float(n)
    for u in units:
        if f < 1024 or u == units[-1]:
            if u == "B":
                return f"{int(f)} {u}"
            return f"{f:.2f} {u}"
        f /= 1024


def bar(pct):
    filled = int(pct / 5)
    if filled > 20:
        filled = 20
    return "[" + "*" * filled + "-" * (20 - filled) + "]"


def parse_telegram_url(url):
    try:
        parsed = urlparse(url)
        if parsed.netloc != "t.me":
            return None, None
        path_parts = parsed.path.strip("/").split("/")
        if len(path_parts) < 2:
            return None, None
        if path_parts[0] == "c":
            if len(path_parts) >= 3:
                chat_id = int(path_parts[1])
                if chat_id > 0:
                    chat_id = int(f"-100{chat_id}")
                message_id = int(path_parts[2])
                return chat_id, message_id
        else:
            username = path_parts[0]
            message_id = int(path_parts[1])
            return f"@{username}", message_id
    except Exception:
        return None, None


def sanitize_filename(name):
    name = os.path.basename(name)
    name = re.sub(r'[\\/*?:"<>|]', "_", name)
    return name or "file"


def get_media_filename(msg):
    if msg.document and msg.document.file_name:
        return msg.document.file_name
    if msg.video and msg.video.file_name:
        return msg.video.file_name
    if msg.audio and msg.audio.file_name:
        return msg.audio.file_name
    if msg.photo:
        return f"photo_{msg.id}.jpg"
    if msg.video:
        return f"video_{msg.id}.mp4"
    if msg.audio:
        return f"audio_{msg.id}.mp3"
    if msg.voice:
        return f"voice_{msg.id}.ogg"
    if msg.sticker:
        ext = ".webp"
        if msg.sticker.is_animated:
            ext = ".tgs"
        elif msg.sticker.is_video:
            ext = ".webm"
        return f"sticker_{msg.id}{ext}"
    return f"file_{msg.id}"


def _raw_args(message, command_name):
    text = message.text or message.caption or ""
    prefix = "." + command_name
    if not text.startswith(prefix):
        return None
    rest = text[len(prefix):]
    if rest and not rest[0].isspace():
        return None
    return rest.strip()


async def resolve_source(message, command_name):
    args = _raw_args(message, command_name)
    if args is None:
        return None, None, None

    source_chat_id = None
    msg_id = None
    custom_name = None

    if args.startswith("https://t.me/"):
        source_chat_id, msg_id = parse_telegram_url(args)
        if not source_chat_id or not msg_id:
            return None, None, None
    elif args and message.reply_to_message:
        source_chat_id = message.chat.id
        msg_id = message.reply_to_message.id
        custom_name = sanitize_filename(args)
    elif not args and message.reply_to_message:
        source_chat_id = message.chat.id
        msg_id = message.reply_to_message.id
    elif args and not message.reply_to_message:
        parts = args.split()
        if len(parts) == 1:
            source_chat_id = message.chat.id
            try:
                msg_id = int(parts[0])
            except ValueError:
                print(f"Usage: {command_name} (reply), {command_name} name.ext (reply), {command_name} https://t.me/user/123, {command_name} @user 123 or {command_name} -100123 456")
                return None, None, None
        elif len(parts) == 2:
            chat_input = parts[0]
            try:
                msg_id = int(parts[1])
            except ValueError:
                return None, None, None
            if chat_input.startswith("@"):
                source_chat_id = chat_input
            else:
                try:
                    source_chat_id = int(chat_input)
                except ValueError:
                    try:
                        chat = await message._client.get_chat(chat_input)
                        source_chat_id = chat.id
                    except Exception:
                        return None, None, None
        else:
            print(f"Usage: {command_name} (reply), {command_name} name.ext (reply), {command_name} https://t.me/user/123, {command_name} @user 123 or {command_name} -100123 456")
            return None, None, None
    else:
        print(f"Usage: {command_name} (reply), {command_name} name.ext (reply), {command_name} https://t.me/user/123, {command_name} @user 123 or {command_name} -100123 456")
        return None, None, None

    return source_chat_id, msg_id, custom_name


async def download_single(client, target_msg, custom_name=None):
    if custom_name:
        filename = custom_name
    else:
        filename = sanitize_filename(get_media_filename(target_msg))

    file_path = os.path.join(os.getcwd(), filename)
    last_edit = {"t": 0.0}

    async def progress(current, total):
        now = asyncio.get_event_loop().time()
        if now - last_edit["t"] < 2.0 and current < total:
            return
        last_edit["t"] = now
        pct = (current / total) * 100 if total else 0
        line = f"Downloading {bar(pct)} {human_size(current)}/{human_size(total)} {pct:.1f}% {filename}"
        print("\r" + line, end="", flush=True)

    print(f"Downloading {filename}")
    file_path = await target_msg.download(
        file_name=file_path,
        progress=progress,
    )
    size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
    print("\r" + f"Downloading {bar(100)} {human_size(size)}/{human_size(size)} 100.0% {filename}", flush=True)
    print(f"Saved: {file_path}")


async def resolve_chat(client, source_chat_id):
    if isinstance(source_chat_id, str) and source_chat_id.startswith("@"):
        chat = await client.get_chat(source_chat_id)
        return chat.id
    return source_chat_id


async def _react(client, message, emoji):
    try:
        await client.send_reaction(
            chat_id=message.chat.id,
            message_id=message.id,
            emoji=emoji,
        )
    except Exception:
        pass


async def _finalize_reaction(client, message, success):
    try:
        await client.send_reaction(
            chat_id=message.chat.id,
            message_id=message.id,
            emoji="",
        )
    except Exception:
        pass
    try:
        await client.send_reaction(
            chat_id=message.chat.id,
            message_id=message.id,
            emoji="👍" if success else "👎",
        )
    except Exception:
        pass


async def _send_output(client, message, output):
    if not output:
        return
    max_len = 4000
    if len(output) <= max_len:
        await client.send_message(
            chat_id=message.chat.id,
            text=output,
            reply_to_message_id=message.id,
        )
        return
    for i in range(0, len(output), max_len):
        chunk = output[i:i + max_len]
        await client.send_message(
            chat_id=message.chat.id,
            text=chunk,
            reply_to_message_id=message.id,
        )


def _parse_fs_args(message, command_name):
    text = message.text or message.caption or ""
    prefix = "." + command_name
    if not text.startswith(prefix):
        return None
    rest = text[len(prefix):]
    if rest and not rest[0].isspace():
        return None
    return rest.strip()


def _split_fs_args(raw):
    recursive = False
    tokens = shlex.split(raw)
    filtered = []
    for token in tokens:
        if token == "-r":
            recursive = True
        else:
            filtered.append(token)
    return filtered, recursive


def _expand_glob(token):
    if any(ch in token for ch in "*?["):
        matches = sorted(glob.glob(token))
        return matches
    return [token]


def _expand_tokens(tokens):
    expanded = []
    for token in tokens:
        expanded.extend(_expand_glob(token))
    return expanded


def _list_path(path):
    if os.path.isfile(path):
        size = os.path.getsize(path)
        return [f"{human_size(size):>10}  {os.path.basename(path)}"]
    if not os.path.isdir(path):
        return None
    lines = []
    try:
        entries = sorted(os.listdir(path))
    except OSError as e:
        return [f"Error: {e}"]
    for entry in entries:
        full = os.path.join(path, entry)
        try:
            if os.path.isdir(full):
                lines.append(f"{'<DIR>':>10}  {entry}/")
            else:
                size = os.path.getsize(full)
                lines.append(f"{human_size(size):>10}  {entry}")
        except OSError:
            lines.append(f"{'?':>10}  {entry}")
    if not lines:
        lines.append("(empty)")
    return lines


def _ensure_parent(dst, recursive):
    parent = os.path.dirname(dst)
    if parent and not os.path.isdir(parent):
        if recursive:
            os.makedirs(parent, exist_ok=True)
            return True
        return False
    return True


@app.on_message(
    (filters.private | filters.group | filters.me)
    & ~filters.channel
    & filters.command("dl", prefixes=".")
)
async def download_handler(client: Client, message: Message):
    await _react(client, message, "🤔")
    success = False
    try:
        source_chat_id, msg_id, custom_name = await resolve_source(message, "dl")
        if source_chat_id is None or msg_id is None:
            return

        source_chat_id = await resolve_chat(client, source_chat_id)

        try:
            target_msg = await client.get_messages(source_chat_id, msg_id)
        except Exception as e:
            print(f"Error: could not fetch message: {str(e)[:150]}")
            return

        if not target_msg or target_msg.empty:
            return

        if not target_msg.media:
            return

        await download_single(client, target_msg, custom_name)
        success = True

    except Exception as e:
        print(f"Error: {str(e)[:150]}")
    finally:
        await _finalize_reaction(client, message, success)


@app.on_message(
    (filters.private | filters.group | filters.me)
    & ~filters.channel
    & filters.command("dlg", prefixes=".")
)
async def download_group_handler(client: Client, message: Message):
    await _react(client, message, "🤔")
    success = False
    try:
        source_chat_id, msg_id, custom_name = await resolve_source(message, "dlg")
        if source_chat_id is None or msg_id is None:
            return

        source_chat_id = await resolve_chat(client, source_chat_id)

        try:
            target_msg = await client.get_messages(source_chat_id, msg_id)
        except Exception as e:
            print(f"Error: could not fetch message: {str(e)[:150]}")
            return

        if not target_msg or target_msg.empty:
            return

        if not target_msg.media:
            return

        if not target_msg.media_group_id:
            await download_single(client, target_msg, custom_name)
            success = True
            return

        try:
            media_group = await client.get_media_group(source_chat_id, msg_id)
        except Exception as e:
            print(f"Error: could not fetch media group: {str(e)[:150]}")
            return

        for idx, single_msg in enumerate(media_group, start=1):
            if not single_msg.media:
                continue
            name = None
            if custom_name and len(media_group) == 1:
                name = custom_name
            elif custom_name:
                base, ext = os.path.splitext(custom_name)
                name = f"{base}_{idx}{ext}"
            try:
                await download_single(client, single_msg, name)
            except Exception as e:
                print(f"Error downloading item {idx}: {str(e)[:150]}")

        success = True

    except Exception as e:
        print(f"Error: {str(e)[:150]}")
    finally:
        await _finalize_reaction(client, message, success)


@app.on_message(
    (filters.private | filters.group | filters.me)
    & ~filters.channel
    & filters.command("ls", prefixes=".")
)
async def ls_handler(client: Client, message: Message):
    await _react(client, message, "🤔")
    success = False
    try:
        raw = _parse_fs_args(message, "ls")
        if raw is None:
            return
        try:
            tokens, _ = _split_fs_args(raw)
        except ValueError as e:
            print(f"Error: {e}")
            return
        targets = _expand_tokens(tokens) if tokens else ["."]
        if not targets:
            print("Error: no matches")
            return
        output_lines = []
        for target in targets:
            lines = _list_path(target)
            if lines is None:
                output_lines.append(f"Error: path not found: {target}")
                continue
            output_lines.append(f"Listing: {os.path.abspath(target)}")
            output_lines.extend(lines)
            success = True
        if output_lines:
            await _send_output(client, message, "\n".join(output_lines))
    except Exception as e:
        print(f"Error: {str(e)[:150]}")
    finally:
        await _finalize_reaction(client, message, success)


@app.on_message(
    (filters.private | filters.group | filters.me)
    & ~filters.channel
    & filters.command("cp", prefixes=".")
)
async def cp_handler(client: Client, message: Message):
    await _react(client, message, "🤔")
    success = False
    try:
        raw = _parse_fs_args(message, "cp")
        if not raw:
            print("Usage: .cp [-r] SRC... DST")
            return
        try:
            tokens, recursive = _split_fs_args(raw)
        except ValueError as e:
            print(f"Error: {e}")
            return
        if len(tokens) < 2:
            print("Usage: .cp [-r] SRC... DST")
            return
        dst = tokens[-1]
        src_tokens = tokens[:-1]
        sources = _expand_tokens(src_tokens)
        if not sources:
            print("Error: no matches")
            return
        dst_is_dir = os.path.isdir(dst) or dst.endswith(os.sep) or dst.endswith("/")
        if len(sources) > 1:
            if not dst_is_dir:
                if recursive:
                    os.makedirs(dst, exist_ok=True)
                    dst_is_dir = True
                else:
                    print(f"Error: destination must be a directory: {dst}")
                    return
        for src in sources:
            if not os.path.exists(src):
                print(f"Error: source not found: {src}")
                continue
            if dst_is_dir:
                target = os.path.join(dst, os.path.basename(src.rstrip(os.sep)))
            else:
                target = dst
            if not _ensure_parent(target, recursive):
                print(f"Error: destination directory not found: {os.path.dirname(target)}")
                continue
            try:
                if os.path.isdir(src):
                    shutil.copytree(src, target, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, target)
                print(f"Copied: {src} -> {target}")
                success = True
            except Exception as e:
                print(f"Error copying {src}: {str(e)[:150]}")
    except Exception as e:
        print(f"Error: {str(e)[:150]}")
    finally:
        await _finalize_reaction(client, message, success)


@app.on_message(
    (filters.private | filters.group | filters.me)
    & ~filters.channel
    & filters.command("mv", prefixes=".")
)
async def mv_handler(client: Client, message: Message):
    await _react(client, message, "🤔")
    success = False
    try:
        raw = _parse_fs_args(message, "mv")
        if not raw:
            print("Usage: .mv [-r] SRC... DST")
            return
        try:
            tokens, recursive = _split_fs_args(raw)
        except ValueError as e:
            print(f"Error: {e}")
            return
        if len(tokens) < 2:
            print("Usage: .mv [-r] SRC... DST")
            return
        dst = tokens[-1]
        src_tokens = tokens[:-1]
        sources = _expand_tokens(src_tokens)
        if not sources:
            print("Error: no matches")
            return
        dst_is_dir = os.path.isdir(dst) or dst.endswith(os.sep) or dst.endswith("/")
        if len(sources) > 1:
            if not dst_is_dir:
                if recursive:
                    os.makedirs(dst, exist_ok=True)
                    dst_is_dir = True
                else:
                    print(f"Error: destination must be a directory: {dst}")
                    return
        for src in sources:
            if not os.path.exists(src):
                print(f"Error: source not found: {src}")
                continue
            if dst_is_dir:
                target = os.path.join(dst, os.path.basename(src.rstrip(os.sep)))
            else:
                target = dst
            if not _ensure_parent(target, recursive):
                print(f"Error: destination directory not found: {os.path.dirname(target)}")
                continue
            try:
                shutil.move(src, target)
                print(f"Moved: {src} -> {target}")
                success = True
            except Exception as e:
                print(f"Error moving {src}: {str(e)[:150]}")
    except Exception as e:
        print(f"Error: {str(e)[:150]}")
    finally:
        await _finalize_reaction(client, message, success)


@app.on_message(
    (filters.private | filters.group | filters.me)
    & ~filters.channel
    & filters.command("cmd", prefixes=".")
)
async def cmd_handler(client: Client, message: Message):
    await _react(client, message, "🤔")
    success = False
    try:
        text = message.text or message.caption or ""
        prefix = ".cmd"
        if not text.startswith(prefix):
            return
        rest = text[len(prefix):]
        if rest and not rest[0].isspace():
            return
        command = rest.strip()
        if not command:
            print("Usage: .cmd <command>")
            return
        print(f"Executing: {command}")
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
        )
        parts = []
        if result.stdout:
            parts.append(result.stdout)
        if result.stderr:
            parts.append(result.stderr)
        parts.append(f"Exit code: {result.returncode}")
        output = "\n".join(parts).rstrip()
        print(output)
        await _send_output(client, message, output)
        success = result.returncode == 0
    except Exception as e:
        print(f"Error: {str(e)[:150]}")
        try:
            await _send_output(client, message, f"Error: {str(e)[:150]}")
        except Exception:
            pass
    finally:
        await _finalize_reaction(client, message, success)


def _silence_peer_errors(loop, context):
    exc = context.get("exception")
    if isinstance(exc, ValueError) and "Peer id invalid" in str(exc):
        return
    loop.default_exception_handler(context)


async def _main():
    loop = asyncio.get_event_loop()
    loop.set_exception_handler(_silence_peer_errors)
    await app.start()
    print("Bot started (download mode)")
    await asyncio.Future()


def run_bot():
    app.run(_main())
