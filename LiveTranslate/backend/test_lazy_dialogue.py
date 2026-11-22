from pathlib import Path
from tempfile import TemporaryDirectory
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np
from audio_engine import AudioEngine
from dialogue_acceleration import DialogueUnavailable, LazyKoreanDialogue, _load_large
from korean_dialogue import accurate_turn
from speech_decode import speech_captions
from worker import Worker


class LazyDialogueTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.proxy = LazyKoreanDialogue(Path('data'),2,lambda state,msg:self.events.append(state),lambda:False)

    def test_non_korean_and_failed_independent_gate_do_not_load(self):
        audio = np.ones(48000,'float32')*.05
        small = SimpleNamespace(dialogue_model=self.proxy,sensevoice=Mock())
        with patch('dialogue_acceleration._load_large') as load:
            for lang in ('en','ja','zh'):
                info = SimpleNamespace(language=lang,language_probability=.99)
                self.assertIsNone(accurate_turn(small,audio,audio,'auto',info,lambda:False,None))
            info = SimpleNamespace(language='ko',language_probability=.99)
            small.sensevoice.transcribe_trimmed.return_value = {'language':'en','probs':{'en':.99},'tags':['<|Speech|>'],'text':'English'}
            self.assertIsNone(accurate_turn(small,audio,audio,'auto',info,lambda:False,None))
            load.assert_not_called()
        self.assertEqual([],self.events)

    def test_loads_only_on_first_gated_transcribe_and_close_releases(self):
        model=Mock()
        model.transcribe.side_effect=lambda *a,**k:(iter(['one']),object())
        with patch('dialogue_acceleration._load_large',return_value=model) as load:
            for _ in range(2):
                segments,_=self.proxy.transcribe([1],task='transcribe')
                self.assertEqual(['one'],list(segments))
            self.assertEqual(['loading','ready'],self.events)
            self.proxy.close()
            self.assertIsNone(self.proxy.loaded_model)
            with self.assertRaises(DialogueUnavailable):
                self.proxy.transcribe([1])
            self.assertEqual(1,load.call_count)

    def test_failed_load_does_not_retry_or_repeatedly_warn(self):
        with patch('dialogue_acceleration._load_large',side_effect=OSError('Missing files')) as load:
            for _ in range(2):
                with self.assertRaises(DialogueUnavailable):
                    self.proxy.transcribe([1])
            self.assertEqual(['loading','fallback'],self.events)
            self.assertEqual(1,load.call_count)

    def test_native_failure_during_lazy_segment_consumption(self):
        def fail():
            yield 'partial'
            raise RuntimeError('Device went away')
        model=Mock()
        model.transcribe.return_value = (fail(),object())
        with patch('dialogue_acceleration._load_large',return_value=model):
            segments,_=self.proxy.transcribe([1])
            self.assertEqual('partial',next(segments))
            with self.assertRaises(DialogueUnavailable):
                next(segments)
            self.assertIsNone(self.proxy.loaded_model)
            self.assertEqual(['loading','ready','fallback'],self.events)

    def test_gpu_absent_never_constructs_a_large_cpu_model(self):
        with patch('ctranslate2.get_cuda_device_count',return_value=0),patch('faster_whisper.WhisperModel') as factory:
            with self.assertRaisesRegex(OSError,'NVIDIA'):
                _load_large('unused','unused',2,lambda:False)
            factory.assert_not_called()

    def test_cancelled_attempt_does_not_load(self):
        self.proxy.cancelled=lambda:True
        with patch('dialogue_acceleration._load_large') as load:
            with self.assertRaises(DialogueUnavailable):
                self.proxy.transcribe([1])
            load.assert_not_called()
        self.assertEqual([],self.events)

    def test_unavailable_turn_continues_through_small_decoder(self):
        info=SimpleNamespace(language='en',language_probability=.99,all_language_probs=[('en',.99)])
        model=Mock(dialogue_model=self.proxy)
        model.transcribe.return_value=(iter([]),info)
        samples=np.ones(48000,'float32')*.1
        with (patch('speech_decode._speech_spans',return_value=[{'start':0,'end':48000}]),
              patch('korean_dialogue.accurate_turn',side_effect=DialogueUnavailable('Unavailable')),
              patch('speech_decode._accepted_language',return_value=False) as fallback):
            self.assertEqual([],list(speech_captions(model,samples)))
            fallback.assert_called_once()

    def test_failed_optional_turn_still_yields_the_same_positive_caption(self):
        info=SimpleNamespace(language='ko',language_probability=.99,all_language_probs=[('ko',.99)])
        seg=SimpleNamespace(text='연주를 시작합니다.',start=.1,end=2.4,compression_ratio=1.,avg_logprob=-.2,no_speech_prob=.01)
        def transcribe(*a,**k):return iter([seg]),info
        small=SimpleNamespace(transcribe=transcribe)
        samples=np.ones(48000,'float32')*.1
        translate=lambda *_:{'text':'The performance begins.','language':'ko'}
        with patch('speech_decode._speech_spans',return_value=[{'start':0,'end':48000}]):
            ordinary=list(speech_captions(small,samples,translate_source=translate))
            small.dialogue_model=self.proxy
            with patch('korean_dialogue.accurate_turn',side_effect=DialogueUnavailable('Unavailable')):
                actual=list(speech_captions(small,samples,translate_source=translate))
        self.assertEqual('The performance begins.',ordinary[0]['text'])
        self.assertEqual(ordinary,actual)

    def test_session_teardown_detaches_proxy_from_cached_small_model(self):
        with TemporaryDirectory() as tmp:
            small=SimpleNamespace(sensevoice=object())
            received=[]
            finished=threading.Event()
            def emit(event):
                if event.get('state')=='stopped':finished.set()
            engine=AudioEngine(Path(tmp),emit)
            def capture(session):
                session.ready.set()
                session.capture_done.set()
            def translate(session,model):
                received.append(getattr(model,'dialogue_model',None))
            with (patch.object(engine,'installed_models',return_value=['small']),patch.object(engine,'_load_model',return_value=small),
                  patch.object(engine,'_capture',capture),patch.object(engine,'_translate',translate)):
                try:
                    for mode in ('standard','nvidia'):
                        finished.clear()
                        engine.start(0,model='small',korean_dialogue=mode)
                        self.assertTrue(finished.wait(3))
                    self.assertIsNone(received[0])
                    self.assertTrue(received[1].closed)
                    self.assertFalse(hasattr(small,'dialogue_model'))
                finally:
                    engine.close()

    def test_worker_command_default_and_selection(self):
        with TemporaryDirectory() as tmp:
            worker=Worker(Path(tmp),lambda _:None)
            try:
                with patch.object(worker.audio,'start') as start:
                    for options,expected in (({},'standard'),({'korean_dialogue':'nvidia'},'nvidia')):
                        worker.dispatch(dict(command='start_audio',device_id=0,model='small',**options))
                        worker.execute(worker.jobs.get_nowait())
                        self.assertEqual(expected,start.call_args.kwargs['korean_dialogue'])
            finally:
                worker.close()
