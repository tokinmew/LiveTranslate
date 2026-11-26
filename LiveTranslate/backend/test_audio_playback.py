"""Controlled PCM and device fixtures. No microphone or playback is captured."""
from pathlib import Path
import struct
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from audio_chunks import CapturedPhrase, PendingPhrases, PhraseBuffer
from audio_devices import DEFAULT_PLAYBACK, DEFAULT_PLAYBACK_AND_MIC, Endpoint, Route, capture_routes
from audio_engine import AudioEngine, _Session, pcm_to_mono
from speech_decode import downmix, speech_captions


def device(index, name, loopback=False, channels=2, rate=48000):
    return dict(index=index, name=name, isLoopbackDevice=loopback, hostApi=2,
                maxInputChannels=channels, defaultSampleRate=rate)


class Devices:
    gaming = device(10, "Gaming [Loopback]", True, 8, 96000)
    calls = device(11, "Chat [Loopback]", True)
    mic = device(1, "Headset microphone", False, 1)

    def get_loopback_device_info_generator(self):
        return iter([self.calls, self.gaming])
    def get_default_wasapi_device(self, *, d_in):
        return self.mic
    def get_default_wasapi_loopback(self):
        return self.gaming
    def get_device_info_by_index(self, index):
        return {1:self.mic, 10:self.gaming, 11:self.calls}[index]


DEFAULTS = (Endpoint("render-game", "Gaming"), Endpoint("render-chat", "Chat"), Endpoint("input", "Headset microphone"))


class PlaybackRouteTests(unittest.TestCase):
    def test_default_listens_to_media_and_separate_calls(self):
        routes = capture_routes(Devices(), DEFAULT_PLAYBACK, DEFAULTS)
        self.assertEqual([("pc",10), ("pc",11)], [r.key for r in routes])

    def test_default_roles_on_same_endpoint_open_only_one_stream(self):
        same = (DEFAULTS[0], DEFAULTS[0])
        self.assertEqual([("pc",10)], [r.key for r in capture_routes(Devices(), DEFAULT_PLAYBACK, same)])

    def test_renamed_default_with_identical_identity_is_deduplicated(self):
        same = (DEFAULTS[0], Endpoint(DEFAULTS[0].id, "Chat"))
        self.assertEqual([("pc",10)], [r.key for r in capture_routes(Devices(), DEFAULT_PLAYBACK, same)])

    def test_combined_adds_an_independent_microphone(self):
        routes = capture_routes(Devices(), DEFAULT_PLAYBACK_AND_MIC, DEFAULTS)
        self.assertEqual([("pc",10),("pc",11),("microphone",1)], [r.key for r in routes])

    def test_no_communications_role_can_use_driver_media_only(self):
        self.assertEqual([("pc",10)], [r.key for r in capture_routes(Devices(), DEFAULT_PLAYBACK, ())])

    def test_cannot_substitute_mic_for_missing_render(self):
        audio=Devices()
        audio.get_default_wasapi_loopback=lambda: audio.mic
        with self.assertRaisesRegex(RuntimeError, "no available default playback"):
            capture_routes(audio, DEFAULT_PLAYBACK, ())

    def test_other_named_device_is_not_confused_with_substring(self):
        audio=Devices()
        wrong = (Endpoint("a","Game"), None)
        with self.assertRaisesRegex(RuntimeError, "no available default playback"):
            capture_routes(audio, DEFAULT_PLAYBACK, wrong)

    def test_named_loopback_or_mic_never_includes_other_routes(self):
        self.assertEqual([("pc",11)],[r.key for r in capture_routes(Devices(),11,DEFAULTS)])
        self.assertEqual([("microphone",1)],[r.key for r in capture_routes(Devices(),1,DEFAULTS)])

    def test_combined_rejects_loopback_disguised_as_default_mic(self):
        audio = Devices()
        audio.get_default_wasapi_device=lambda **kw:audio.gaming
        with self.assertRaisesRegex(RuntimeError, "microphone input"):
            capture_routes(audio, DEFAULT_PLAYBACK_AND_MIC, DEFAULTS)


