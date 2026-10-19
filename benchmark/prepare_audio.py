"""Build a telephony-like test set: Hindi clips from Google FLEURS, downsampled to 8 kHz
with light noise. Writes data/audio/<id>.wav + <id>.txt. Usage: python prepare_audio.py [N]"""
import csv
import io
import sys
import tarfile

import numpy as np
import soundfile as sf
from huggingface_hub import hf_hub_download
from scipy.signal import resample_poly

from common import AUDIO_DIR

N = int(sys.argv[1]) if len(sys.argv) > 1 else 30
AUDIO_DIR.mkdir(parents=True, exist_ok=True)
tsv = hf_hub_download("google/fleurs", "data/hi_in/test.tsv", repo_type="dataset")
tgz = hf_hub_download("google/fleurs", "data/hi_in/audio/test.tar.gz", repo_type="dataset")
rows = {}
with open(tsv, encoding="utf-8") as f:
    for r in csv.reader(f, delimiter="\t"):
        rows[r[1]] = r[3]  # filename -> normalized transcription
rng = np.random.default_rng(0)
done = 0
with tarfile.open(tgz) as t:
    for m in t:
        name = m.name.split("/")[-1]
        if name not in rows or done >= N:
            continue
        x, sr = sf.read(io.BytesIO(t.extractfile(m).read()))
        x = resample_poly(x, 8000, sr)  # 8 kHz like PSTN
        x = x + rng.normal(0, 0.003, x.shape)  # light line noise
        sf.write(AUDIO_DIR / f"{name[:-4]}.wav", x.astype("float32"), 8000, subtype="PCM_16")
        (AUDIO_DIR / f"{name[:-4]}.txt").write_text(rows[name], encoding="utf-8")
        done += 1
print(f"wrote {done} clips to {AUDIO_DIR}")
