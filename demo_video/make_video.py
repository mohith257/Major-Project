# Builds the 1-2 min Open Day demo video: slides + neural TTS narration + burned-in subtitles + .srt
# Run: python demo_video/make_video.py   (needs ffmpeg on PATH, pip install edge-tts pillow)
import asyncio, os, subprocess, wave, textwrap
import edge_tts
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.path.join(HERE, "build")
os.makedirs(BUILD, exist_ok=True)
VOICE, RATE = "en-IN-NeerjaNeural", "+14%"
W, H = 1920, 1080
GAP, LEAD, TAIL = 0.25, 0.5, 1.2  # seconds: between sentences, before first, after last

BG, PANEL, FG, MUTED, ACCENT = "#0f1b2d", "#17283f", "#f1f5f9", "#94a3b8", "#2dd4bf"
F = lambda name, size: ImageFont.truetype(os.path.join("C:/Windows/Fonts", name), size)
REG, SEMI, BOLD = "segoeui.ttf", "seguisb.ttf", "segoeuib.ttf"

# ---- narration: (slide, sentence). Order follows the coordinators' notice. ----
SCRIPT = [
    (0, "Agentic FedGrid: privacy-preserving intrusion detection with federated learning and agentic AI."),
    (0, "By Mohith Kumar M, Anusha B, Lokesh Kumar Yadav and Rohan C Ravi, guided by Dr. Naidila Sadashiv, Department of ISE, JSS Academy of Technical Education, Bengaluru."),
    (1, "Our objectives: detect attacks on edge devices, so raw traffic never leaves the device."),
    (1, "Learn together across sites through federated learning, and respond autonomously but safely, even against poisoned updates."),
    (2, "Each edge node runs a tabular Transformer that classifies every network flow."),
    (2, "Nodes train small LoRA adapters, so each upload is about ten kilobytes instead of a hundred."),
    (2, "A serverless AWS backend combines these updates into a new global model."),
    (2, "An agent decides whether to ignore, alert or block based on expected cost. Blocks expire automatically, and a new model is adopted only if it does not hurt local performance."),
    (3, "This lets hospitals, colleges and small businesses share threat knowledge without sharing private traffic, at low cost, and with fewer false alarms cutting off legitimate users."),
    (4, "On four AWS nodes, the model reaches 87.7 percent accuracy on the official UNSW-NB15 test set and 99.3 percent on ToN-IoT, with 1.7 millisecond inference."),
    (4, "Under poisoning, median aggregation holds 86.5 percent accuracy, versus 47.5 percent for plain averaging."),
    (4, "With a simulated analyst, wrongly blocked benign traffic drops from 22 percent to 2 percent."),
    (4, "Agentic FedGrid shows that private, autonomous intrusion detection at the edge is practical. Thank you."),
]
# what the subtitle shows when it should differ from what the voice reads
SHOW = {"percent": "%", " millisecond": " ms", "ten kilobytes instead of a hundred": "10 KB instead of 100 KB"}


def show(t):
    for a, b in SHOW.items():
        t = t.replace(" " + a, b) if a == "percent" else t.replace(a, b)
    return t


# ---- 1. TTS per sentence -> wav, measure exact durations ----
async def tts_all():
    for i, (_, text) in enumerate(SCRIPT):
        mp3 = os.path.join(BUILD, f"s{i:02d}.mp3")
        if not os.path.exists(mp3):
            await edge_tts.Communicate(text, VOICE, rate=RATE).save(mp3)

asyncio.run(tts_all())

SR = 24000
def silence(sec): return b"\x00\x00" * int(SR * sec)
pcm, timeline, t = [silence(LEAD)], [], LEAD
for i, (slide, text) in enumerate(SCRIPT):
    wav = os.path.join(BUILD, f"s{i:02d}.wav")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", os.path.join(BUILD, f"s{i:02d}.mp3"),
                    "-ar", str(SR), "-ac", "1", "-sample_fmt", "s16", wav], check=True)
    with wave.open(wav) as w:
        frames = w.readframes(w.getnframes())
    dur = len(frames) / 2 / SR
    timeline.append((slide, text, t, t + dur))
    pcm += [frames, silence(GAP)]
    t += dur + GAP