class PcmTests(unittest.TestCase):
    def test_opposite_phase_channels_retain_dialogue(self):
        import numpy as np
        sine = np.sin(np.arange(16000)*.07).astype(np.float32)
        output = downmix(np.column_stack([sine, -sine]))
        self.assertTrue(np.allclose(output,sine))

    def test_windows_centre_dialogue_not_lost_to_surround_and_lfe(self):
        import numpy as np
        x = np.zeros((3000,8), np.float32)
        x[:,2]=.2
        x[:,3]=.8
        self.assertTrue(np.allclose(downmix(x), .1))
        x[:,2]=0
        self.assertTrue(np.allclose(downmix(x), 0))

    def test_odd_driver_fragment_has_no_out_of_bounds_read(self):
        self.assertEqual([],pcm_to_mono(b"\x01\x02\x03",2,16000).tolist())
        self.assertEqual([.25],pcm_to_mono(struct.pack("<hh",8192,8192)+b"\0",2,16000).tolist())

    def test_silence_never_enqueues_a_phrase(self):
        result = []
        b = PhraseBuffer(16000,1,3,result.append)
        b.add(b"\0"*320000,now=1)
        b.flush_idle(2)
        self.assertEqual([],result)

    def test_idle_playback_flushes_final_short_utterance_exactly_once(self):
        result = []
        b = PhraseBuffer(16000,1,5,result.append)
        whole = struct.pack("<h",900)*16000
        for i in range(0,len(whole),1370):
            b.add(whole[i:i+1370], now=5)
        self.assertFalse(result)
        b.flush_idle(5.20)
        self.assertFalse(result)
        b.flush_idle(5.55)
        b.flush_idle(10)
        self.assertEqual([whole],result)

    def test_short_voices_separated_at_pauses_preserve_preroll(self):
        result = []
        b = PhraseBuffer(16000,1,5,result.append)
        speech = struct.pack("<h",60) * 8000
        silence = b"\0\0"*14400
        b.add(silence + speech + silence + speech + silence, now=1)
        self.assertEqual(2,len(result))
        for data in result:
            self.assertIn(speech,data)
            self.assertTrue(data.startswith(b"\0\0"*640))

    def test_quiet_centre_channel_syllables_survive_packet_boundaries_and_idle(self):
        for rate, channels, ms in ((11025, 1, 61), (16000, 1, 75), (48000, 2, 95), (96000, 8, 119)):
            with self.subTest(rate=rate, channels=channels):
                result = []
                b = PhraseBuffer(rate, channels, 3, result.append)
                values = [0] * channels
                values[2 if channels >= 3 else 0] = 12
                syllable = struct.pack("<" + "h" * channels, *values) * round(rate * ms / 1000)
                for i in range(0, len(syllable), 397):
                    b.add(syllable[i:i+397], now=0)
                b.flush_idle(.2)
                self.assertEqual([], result)
                b.flush_idle(.45)
                b.flush_idle(2)
                self.assertEqual([syllable], result)

    def test_gap_before_next_callback_finishes_each_reply(self):
        result = []
        b = PhraseBuffer(16000, 1, 3, result.append)
        first = struct.pack("<h", 90) * 1481
        second = struct.pack("<h", 40) * 1701
        b.add(first + b"\xff", now=1)
        b.add(second, now=1.9)
        b.flush_idle(2.8)
        self.assertEqual([first, second], result)

    def test_single_click_and_quiet_background_do_not_enter_queue(self):
        result = []
        b = PhraseBuffer(16000, 1, 3, result.append)
        b.add(struct.pack("<h", 32000) + struct.pack("<h", 2) * 16000, now=1)
        b.flush_idle(2)
        self.assertEqual([], result)

    def test_continuous_audio_is_bounded(self):
        result=[]
        b=PhraseBuffer(16000,1,3,result.append)
        b.add(struct.pack("<h",2400)*160000, now=1)
        b.flush_idle(2)
        self.assertEqual(320000, sum(map(len,result)))
        self.assertLessEqual(max(map(len,result)), 32000*3.8)

    def test_busy_game_does_not_evict_microphone_or_calls(self):
        q=PendingPhrases()
        def put(source,n,stamp):
            return q.push(CapturedPhrase(b"test",16000,1,source,n,stamp))
        put("microphone",1,1)
        put("pc",11,2)
        for stamp in range(3,20): dropped=put("pc",10,stamp)
        self.assertTrue(dropped)
        retained = [q.next(.01) for _ in range(2 + q.MAX_PHRASES)]
        self.assertEqual([1,11] + [10] * q.MAX_PHRASES, [phrase.endpoint for phrase in retained])
        self.assertEqual([1,2] + list(range(20 - q.MAX_PHRASES, 20)), [phrase.captured for phrase in retained])
        self.assertIsNone(q.next(.001))

    def test_long_phrases_obey_original_per_source_audio_budget(self):
        q = PendingPhrases(chunk_seconds=3)
        data = b"\0\0" * round(3.74 * 16000)
        for stamp in range(3):
            dropped = q.push(CapturedPhrase(data, 16000, 1, "pc", 10, stamp))
            self.assertEqual(stamp == 2, dropped)
        self.assertEqual([1, 2], [q.next(.01).captured for _ in range(2)])
        self.assertIsNone(q.next(.001))


