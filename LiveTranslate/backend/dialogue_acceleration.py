"""Session-scoped, optional second recognizer for positively gated Korean speech."""
from contextlib import ExitStack
import hashlib
import os
from pathlib import Path


_LARGE = {
    'model.bin': (3087284237, '69f74147e3334731bc3a76048724833325d2ec74642fb52620eda87352e3d4f1'),
    'config.json': (2394, 'a9306624f5ec14270a014b647e5c316b6e03a662c369758d1b90697a7b0655b9'),
    'preprocessor_config.json': (340, '7ccc62c6f2765af1f3b46c00c9b5894426835a05021c8b9c01eecb6dfb542711'),
    'tokenizer.json': (2480617, '6d8cbd7cd0d8d5815e478dac67b85a26bbe77c1f5e0c6d76d1ce2abc0e5f21ca'),
    'vocabulary.json': (1068114, 'c69260f2ab26d659b7c398f9a2b2b48ed0df16c3b47d7326782fd9cba71690c1'),
}
_OPTIONAL_ERRORS = (OSError, ImportError, MemoryError, RuntimeError, ValueError)


class DialogueUnavailable(Exception):
    """The current utterance must resume the already available Small decoder."""


def _load_large(model_directory, cuda_directory, threads, cancelled):
    from nvidia_runtime import _CUBLAS, _load_cublas, _locked_reader, _win32
    import ctranslate2
    from faster_whisper import WhisperModel
    import numpy as np

    if os.name != 'nt' or not ctranslate2.get_cuda_device_count():
        raise OSError('No compatible NVIDIA device is available.')
    # Verify model availability before loading even the approved GPU libraries.
    model_directory = Path(model_directory).resolve(strict=True)
    cuda_directory = Path(cuda_directory).resolve(strict=True)
    for name, size, _ in _CUBLAS:
        if (cuda_directory / name).stat().st_size != size:
            raise ValueError('Unexpected NVIDIA library size: ' + name)
    kernel = _win32()
    with ExitStack() as locked:
        streams = []
        for name, (size, expected) in _LARGE.items():
            if cancelled():
                raise DialogueUnavailable('Audio stopped.')
            path = model_directory / name
            if path.is_symlink() or path.resolve() != path:
                raise ValueError('Unverified optional speech-model path.')
            stream = locked.enter_context(_locked_reader(path, kernel))
            if os.fstat(stream.fileno()).st_size != size:
                raise ValueError('Unexpected optional speech-model size: ' + name)
            streams.append((stream, name, expected))
        for stream, name, expected in streams:
            digest = hashlib.sha256()
            while block := stream.read(4*1024*1024):
                if cancelled():
                    raise DialogueUnavailable('Audio stopped.')
                digest.update(block)
            if digest.hexdigest() != expected:
                raise ValueError('Optional speech-model integrity check failed: ' + name)
        _load_cublas(cuda_directory)
        if cancelled():
            raise DialogueUnavailable('Audio stopped.')
        model = WhisperModel(str(model_directory), device='cuda', compute_type='float16', cpu_threads=threads,
                             num_workers=1, local_files_only=True)
        if cancelled():
            raise DialogueUnavailable('Audio stopped.')
        extractor = model.feature_extractor
        probe = np.zeros((extractor.mel_filters.shape[0], extractor.nb_max_frames), dtype='float32')
        model.model.detect_language(model.encode(probe))
    return model


class LazyKoreanDialogue:
    """Called only by the serial audio consumer, after both Korean language checks."""
    def __init__(self, data_dir, threads, emit, cancelled):
        self.data_dir = Path(data_dir)
        self.threads = threads
        self.emit = emit
        self.cancelled = cancelled
        self.loaded_model = None
        self.failed = False
        self.closed = False

    def _cancelled(self):
        return self.closed or self.cancelled()

    def _failed(self, error):
        self.failed = True
        self.loaded_model = None
        if not self._cancelled():
            self.emit('fallback', 'Using Small for Korean dialogue. ' + str(error))
        raise DialogueUnavailable(str(error)) from None

    def transcribe(self, audio, **kwargs):
        if self._cancelled() or self.failed:
            raise DialogueUnavailable('Optional Korean dialogue model is inactive.')
        try:
            if self.loaded_model is None:
                self.emit('loading', 'Preparing the local NVIDIA Korean dialogue model.')
                self.loaded_model = _load_large(self.data_dir/'speech/large-v3', self.data_dir/'accelerators/cuda12/bin',
                                                self.threads, self._cancelled)
                if self._cancelled():
                    self.close()
                    raise DialogueUnavailable('Audio stopped.')
                self.emit('ready', 'NVIDIA Korean dialogue model is ready.')
            segments, info = self.loaded_model.transcribe(audio, **kwargs)
        except _OPTIONAL_ERRORS as error:
            self._failed(error)
        return self._segments(segments), info

    def _segments(self, segments):
        # faster-whisper completes decoding when the caller consumes its iterator.
        try:
            yield from segments
        except _OPTIONAL_ERRORS as error:
            self._failed(error)

    def close(self):
        self.closed = True
        self.loaded_model = None