pcm.append(silence(TAIL))
total = t + TAIL
with wave.open(os.path.join(BUILD, "narration.wav"), "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(b"".join(pcm))
print(f"narration {total:.1f}s")

# ---- 2. caption chunks: split long sentences at word boundaries, time by character share ----
captions = []
for slide, text, a, b in timeline:
    words = show(text).split(" ")  # not split(): it would also break on the nbsp
    k = -(-len(" ".join(words)) // 100)  # number of chunks, each <= ~100 chars, split evenly
    per = -(-len(words) // k)
    chunks = [" ".join(words[j:j + per]) for j in range(0, len(words), per)]
    n, s = sum(len(c) for c in chunks), a
    for c in chunks:
        e = s + (b - a) * len(c) / n
        captions.append((slide, c, s, e)); s = e

def ts(x): return f"{int(x//3600):02d}:{int(x%3600//60):02d}:{int(x%60):02d},{int(round(x%1*1000)) % 1000:03d}"
with open(os.path.join(HERE, "captions_for_upload.srt"), "w", encoding="utf8") as f:
    for k, (_, c, s, e) in enumerate(captions, 1):
        f.write(f"{k}\n{ts(s)} --> {ts(e)}\n{c}\n\n")

# ---- 3. slides ----
def base(section, title):
    im = Image.new("RGB", (W, H), BG); d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, 10], fill=ACCENT)
    d.text((110, 60), section.upper(), font=F(SEMI, 30), fill=ACCENT)
    d.text((110, 100), title, font=F(BOLD, 64), fill=FG)
    d.text((W - 110, 70), "Agentic FedGrid", font=F(SEMI, 28), fill=MUTED, anchor="ra")
    return im, d

def cards(d, items, top, cols, h):
    gw = (W - 220 - 40 * (cols - 1)) // cols
    for k, (head, body) in enumerate(items):
        x, y = 110 + (k % cols) * (gw + 40), top + (k // cols) * (h + 36)
        d.rounded_rectangle([x, y, x + gw, y + h], 22, fill=PANEL)
        d.rectangle([x, y + 22, x + 8, y + h - 22], fill=ACCENT)
        d.text((x + 44, y + 34), head, font=F(BOLD, 40), fill=FG)
        lines = textwrap.wrap(body, int(gw / 17))
        for j, ln in enumerate(lines):
            d.text((x + 44, y + 98 + j * 42), ln, font=F(REG, 32), fill=MUTED)

slides = []
# 0 title + team + guide
im, d = base("Final-year project · Dept. of ISE · 2025–26", "")
d.text((W // 2, 190), "Agentic FedGrid", font=F(BOLD, 120), fill=FG, anchor="mm")
d.text((W // 2, 300), "Autonomous Privacy-Preserving Intrusion Detection", font=F(SEMI, 46), fill=ACCENT, anchor="mm")
d.text((W // 2, 356), "via Federated Learning and Agentic AI", font=F(SEMI, 46), fill=ACCENT, anchor="mm")
team = [("1JS23IS090", "Mohith Kumar M"), ("1JS23IS016", "Anusha B"), ("1JS22IS065", "Lokesh Kumar Yadav"), ("1JS24IS410", "Rohan C Ravi")]
d.rounded_rectangle([460, 420, W - 460, 760], 22, fill=PANEL)
for k, (usn, name) in enumerate(team):
    y = 450 + k * 72
    d.text((540, y), usn, font=F(SEMI, 38), fill=ACCENT)
    d.text((860, y), name, font=F(REG, 38), fill=FG)
d.text((W // 2, 800), "Guide: Dr. Naidila Sadashiv", font=F(SEMI, 40), fill=FG, anchor="mm")
d.text((W // 2, 852), "JSS Academy of Technical Education, Bengaluru", font=F(REG, 34), fill=MUTED, anchor="mm")
slides.append(im)

# 1 objectives
im, d = base("Objectives", "What we set out to do")
cards(d, [("Detect at the edge", "Classify network flows on the device itself; raw traffic never leaves it."),
          ("Learn together", "Federated learning across sites, sharing only ~10 KB LoRA updates."),
          ("Respond safely", "Autonomous, cost-aware blocking that escalates gradually and expires."),
          ("Resist poisoning", "Robust aggregation and a local check before adopting any new model.")], 250, 2, 280)
slides.append(im)

# 2 methodology: architecture figure
im, d = base("Methodology", "Edge agents + serverless federated learning")
fig = Image.open(os.path.join(ROOT, "paper_figures", "fig1_infrastructure.png")).convert("RGB")
fh = 600; fw = int(fig.width * fh / fig.height)
fig = fig.resize((fw, fh), Image.LANCZOS)
px = (W - fw) // 2
d.rounded_rectangle([px - 30, 215, px + fw + 30, 215 + fh + 40], 22, fill="#ffffff")
im.paste(fig, (px, 235))
slides.append(im)

# 3 societal impact
im, d = base("Societal impact", "Who benefits")
cards(d, [("Privacy by design", "Hospitals, colleges and small businesses share threat knowledge, not their traffic."),
          ("Low cost", "Serverless AWS backend: pay per use, no always-on server to run."),
          ("Fewer false blocks", "Cost-aware, reversible actions keep legitimate users online."),
          ("Collective defence", "An attack seen at one site helps protect every other site.")], 250, 2, 280)
slides.append(im)

# 4 conclusion: key numbers
im, d = base("Conclusion", "Key results (4 AWS EC2 nodes, multiple seeds)")
tiles = [("87.7%", "accuracy, official UNSW-NB15 test"), ("99.3%", "accuracy, ToN-IoT"), ("1.7 ms", "inference per flow"),
         ("10.3 KB", "per update (vs 103.7 KB)"), ("86.5% vs 47.5%", "median vs FedAvg under poisoning"), ("22% → 2%", "benign traffic wrongly blocked*")]
tw = (W - 220 - 80) // 3
for k, (big, small) in enumerate(tiles):
    x, y = 110 + (k % 3) * (tw + 40), 240 + (k // 3) * 250
    d.rounded_rectangle([x, y, x + tw, y + 214], 22, fill=PANEL)
    d.text((x + tw // 2, y + 82), big, font=F(BOLD, 64 if len(big) < 10 else 50), fill=ACCENT, anchor="mm")
    d.text((x + tw // 2, y + 160), small, font=F(REG, 30), fill=MUTED, anchor="mm")
d.text((110, 760), "*with a simulated analyst; UNSW-NB15", font=F(REG, 26), fill=MUTED)
slides.append(im)

# ---- 4. frames = slide + caption band; concat with exact durations ----
cap_font = F(SEMI, 44)
def frame(slide_img, text):
    im = slide_img.copy(); d = ImageDraw.Draw(im)
    if text:
        lines = textwrap.wrap(text, 60)
        bh = 40 + 58 * len(lines)
        d.rectangle([0, H - bh - 40, W, H], fill="#05080f")
        for j, ln in enumerate(lines):
            d.text((W // 2, H - bh - 20 + j * 58 + 29), ln, font=cap_font, fill="#ffffff", anchor="mm")
    return im

segs, cur = [], 0.0
for slide, c, s, e in captions:
    if s > cur:  # gap between captions: keep slide, no caption
        segs.append((slide, "", s - cur))
    segs.append((slide, c, e - s)); cur = e
segs.append((captions[-1][0], "", total - cur))

lines = []
for k, (slide, c, dur) in enumerate(segs):
    p = os.path.join(BUILD, f"f{k:03d}.png")
    frame(slides[slide], c).save(p)
    lines += [f"file '{p.replace(os.sep, '/')}'", f"duration {dur:.3f}"]
lines.append(lines[-2])  # concat demuxer needs the last file repeated
with open(os.path.join(BUILD, "frames.txt"), "w") as f:
    f.write("\n".join(lines) + "\n")

out = os.path.join(HERE, "AgenticFedGrid_demo.mp4")
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", os.path.join(BUILD, "frames.txt"),
                "-i", os.path.join(BUILD, "narration.wav"), "-vf", "fps=30,format=yuv420p", "-c:v", "libx264", "-crf", "20",
                "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", out], check=True)
for k, s in enumerate(slides):
    s.save(os.path.join(BUILD, f"slide{k}.png"))
print("wrote", out)
