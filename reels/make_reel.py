#!/usr/bin/env python3
"""Turn a set of photos into an Instagram Reel (1080x1920, 9:16, H.264/AAC).

Each photo gets a slow Ken Burns zoom/pan, photos are joined with crossfades,
and an optional title card, end card and music track are added.

Requires ffmpeg on PATH. Pillow is optional but recommended: it fixes phone
photos that are stored sideways (EXIF orientation).

Examples:
    python3 make_reel.py photos/ -o reel.mp4
    python3 make_reel.py photos/*.jpg -o reel.mp4 --title "Darbin Wine" \
        --end-text "@darbinwine" --music track.mp3 --per-photo 3.5
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WIDTH, HEIGHT = 1080, 1920
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic"}

# Zoom/pan patterns cycled across photos so consecutive shots move differently.
# Each entry: (zoom expression, x expression, y expression). `on` is the output
# frame number within the clip and `N` is replaced by that clip's frame count.
MOTIONS = [
    # slow zoom in, centred
    ("1+0.12*on/N", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
    # slow zoom out, centred
    ("1.12-0.12*on/N", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
    # zoomed, pan left -> right
    ("1.12", "(iw-iw/zoom)*on/N", "ih/2-(ih/zoom/2)"),
    # zoom in towards the top (labels, bottle necks)
    ("1+0.12*on/N", "iw/2-(iw/zoom/2)", "(ih/2-(ih/zoom/2))*(1-on/N)"),
    # zoomed, pan right -> left
    ("1.12", "(iw-iw/zoom)*(1-on/N)", "ih/2-(ih/zoom/2)"),
]


def collect_photos(inputs):
    photos = []
    for item in inputs:
        p = Path(item)
        if p.is_dir():
            photos += sorted(f for f in p.iterdir() if f.suffix.lower() in IMAGE_EXTS)
        elif p.is_file():
            photos.append(p)
        else:
            sys.exit(f"Not found: {item}")
    if not photos:
        sys.exit("No photos found.")
    return photos


def normalize_photos(photos, workdir):
    """Apply EXIF rotation and convert to RGB JPEG so ffmpeg reads every file the same way."""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        print("Pillow not installed; skipping EXIF rotation fix (pip install pillow).", file=sys.stderr)
        return photos

    try:
        from pillow_heif import register_heif_opener
        register_heif_opener()
    except ImportError:
        pass

    out = []
    for i, src in enumerate(photos):
        dst = workdir / f"photo_{i:03d}.jpg"
        with Image.open(src) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.save(dst, quality=95)
        out.append(dst)
    return out


def find_font(explicit):
    if explicit:
        return explicit
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        "/Library/Fonts/Georgia Bold.ttf",
        "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
        "C:/Windows/Fonts/georgiab.ttf",
    ):
        if Path(candidate).exists():
            return candidate
    return None


def text_filter(textfile, font, start, end, size, y, fade=0.5):
    """drawtext that fades in at `start` and out at `end`."""
    alpha = (
        f"if(lt(t,{start}),0,if(lt(t,{start + fade}),(t-{start})/{fade},"
        f"if(lt(t,{end - fade}),1,if(lt(t,{end}),({end}-t)/{fade},0))))"
    )
    font_opt = f"fontfile='{font}':" if font else ""
    return (
        f"drawtext={font_opt}textfile='{textfile}':fontsize={size}:fontcolor=white:"
        f"x=(w-text_w)/2:y={y}:shadowcolor=black@0.6:shadowx=3:shadowy=3:"
        f"line_spacing=12:alpha='{alpha}'"
    )


def build(args):
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg not found on PATH.")

    photos = collect_photos(args.photos)
    n = len(photos)
    d, fade, fps = args.per_photo, args.fade, args.fps
    if n > 1 and fade >= d:
        sys.exit("--fade must be shorter than --per-photo.")
    total = n * d - (n - 1) * fade if n > 1 else d
    frames = round(d * fps)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        photos = normalize_photos(photos, tmp)

        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-stats"]
        for p in photos:
            # One frame per photo: zoompan expands it into `frames` output frames.
            cmd += ["-i", str(p)]
        if args.music:
            cmd += ["-stream_loop", "-1", "-i", args.music]

        parts = []
        for i in range(n):
            z, x, y = (e.replace("N", str(frames - 1)) for e in MOTIONS[i % len(MOTIONS)])
            # Fill the 9:16 frame (crop the overflow), upscale 2x so zoompan's
            # integer pixel steps don't jitter, then zoom/pan back down to 1080x1920.
            parts.append(
                f"[{i}:v]scale={WIDTH * 2}:{HEIGHT * 2}:force_original_aspect_ratio=increase,"
                f"crop={WIDTH * 2}:{HEIGHT * 2},setsar=1,"
                f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={WIDTH}x{HEIGHT}:fps={fps},"
                f"trim=duration={d},setpts=PTS-STARTPTS,format=yuv420p[v{i}]"
            )

        last = "v0"
        for i in range(1, n):
            offset = i * (d - fade)
            parts.append(
                f"[{last}][v{i}]xfade=transition={args.transition}:duration={fade}:offset={offset:.3f}[x{i}]"
            )
            last = f"x{i}"

        font = find_font(args.font)
        overlays = []
        if args.title:
            tf = tmp / "title.txt"
            tf.write_text(args.title)
            overlays.append(text_filter(tf, font, 0.3, min(d + 0.5, total), 96, "h*0.70"))
        if args.end_text:
            ef = tmp / "end.txt"
            ef.write_text(args.end_text)
            start = max(total - d, 0.3)
            overlays.append(text_filter(ef, font, start, total + 1, 72, "h*0.78"))
        overlays.append(f"fade=t=in:st=0:d=0.4,fade=t=out:st={max(total - 0.6, 0):.3f}:d=0.6")
        parts.append(f"[{last}]{','.join(overlays)}[vout]")

        if args.music:
            a = n
            parts.append(
                f"[{a}:a]atrim=duration={total:.3f},asetpts=PTS-STARTPTS,"
                f"afade=t=in:st=0:d=1,afade=t=out:st={max(total - 2, 0):.3f}:d=2[aout]"
            )

        script = tmp / "filter.txt"
        script.write_text(";\n".join(parts))
        cmd += ["-filter_complex_script", str(script), "-map", "[vout]"]
        if args.music:
            cmd += ["-map", "[aout]", "-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
        cmd += [
            "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-profile:v", "high",
            "-pix_fmt", "yuv420p", "-r", str(fps), "-t", f"{total:.3f}",
            "-movflags", "+faststart", args.output,
        ]

        print(f"{n} photos -> {args.output} ({total:.1f}s)")
        subprocess.run(cmd, check=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("photos", nargs="+", help="photo files and/or folders (folders are sorted by name)")
    ap.add_argument("-o", "--output", default="reel.mp4")
    ap.add_argument("--per-photo", type=float, default=3.0, help="seconds each photo is on screen (default 3)")
    ap.add_argument("--fade", type=float, default=0.6, help="crossfade length in seconds (default 0.6)")
    ap.add_argument("--transition", default="fade", help="ffmpeg xfade transition, e.g. fade, smoothleft, circleopen")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--title", help="text shown over the first photo")
    ap.add_argument("--end-text", help="text shown over the last photo, e.g. @darbinwine")
    ap.add_argument("--music", help="audio file; looped or trimmed to the reel length")
    ap.add_argument("--font", help="path to a .ttf/.otf font for the text")
    build(ap.parse_args())


if __name__ == "__main__":
    main()
