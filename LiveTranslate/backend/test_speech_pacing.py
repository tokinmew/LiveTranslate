"""Packet-level regressions for deliberate speech with ordinary inter-word pauses."""
import struct
import unittest

from audio_chunks import PhraseBuffer


class SpeechPacingTests(unittest.TestCase):
    @staticmethod
    def pcm(milliseconds, level=0):
        return struct.pack("<h", level) * (16 * milliseconds)

    def capture(self, pieces, packet=20):
        output = []
        buffer = PhraseBuffer(16000, 1, 5, output.append)
        clock = 0.0
        recording = b"".join(self.pcm(length, level) for length, level in pieces)
        width = 32 * packet
        for start in range(0, len(recording), width):
            payload = recording[start:start + width]
            clock += len(payload) / 32000
            buffer.add(payload, now=clock)
        buffer.flush_idle(clock + 1)
        buffer.flush_idle(clock + 2)
        return output

    def test_slow_words_keep_their_context_across_half_second_pauses(self):
        for packet in (10, 20, 100):
            with self.subTest(packet=packet):
                out = self.capture([(240, 80), (500, 0), (320, 100), (580, 0), (280, 90), (900, 0)], packet)
                self.assertEqual(1, len(out))
                for length, level in ((240, 80), (320, 100), (280, 90)):
                    self.assertIn(self.pcm(length, level), out[0])

    def test_idle_loopback_retains_a_word_arriving_after_half_second(self):
        out = []
        buffer = PhraseBuffer(16000, 1, 5, out.append)
        first, second = self.pcm(240, 80), self.pcm(260, 90)
        buffer.add(first, now=.24)
        buffer.flush_idle(.74)
        self.assertEqual(0, len(out))
        # The next callback contains a complete 260 ms packet after the pause.
        buffer.add(second, now=1.0)
        buffer.flush_idle(1.8)
        self.assertEqual(1, len(out))
        self.assertEqual([first + second], out)

    def test_a_completed_turn_still_releases_without_next_callback(self):
        out = []
        buffer = PhraseBuffer(16000, 1, 5, out.append)
        spoken = self.pcm(300, 90)
        buffer.add(spoken, now=.3)
        buffer.flush_idle(1.1)
        buffer.flush_idle(3)
        self.assertEqual([spoken], out)

    def test_distinct_turns_remain_separate_after_a_full_pause(self):
        out = self.capture([(260, 80), (900, 0), (280, 90), (900, 0)])
        self.assertEqual(2, len(out))
        self.assertIn(self.pcm(260, 80), out[0])
        self.assertNotIn(self.pcm(280, 90), out[0])
        self.assertIn(self.pcm(280, 90), out[1])

    def test_long_continuous_speech_and_quiet_background_stay_bounded(self):
        out = self.capture([(14000, 90)])
        self.assertEqual(14 * 32000, sum(map(len, out)))
        self.assertLessEqual(max(map(len, out)), int(5.9 * 32000))
        self.assertEqual([], self.capture([(12000, 2), (1200, 0)]))

    def test_hard_duration_boundaries_preserve_every_pcm_sample_once(self):
        # A varying waveform detects duplication or omission at each cut.
        recording = b"".join(struct.pack("<h", 30 + index % 3071) for index in range(16000 * 14))
        out = []
        buffer = PhraseBuffer(16000, 1, 5, out.append)
        for offset in range(0, len(recording), 2518):
            payload = recording[offset:offset + 2518]
            buffer.add(payload, now=(offset + len(payload)) / 32000)
        buffer.flush_idle(15)
        self.assertEqual(len(recording), sum(map(len, out)))
        self.assertTrue(recording == b"".join(out))
        self.assertLessEqual(max(map(len, out)), int(5.9 * 32000))

    def test_duration_limit_uses_an_earlier_pause_to_keep_final_word_intact(self):
        out = self.capture([(3400, 80), (500, 0), (3000, 90)])
        self.assertEqual(2, len(out))
        self.assertTrue(self.pcm(3400, 80) in out[0])
        self.assertTrue(self.pcm(3000, 90) in out[1])
        self.assertEqual(6900 * 32, sum(map(len, out)))


if __name__ == "__main__":
    unittest.main()
