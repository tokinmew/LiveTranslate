"""Offline SenseVoice CTC transcription and language evidence for short speech."""
from pathlib import Path
import hashlib
import os

# The Windows ONNX Runtime distribution reads this before native initialization.
os.environ['ORT_DISABLE_TELEMETRY'] = '1'
import numpy as np


VERIFIED_FILES = {
    'model.int8.onnx': (239233841, 'c71f0ce00bec95b07744e116345e33d8cbbe08cef896382cf907bf4b51a2cd51'),
    'tokens.txt': (315894, 'f449eb28dc567533d7fa59be34e2abca8784f771850c78a47fb731a31429a1dc'),
}


def verify_files(directory):
    for name, (length, digest) in VERIFIED_FILES.items():
        file = directory / name
        with file.open('rb') as stream:
            if file.stat().st_size != length or hashlib.file_digest(stream, 'sha256').hexdigest() != digest:
                raise ValueError('Unexpected SenseVoice file contents: ' + name)


class SenseVoice:
    def __init__(self, directory, threads=2):
        import onnxruntime as ort

        ort.disable_telemetry_events()
        directory = Path(directory)
        verify_files(directory)
        options = ort.SessionOptions()
        options.intra_op_num_threads = max(1, int(threads))
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(directory / 'model.int8.onnx'), options, providers=['CPUExecutionProvider'])
        metadata = self.session.get_modelmeta().custom_metadata_map
        if metadata.get('model_type') != 'sense_voice_ctc' or metadata.get('lfr_window_size') != '7' or metadata.get('lfr_window_shift') != '6':
            raise ValueError('Unexpected offline speech model architecture')
        self.languages = {key[5:]: int(value) for key, value in metadata.items() if key.startswith('lang_')}
        self.text_norm = int(metadata['without_itn'])
        self.with_itn = int(metadata['with_itn'])
        self.neg_mean = np.fromstring(metadata['neg_mean'], sep=',', dtype=np.float32)
        self.inv_std = np.fromstring(metadata['inv_stddev'], sep=',', dtype=np.float32)
        self.tokens = {}
        for line in (directory / 'tokens.txt').read_text(encoding='utf-8').splitlines():
            token, number = line.rsplit(' ', 1)
            self.tokens[int(number)] = token
        self.language_tokens = {token[2:-2]: number for number, token in self.tokens.items()
                                if token.startswith('<|') and token[2:-2] in self.languages}
        self.window = np.hamming(400).astype(np.float32)
        hz = np.arange(257) * (16000 / 512)
        mel = 1127 * np.log1p(hz / 700)
        edges = np.linspace(1127 * np.log1p(20 / 700), mel[-1], 82)
        low = (mel[:, None] - edges[:-2]) / (edges[1:-1] - edges[:-2])
        high = (edges[2:] - mel[:, None]) / (edges[2:] - edges[1:-1])
        self.filters = np.maximum(0, np.minimum(low, high)).astype(np.float32)

    def features(self, samples):
        samples = np.asarray(samples, dtype=np.float32) * 32768
        if len(samples) < 400:
            samples = np.pad(samples, (0, 400 - len(samples)))
        # 25 ms Kaldi-style frames with a 10 ms stride, pre-emphasis and an 80-bin log Mel bank.
        frames = np.lib.stride_tricks.sliding_window_view(samples, 400)[::160]
        frames = frames - frames.mean(axis=1, keepdims=True)
        pre = np.empty_like(frames)
        pre[:, 0] = frames[:, 0] * .03
        pre[:, 1:] = frames[:, 1:] - .97 * frames[:, :-1]
        spectrum = np.abs(np.fft.rfft(pre * self.window, n=512, axis=1)) ** 2
        bands = np.log(np.maximum(np.finfo(np.float32).eps, spectrum @ self.filters)).astype(np.float32)
        indices = np.arange(0, len(bands), 6)[:, None] + np.arange(-3, 4)[None, :]
        stacked = bands[np.clip(indices, 0, len(bands) - 1)].reshape(-1, 560)
        return np.ascontiguousarray((stacked + self.neg_mean) * self.inv_std)

    def transcribe(self, samples, selection='auto'):
        features = self.features(samples)
        return self.decode(features, selection)

    @staticmethod
    def _trim(samples):
        samples = np.asarray(samples, dtype=np.float32)
        if len(samples):
            voiced = np.flatnonzero(np.abs(samples) > max(np.max(np.abs(samples)) * 0.025, 1e-7))
            if len(voiced):
                samples = samples[max(0, voiced[0] - 320):min(len(samples), voiced[-1] + 320)]
        return samples

    def transcribe_trimmed(self, samples, selection='auto'):
        """Remove quiet leading/trailing samples before a second language observation."""
        return self.transcribe(self._trim(samples), selection)

    def transcribe_repeated(self, samples, selection='auto'):
        """Check acoustic consistency across three copies with identical 100 ms gaps."""
        unit = np.pad(self._trim(samples), (0, 1600))
        return self.transcribe(np.tile(unit, 3), selection)

    def transcribe_formatted(self, samples, selection):
        """Recover sentence punctuation for translation after identifying the source language."""
        return self.decode(self.features(samples), selection, self.with_itn)

    def decode(self, features, selection, normalization=None):
        inputs = {'x': features[None], 'x_length': np.array([len(features)], dtype='int32'),
                  'language': np.array([self.languages[selection]], dtype='int32'),
                  'text_norm': np.array([self.text_norm if normalization is None else normalization], dtype='int32')}
        logits = self.session.run(['logits'], inputs)[0][0]
        ids = logits.argmax(axis=-1)
        first = logits[0].astype(np.float64)
        probs = np.exp(first - first.max())
        probs /= probs.sum()
        all_lang = {lang: float(probs[number]) for lang, number in self.language_tokens.items()}
        # The four leading outputs describe language, emotion, event and text normalization.
        tags = [self.tokens[int(i)] for i in ids[:4]]
        words = []
        prev = -1
        for i in ids[4:]:
            if i and i != prev:
                words.append(self.tokens[int(i)])
            prev = i
        text = ''.join(words).replace('▁', ' ').strip()
        return {'language': tags[0][2:-2], 'probs': all_lang, 'tags': tags, 'text': text}
