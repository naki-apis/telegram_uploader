from pyrogram import Client, filters
from pyrogram.types import Message
import asyncio
import os
import re
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


async def resolve_source(message, command_name):
    if not message.command:
        return None, None, None
    args = " ".join(message.command[1:]).strip()
    source_chat_id = None
    msg_id = None
    custom_name = None

    if args.startswith("https://t.me/"):
        source_chat_id, msg_id = parse_telegram_url(args)
        if not source_chat_id or not msg_id:
            return None, None, None
    elif len(message.command) == 2 and message.reply_to_message:
        source_chat_id = message.chat.id
        msg_id = message.reply_to_message.id
        custom_name = sanitize_filename(message.command[1])
    elif len(message.command) == 1 and message.reply_to_message:
        source_chat_id = message.chat.id
        msg_id = message.reply_to_message.id
    elif len(message.command) == 2:
        source_chat_id = message.chat.id
        try:
            msg_id = int(message.command[1])
        except ValueError:
            print(f"Usage: {command_name} (reply), {command_name} name.ext (reply), {command_name} https://t.me/user/123, {command_name} @user 123 or {command_name} -100123 456")
            return None, None, None
    elif len(message.command) == 3:
        chat_input = message.command[1]
        try:
            msg_id = int(message.command[2])
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


@app.on_message(
    (filters.private | filters.group | filters.me)
    & ~filters.channel
    & filters.command("dl", prefixes=".")
)
async def download_handler(client: Client, message: Message):
    await _react(client, message, "🤔")
    success = False
    try:
        source_chat_id, msg_id, custom_name = await resolve_source(message, ".dl")
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
        source_chat_id, msg_id, custom_name = await resolve_source(message, ".dlg")
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
