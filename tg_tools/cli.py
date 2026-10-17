import argparse
import os
import sys
from .config import ensure_credentials, clear_config
from .compressor import parse_zip_option
from .uploader import TelegramUploader, PROFILE_EXTS


def run_server():
    from .downloader import run_bot
    run_bot()


def main():
    parser = argparse.ArgumentParser(
        prog="tg-tool",
        description="Sube archivos a Telegram usando Pyrogram. Soporta archivos individuales, carpetas completas, compresión automática y modo bot de descarga.",
        epilog="Ejemplos:\n"
               "  tg-tool archivo.zip\n"
               "  tg-tool --folder ./fotos -IB\n"
               "  tg-tool server\n"
               "  tg-tool archivo.pdf -T preview.jpg",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "path", nargs="?", default=None,
        help="Ruta del archivo a subir, o 'server' para iniciar el bot de descarga. "
             "Si se omite, usa -F/--file o --folder."
    )

    parser.add_argument(
        "-F", "--file", dest="files", action="append", default=None,
        metavar="RUTA",
        help="Añade un archivo a la lista de subida (repetible). No compatible con --folder."
    )

    parser.add_argument(
        "--folder", metavar="DIR",
        help="Sube todos los archivos del directorio (orden alfabético). No compatible con archivos individuales."
    )

    parser.add_argument(
        "--chat", metavar="CHAT_ID", default=None,
        help="ID del chat destino o @usuario. Por defecto Mensajes Guardados (me)."
    )

    parser.add_argument(
        "--premium", action="store_true",
        help="Usa el límite de 3995MB para cuentas Premium (por defecto 1995MB)."
    )

    parser.add_argument(
        "--zip", metavar="TAMAÑO[/NIVEL]", default=None,
        help="Fuerza compresión 7z. TAMAÑO acepta K/M/G (ej. 100M, 1G). NIVEL opcional 0-9 (ej. 100M/9)."
    )

    parser.add_argument(
        "-T", "--thumb", metavar="RUTA", default=None,
        help="Miniatura personalizada para documentos (.jpg/.jpeg/.png). "
             "Telegram puede no mostrarla en ciertos tipos como PDF."
    )

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--video", action="store_true",
        help="Envía los archivos como video."
    )
    mode_group.add_argument(
        "--image", action="store_true",
        help="Envía los archivos como foto."
    )
    mode_group.add_argument(
        "--audio", action="store_true",
        help="Envía los archivos como audio."
    )

    parser.add_argument(
        "-IB", "--media-batch", dest="media_batch", action="store_true",
        help="Agrupa imágenes y videos en álbumes de hasta 10 elementos."
    )

    parser.add_argument(
        "-RC", "--remove_api", action="store_true",
        help="Elimina credenciales API y archivos de sesión guardados."
    )

    parser.add_argument(
        "-P", "--profile", action="store_true",
        help="Establece la foto de perfil usando la ruta, --folder o -F especificados."
    )

    parser.add_argument(
        "--delay", type=float, default=0.0, metavar="SEG",
        help="Segundos de espera entre subidas de foto de perfil (por defecto 0)."
    )

    args = parser.parse_args()

    if args.remove_api:
        removed = clear_config()
        print("Credenciales API eliminadas (config.json vaciado).")
        if removed:
            print("Sesiones eliminadas:")
            for p in removed:
                print(f"  - {p}")
        else:
            print("No se encontraron archivos de sesión.")
        return

    if args.path == "server":
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

    thumb_path = None
    if args.thumb:
        if not os.path.isfile(args.thumb):
            print(f"Error: el archivo de miniatura no existe: {args.thumb}", file=sys.stderr)
            sys.exit(1)
        ext = os.path.splitext(args.thumb)[1].lower()
        if ext not in (".jpg", ".jpeg", ".png"):
            print(f"Error: la miniatura debe ser .jpg/.jpeg/.png: {args.thumb}", file=sys.stderr)
            sys.exit(1)
        thumb_path = args.thumb

    sources = []
    if args.path and args.path != "server":
        sources.append(args.path)
    if args.files:
        sources.extend(args.files)

    if args.folder and sources:
        parser.error("Use --folder o archivos individuales, no ambos.")

    if args.profile:
        if args.folder:
            profile_paths = sorted(
                os.path.join(args.folder, e)
                for e in os.listdir(args.folder)
                if os.path.isfile(os.path.join(args.folder, e))
                and os.path.splitext(e)[1].lower() in PROFILE_EXTS
            )
        elif sources:
            profile_paths = [s for s in sources if os.path.splitext(s)[1].lower() in PROFILE_EXTS]
        else:
            profile_paths = sorted(
                os.path.join(os.getcwd(), e)
                for e in os.listdir(os.getcwd())
                if os.path.isfile(os.path.join(os.getcwd(), e))
                and os.path.splitext(e)[1].lower() in PROFILE_EXTS
            )

        if not profile_paths:
            print("No se encontraron imágenes de perfil válidas (.jpg/.jpeg/.png).", file=sys.stderr)
            sys.exit(1)

        api_id, api_hash = ensure_credentials()
        uploader = None
        try:
            uploader = TelegramUploader(api_id, api_hash)
            uploader.start()
            uploader.set_profile_photos(profile_paths, delay=args.delay)
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
                print("Errores:")
                for path, msg in uploader.errors:
                    print(f"  - {path}: {msg}")
        return

    if not args.folder and not sources:
        parser.error("Debe proporcionar una ruta, -F/--file o --folder.")

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
            thumb_path=thumb_path,
        )
        uploader.start()
        if args.folder:
            uploader.send_folder(args.folder, chat_id=args.chat, mode=mode, media_batch=args.media_batch)
        else:
            for s in sources:
                if not os.path.isfile(s):
                    print(f"Error: el archivo no existe: {s}", file=sys.stderr)
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
            print("Errores:")
            for path, msg in uploader.errors:
                print(f"  - {path}: {msg}")
