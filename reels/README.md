# Darbin Wine reels

Turns photos into Instagram Reels (1080×1920, 9:16, 30fps, H.264/AAC). Each photo gets a slow zoom or pan, and the photos are joined with crossfades. A title, an end card and music are optional.

## Requirements

- ffmpeg
- Python 3
- Pillow (`pip install pillow`, recommended), which turns sideways phone photos upright. `pillow-heif` adds iPhone HEIC support.

## Usage

Put photos in `photos/`. They play in filename order, so prefix them `01_`, `02_`, … to set the order.

```sh
python3 make_reel.py photos/ -o output/reel.mp4 \
    --title "Darbin Wine" --end-text "@darbinwine" --music track.mp3
```

| Option | Default | |
|---|---|---|
| `--per-photo` | 3.0 | seconds per photo |
| `--fade` | 0.6 | crossfade length in seconds |
| `--transition` | fade | any ffmpeg xfade transition, e.g. `smoothleft`, `circleopen`, `dissolve` |
| `--title` | none | text over the first photo |
| `--end-text` | none | text over the last photo |
| `--music` | none | audio file, looped or trimmed to the reel length and faded out |
| `--fit` | blur | `blur` shows the whole photo as a bordered print over a blurred copy (best for landscape photos); `crop` fills the frame |
| `--border` | 14 | print border in px for `--fit blur` |
| `--look` | film | `film` is a warm, faded grade with grain and vignette; `none` leaves colours as they are |
| `--font` | DejaVu Serif Bold / Georgia Bold | path to a .ttf/.otf |

Reel length is `photos × per-photo − (photos − 1) × fade`. For example, 8 photos at the defaults make a 19.8s reel.

## Music

`make_music.py` synthesizes an original retro pop backing track (120 BPM, I–V–vi–IV, vinyl crackle) that is free to use. At 120 BPM, `--per-photo 2.5 --fade 0.5` changes photo every 4 beats, on the beat.

```sh
python3 make_music.py -o output/darbin_pop.wav --seconds 17
python3 make_reel.py photos/ -o output/darbin_reel.mp4 --per-photo 2.5 --fade 0.5 \
    --music output/darbin_pop.wav --title "Evenings at Darbin" \
    --font /usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf
```

Use music you have the rights to, or add a track from Instagram's own library when you post.