def confidence(code, probability=.9, english=.01):
    return SimpleNamespace(language=code, language_probability=probability,
                           all_language_probs=[("en",english),(code,probability)])


def segment(text,start=0,end=1):
    return SimpleNamespace(text=text, start=start,end=end,avg_logprob=-.2,
                           no_speech_prob=.02,compression_ratio=1.15)


class DecodeTests(unittest.TestCase):
    def setUp(self):
        import numpy as np
        self.samples = (np.sin(np.arange(48000)*.03)*.2).astype(np.float32)
        self.spans = patch("speech_decode._speech_spans",return_value=[{"start":0,"end":48000}])
        self.spans.start()
        self.addCleanup(self.spans.stop)

    def test_english_mismatched_and_uncertain_speech_skip_before_lazy_decoder(self):
        for info, chosen in [(confidence("en"),"ja"),(confidence("en"),"auto"),
                             (confidence("fr"),"es"),(confidence("ja",.44,.40),"ja"),
                             (confidence("ja",.9),"ko")]:
            def forbidden():
                raise AssertionError("English or unrelated source reached decoding")
                yield
            m=Mock()
            m.transcribe.return_value=(forbidden(),info)
            translate=Mock(side_effect=AssertionError("Translation ran"))
            self.assertEqual([],list(speech_captions(m,self.samples,chosen,translate)))
            self.assertEqual(1,m.transcribe.call_count)
            self.assertIsNone(m.transcribe.call_args.kwargs["language"])

    def test_transcript_without_native_script_never_translates(self):
        m=Mock()
        m.transcribe.return_value=([segment("Open Settings")],confidence("ko"))
        tr=Mock(side_effect=AssertionError("English was translated"))
        self.assertEqual([],list(speech_captions(m,self.samples,"auto",tr)))
        self.assertEqual(1,m.transcribe.call_count)

    def test_word_groups_exclude_english_and_preserve_actual_language(self):
        m=Mock()
        m.transcribe.return_value=([segment("こんにちは"),segment("English only",1,2),segment("日本語",2,3)],confidence("ja"))
        tr=Mock(side_effect=[{"text":"Hello"},{"text":"Japanese"}])
        captions=list(speech_captions(m,self.samples,"auto",tr))
        self.assertEqual(["こんにちは","日本語"],[r["original"] for r in captions])
        self.assertEqual(["Hello","Japanese"],[r["text"] for r in captions])
        self.assertEqual(1,m.transcribe.call_count)

    def test_missing_text_pack_fallback_only_decodes_approved_time_span(self):
        m=Mock()
        m.transcribe.side_effect=[
            ([segment("Only English",0,1),segment("日本語",1,2)],confidence("ja")),
            ([segment("Japanese")],confidence("ja"))]
        captions=list(speech_captions(m,self.samples,"ja",lambda t,l: None))
        self.assertEqual(["Japanese"],[r["text"] for r in captions])
        self.assertEqual("translate",m.transcribe.call_args.kwargs["task"])
        self.assertEqual(16000, len(m.transcribe.call_args.args[0]))

    def test_ignored_source_cannot_fall_back_to_speech_translation(self):
        m=Mock()
        m.transcribe.return_value=([segment("日本語")],confidence("ja"))
        out=list(speech_captions(m,self.samples,"ja",lambda t,l:{"text":"","ignored":True}))
        self.assertEqual([],out)
        self.assertEqual(1,m.transcribe.call_count)

    def test_largely_untranslated_output_retries_approved_source_only(self):
        m=Mock()
        m.transcribe.side_effect=[([segment("音声認識テスト")],confidence("ja")),
                                  ([segment("Speech recognition test")],confidence("ja"))]
        out=list(speech_captions(m,self.samples,"ja",lambda t,l:{"text":"音声認識 test 音声"}))
        self.assertEqual("Speech recognition test",out[0]["text"])
        self.assertEqual(2,m.transcribe.call_count)

    def test_embedded_proper_name_does_not_trigger_fallback(self):
        m=Mock()
        m.transcribe.return_value=([segment("京都駅に到着しました")],confidence("ja"))
        out=list(speech_captions(m,self.samples,"ja",lambda t,l:{"text":"Arrived at 京都駅 station."}))
        self.assertEqual("Arrived at 京都駅 station.",out[0]["text"])
        self.assertEqual(1,m.transcribe.call_count)

    def test_native_only_echo_is_silent_if_both_translation_paths_fail(self):
        model = Mock()
        model.transcribe.side_effect = [
            ([segment("한국어 문장")], confidence("ko")),
            ([segment("한국어 문장")], confidence("ko")),
        ]
        captions = list(speech_captions(model, self.samples, "ko", lambda *_: {"text": "한국어 문장"}))
        self.assertEqual([], captions)
        self.assertEqual(2, model.transcribe.call_count)

    def test_short_native_echo_is_silent_and_arabic_numeral_translation_survives(self):
        for result, expected, calls in (("東京", [], 2), ("300", ["300"], 1)):
            with self.subTest(result=result):
                model = Mock()
                model.transcribe.return_value = ([segment("三百")], confidence("ja"))
                captions = speech_captions(model, self.samples, "ja", lambda *_: {"text": result})
                self.assertEqual(expected, [caption["text"] for caption in captions])
                self.assertEqual(calls, model.transcribe.call_count)

    def test_cancel_during_translation_never_emits(self):
        m=Mock()
        m.transcribe.return_value=([segment("안녕하세요")],confidence("ko"))
        stop=threading.Event()
        def tr(text,code):
            stop.set()
            return {"text":"Hello"}
        self.assertEqual([],list(speech_captions(m,self.samples,"auto",tr,stop.is_set)))


