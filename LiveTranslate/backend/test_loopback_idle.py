"""Synthetic PCM for loopback drivers that switch between silent packets and idle."""
import struct
import unittest

from audio_chunks import PhraseBuffer


class LoopbackIdleTests(unittest.TestCase):
    def setUp(self):
        self.output = []
        self.buf = PhraseBuffer(16000, 2, 5, self.output.append)

    @staticmethod
    def pcm(milliseconds, level=0):
        return struct.pack("<hh", 0, level) * (16 * milliseconds)

    def feed(self, start_ms, count, level, packet=20):
        for offset in range(packet, count + 1, packet):
            self.buf.add(self.pcm(packet, level), (start_ms + offset) / 1000)

    def test_observed_silence_is_part_of_the_loopback_pause(self):
        self.feed(0, 80, 8)
        self.feed(80, 240, 0)
        self.buf.flush_idle(.470)
        self.assertFalse(self.output)
        self.buf.flush_idle(.490)
        self.assertEqual([self.pcm(80, 8) + self.pcm(240)], self.output)

    def test_idle_after_voice_still_uses_full_driver_timeout(self):
        self.feed(0, 80, 8)
        self.buf.flush_idle(.44)
        self.assertFalse(self.output)
        self.buf.flush_idle(.48)
        self.assertEqual([self.pcm(80, 8)], self.output)

    def test_last_partial_voiced_frame_gets_full_timeout(self):
        self.feed(0, 80, 8)
        self.feed(80, 240, 0)
        self.buf.add(self.pcm(10, 10), .330)
        self.buf.flush_idle(.55)
        self.assertFalse(self.output)
        self.buf.flush_idle(.74)
        self.assertEqual([self.pcm(80, 8) + self.pcm(240) + self.pcm(10, 10)], self.output)

    def test_contiguous_speech_delivered_in_a_large_callback_stays_together(self):
        self.feed(0, 80, 8)
        self.feed(80, 320, 0)
        self.buf.add(self.pcm(240, 10), .640)
        self.assertFalse(self.output)
        self.buf.flush_idle(1.04)
        self.assertEqual([self.pcm(80, 8) + self.pcm(320) + self.pcm(240, 10)], self.output)

    def test_long_driver_packets_get_a_grace_period_before_idle(self):
        self.feed(0, 100, 8, 100)
        self.feed(100, 300, 0, 100)
        self.buf.flush_idle(.52)
        self.assertFalse(self.output)
        self.buf.flush_idle(.60)
        self.assertEqual([self.pcm(100, 8) + self.pcm(300)], self.output)

    def test_short_gap_inside_one_word_does_not_duplicate_the_caption(self):
        self.feed(0, 60, 10)
        self.feed(60, 140, 0)
        self.buf.flush_idle(.3)
        self.buf.add(self.pcm(80, 8), .40)
        self.assertFalse(self.output)
        self.buf.flush_idle(.8)
        self.assertEqual([self.pcm(60, 10) + self.pcm(140) + self.pcm(80, 8)], self.output)

    def test_minimum_length_and_very_quiet_replies_unchanged(self):
        for voiced, level, expected in ((40, 200, 0), (60, 6, 1), (80, 3, 0)):
            with self.subTest(voiced=voiced, level=level):
                self.setUp()
                self.feed(0, voiced, level)
                self.feed(voiced, 220, 0)
                self.buf.flush_idle(.8)
                self.assertEqual(expected, len(self.output))
