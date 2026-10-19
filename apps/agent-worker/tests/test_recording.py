import math

import av
import numpy as np

from agent_worker.recording import object_path, to_m4a


def make_stereo_ogg(path, seconds=2.0, rate=48000):
    """Caller tone on the left channel, agent tone on the right, as the real recorder lays them out."""
    t = np.arange(int(seconds * rate)) / rate
    left = (0.3 * np.sin(2 * math.pi * 440 * t)).astype(np.float32)
    right = (0.3 * np.sin(2 * math.pi * 660 * t)).astype(np.float32)
    data = np.stack([left, right])  # planar (channels, samples)
    with av.open(str(path), mode="w", format="ogg") as out:
        stream = out.add_stream("libopus", rate=rate)
        stream.layout = "stereo"
        frame = av.AudioFrame.from_ndarray(data, format="fltp", layout="stereo")
        frame.sample_rate = rate
        for packet in stream.encode(frame):
            out.mux(packet)
        for packet in stream.encode(None):
            out.mux(packet)


def test_ogg_becomes_a_playable_stereo_m4a(tmp_path):
    src, dst = tmp_path / "a.ogg", tmp_path / "a.m4a"
    make_stereo_ogg(src, 2.0)
    seconds = to_m4a(src, dst)
    assert 1.8 < seconds < 2.3
    with av.open(str(dst)) as c:
        s = c.streams.audio[0]
        assert s.codec_context.name == "aac" and s.channels == 2
        assert 1.8 < float(c.duration) / 1_000_000 < 2.3
    assert dst.read_bytes()[4:8] == b"ftyp"          # a real MP4/M4A container


def test_channels_stay_separate(tmp_path):
    src, dst = tmp_path / "a.ogg", tmp_path / "a.m4a"
    make_stereo_ogg(src, 1.0)
    to_m4a(src, dst)
    with av.open(str(dst)) as c:
        frames = [f.to_ndarray() for f in c.decode(c.streams.audio[0])]
    pcm = np.concatenate(frames, axis=1)              # planar float: (2, n)
    # each channel should hold mostly its own tone: compare energy at 440 Hz and 660 Hz
    def energy(ch, hz):
        spec = np.abs(np.fft.rfft(pcm[ch][:48000]))
        return spec[int(hz * len(pcm[ch][:48000]) / 48000)]
    assert energy(0, 440) > 5 * energy(0, 660)
    assert energy(1, 660) > 5 * energy(1, 440)


def test_object_path_is_scoped_to_the_workspace():
    assert object_path("tenant-1", "call-9") == "tenant-1/call-9.m4a"