class BundledRecordingChecks(unittest.TestCase):
    def test_validates_exact_bundled_size_and_hash(self):
        import hashlib
        import json
        from speech_checks import _bundled_fixture
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            target=folder/"ja.wav"
            target.write_bytes(b"fixture")
            entry={"file":"ja.wav","bytes":7,"sha256":hashlib.sha256(b"fixture").hexdigest()}
            (folder/"manifest.json").write_text(json.dumps({"ja":entry}),"utf-8")
            self.assertEqual(target,_bundled_fixture(folder,"ja"))
            target.write_bytes(b"altered")
            with self.assertRaisesRegex(ValueError,"SHA-256"):
                _bundled_fixture(folder,"ja")
            target.write_bytes(b"short")
            with self.assertRaisesRegex(ValueError,"size"):
                _bundled_fixture(folder,"ja")

    def test_recognition_smoke_checks_affirmative_test_subject(self):
        from speech_checks import _matches_recognition_phrase
        self.assertTrue(_matches_recognition_phrase("Hello, this is a voice recognition test."))
        self.assertFalse(_matches_recognition_phrase("This isn't a speech test."))
        self.assertFalse(_matches_recognition_phrase("This is the first test."))


class CaptureNegotiationTests(unittest.TestCase):
    pa = SimpleNamespace(paInt16=8,paFloat32=1,paContinue=0,paComplete=1)

    def test_fallback_keeps_route_and_converts_float_to_i16(self):
        import numpy as np
        audio = Mock()
        opened = []
        def open_stream(**kw):
            opened.append(kw)
            if kw["channels"]==2 and kw["format"]==1:
                return object()
            raise OSError(-9998,"Unsupported")
        audio.open.side_effect=open_stream
        sess=_Session(0,10,"base","ja",3,1,"s")
        _,phrases=AudioEngine._open_device(sess,self.pa,audio,Route(Devices.gaming,"pc"))
        self.assertTrue(all(r["input_device_index"]==10 and not r["start"] for r in opened))
        payload=np.full((48000,2),.125,np.float32).tobytes()
        self.assertEqual((None,0),opened[-1]["stream_callback"](payload,48000,{},0))
        phrases.flush_idle(time.monotonic()+1)
        pkt=sess.chunks.next(.01)
        self.assertEqual(("pc",10,96000,2),(pkt.source,pkt.endpoint,pkt.rate,pkt.channels))
        self.assertEqual(4096,struct.unpack_from("<h",pkt.payload)[0])

    def test_partial_combined_failure_closes_all_without_starting_capture(self):
        opened=[]
        class Port(Devices):
            def open(self,**kw):
                if kw["input_device_index"]==11:
                    raise OSError(-9985,"Device unavailable")
                s=Mock()
                opened.append(s)
                return s
            def terminate(self): pass
        pa=SimpleNamespace(PyAudio=Port,paInt16=8,paContinue=0,paComplete=1)
        with tempfile.TemporaryDirectory() as directory:
            engine=AudioEngine(Path(directory),lambda e:None)
            sess=_Session(0,-3,"base","auto",3,1,"s")
            with patch("audio_engine.windows_default_routes",return_value=DEFAULTS):
                with self.assertRaises(OSError): engine._capture_devices(sess,pa)
            self.assertEqual(1,len(opened))
            opened[0].start_stream.assert_not_called()
            opened[0].close.assert_called_once()

    def test_stale_caption_after_audio_reroute_is_suppressed(self):
        msgs=[]
        with tempfile.TemporaryDirectory() as directory:
            e=AudioEngine(Path(directory),msgs.append)
            s=_Session(0,-2,"base","auto",5,1,"s")
            s.route_epoch=1
            e._session_event(s,{"type":"audio","text":"stale"},0)
            e._session_event(s,{"type":"audio","text":"new"},1)
            self.assertEqual(["new"],[m["text"] for m in msgs])

    def test_off_discards_pending_recorded_pcm_immediately(self):
        with tempfile.TemporaryDirectory() as directory:
            e=AudioEngine(Path(directory),lambda x: None)
            s=_Session(0,-2,"base","auto",5,1,"s")
            s.chunks.push(CapturedPhrase(b"private PCM",16000,1,"pc",11,time.monotonic()))
            e._current=s
            e.stop()
            s.chunks.push(CapturedPhrase(b"late callback",16000,1,"pc",11,time.monotonic()))
            self.assertIsNone(s.chunks.next(.001))

    def test_named_output_reusing_mic_index_fails_without_opening_it(self):
        a=Devices()
        a.terminate=Mock()
        a.open=Mock()
        pa=SimpleNamespace(PyAudio=lambda:a,paInt16=8)
        with tempfile.TemporaryDirectory() as directory:
            e=AudioEngine(Path(directory),lambda event:None)
            s=_Session(0,1,"base","auto",5,1,"s")
            s.selected_identity=("Old output [Loopback]","pc")
            with self.assertRaisesRegex(RuntimeError,"selected audio device changed"):
                e._capture_devices(s,pa)
            a.open.assert_not_called()
            a.terminate.assert_called_once()

    def test_live_default_switch_reopens_and_closes_both_stream_sets(self):
        changed=threading.Event()
        restarted=threading.Event()
        ports=[]
        class Port(Devices):
            def __init__(self):
                self.streams=[]
                self.closed=False
                ports.append(self)
            def open(self,**kwargs):
                s=Mock()
                s.is_active.side_effect=lambda:len(ports)>1 or not changed.is_set()
                self.streams.append((kwargs["input_device_index"],s))
                return s
            def terminate(self):
                self.closed=True
        def defaults(mic):
            return (DEFAULTS[1],DEFAULTS[1]) if changed.is_set() else DEFAULTS
        def emit(event):
            if event.get("state")=="active":
                if not changed.is_set(): changed.set()
                else: restarted.set()
        pa=SimpleNamespace(PyAudio=Port,paInt16=8,paContinue=0,paComplete=1)
        import sys
        with tempfile.TemporaryDirectory() as directory:
            e=AudioEngine(Path(directory),emit)
            s=_Session(0,-2,"base","auto",3,1,"device switch")
            with patch.dict(sys.modules,{"pyaudiowpatch":pa}), patch("audio_engine.windows_default_routes",defaults):
                t=threading.Thread(target=e._capture,args=(s,))
                t.start()
                try:
                    self.assertTrue(restarted.wait(1.5))
                finally:
                    s.stop.set()
                    t.join(2)
            self.assertFalse(t.is_alive())
            self.assertEqual([[10,11],[11]],[[i for i,_ in p.streams] for p in ports])
            self.assertTrue(all(p.closed for p in ports))
            self.assertEqual(1,s.route_epoch)
            for p in ports:
                for _,stream in p.streams:
                    stream.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
