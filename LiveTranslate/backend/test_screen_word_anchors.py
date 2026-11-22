"""Synthetic OCR rows for placement and cover-only redraw regression."""
from pathlib import Path
from tempfile import TemporaryDirectory
import base64
import threading
import types
import unittest
from unittest.mock import patch

from foreign_text import located_foreign_segments
from screen_geometry import LocatedText, line_regions, positioned_segments
from test_worker import FakeAudio, FakeScreen, FakeText
from worker import Worker


class WordAnchorTests(unittest.TestCase):
    def test_removed_link_and_rejected_language_cannot_take_later_labels_box(self):
        line = "https://example.test/猫 고猫 | 猫 | 猫"
        indices = [i for i, c in enumerate(line) if c == "猫"]
        boxes = [(-1024 + i * 40, -50, -1008 + i * 40, -35) for i in range(4)]
        spans = [(start, start + 1, box) for start, box in zip(indices, boxes)]
        anchors = list(positioned_segments(line, spans, "ja"))
        self.assertEqual(anchors, [(("ja", "猫"), box) for box in boxes[-2:]])

    def test_offsets_preserve_raw_spacing_until_anchor_is_chosen(self):
        text = "  Open |  내 친구   \n    日本語です。  "
        rows = list(located_foreign_segments(text, "auto"))
        self.assertEqual([(r[0], r[1]) for r in rows], [("ko", "내 친구"), ("ja", "日本語です。")])
        for _, word, left, right in rows:
            self.assertEqual(word, text[left:right])
        self.assertEqual([], list(located_foreign_segments("HOME https://example.test/猫", "auto")))

    def test_nearby_labels_have_separate_boxes_at_each_size(self):
        for height in (10, 16, 32):
            with self.subTest(height=height):
                text = "設定 保存"
                x = -700
                w = 2 * height
                gap = round(1.35 * height)
                boxes = [(x, 80, x + w, 80 + height), (x + w + gap, 80, x + 2*w + gap, 80 + height)]
                words = [(0, 2, boxes[0]), (3, 5, boxes[1])]
                found = [anchor for part, spans in line_regions(text, words)
                         for anchor in positioned_segments(part, spans, "ja")]
                self.assertEqual(found, [(("ja", "設定"), boxes[0]), (("ja", "保存"), boxes[1])])

    def test_continuous_horizontal_and_vertical_runs_preserve_context(self):
        words = [(0, 2, (24, 15, 48, 31)), (3, 5, (52, 15, 76, 30))]
        region, = line_regions("문을 닫아", words)
        self.assertEqual(list(positioned_segments(*region, "ko")), [(("ko", "문을 닫아"), (24, 15, 76, 31))])
        vertical = [(0, 1, (60, -21, 75, -6)), (1, 2, (60, -4, 75, 11))]
        region, = line_regions("出口", vertical)
        self.assertEqual(list(positioned_segments(*region, "ja")), [(("ja", "出口"), (60, -21, 75, 11))])

    def test_one_word_box_with_multiple_sentences_is_shown_once(self):
        value = "行こう。急いで。"
        box = (-88, 3, -62, 194)
        self.assertEqual(list(positioned_segments(value, [(0, len(value), box)], "ja")),
                         [(("ja", value), box)])
        value = "猫。かわいい。"
        self.assertEqual(list(positioned_segments(value, [(0, len(value), box)], "auto")),
                         [(("ja", value), box)])

    def test_partially_english_token_keeps_text_without_claiming_the_english_pixels(self):
        value = "Menu保存Label"
        self.assertEqual(list(positioned_segments(value, [(0, len(value), (1, 4, 109, 20))], "ja")),
                         [(("ja", "保存"), None)])

    def test_duplicate_at_same_position_is_deduped_but_another_occurrence_remains(self):
        value = "保存"
        a = (-20, -90, 2, -70)
        b = (100, 105, 122, 125)
        frame = LocatedText(value, [(value, [(0, 2, box)]) for box in (a, a, b)])
        self.assertEqual(Worker._screen_layout(frame, "ja"), ((("ja", value), a), (("ja", value), b)))

    def test_only_the_approved_source_reaches_the_frame_with_a_real_cover(self):
        from glyph_cover import collect_covers
        from test_glyph_cover import fixture

        image, _, boxes, *_ = fixture()
        frame = LocatedText("日 | English", [("日", [(0, 1, boxes[0])]),
                                           ("English", [(0, 7, boxes[1])])])
        frame.glyph_covers = collect_covers(image, frame)
        with TemporaryDirectory() as root, patch("worker.TextEngine", FakeText), patch("worker.AudioEngine", FakeAudio), \
                patch("worker.ScreenEngine", FakeScreen):
            worker = Worker(Path(root), lambda _: None)
            try:
                original, caption = worker.translate_screen_text(frame, "ja")
            finally:
                worker.close()
        self.assertEqual(original, "日")
        row, = caption["regions"]
        self.assertEqual((row["left"], row["top"], row["width"], row["height"]),
                         (boxes[0][0], boxes[0][1], boxes[0][2]-boxes[0][0], boxes[0][3]-boxes[0][1]))
        self.assertEqual(base64.b64decode(row["cover_png"], validate=True), frame.glyph_covers[boxes[0]])

    def test_changing_cover_updates_only_placement_and_reuses_one_translation(self):
        value = "保存"
        box = (11, 7, 21, 15)
        def frame(fill):
            located = LocatedText(value, [(value, [(0, 2, box)])])
            located.glyph_covers = {box: fill}
            return located

        covers = types.ModuleType("glyph_cover")
        def attach(regions, maps):
            for row in regions:
                row["cover_png"] = maps[(row["left"], row["top"], row["left"] + row["width"],
                                        row["top"] + row["height"])]
        covers.attach_covers = attach
        done = threading.Event()
        events = []
        def send(event):
            events.append(event)
            if event["type"] == "screen_clear":
                done.set()
        frames = iter([frame("first"), frame("second"), frame("second"), "English"])
        with TemporaryDirectory() as root, patch("worker.TextEngine", FakeText), patch("worker.AudioEngine", FakeAudio), \
                patch("worker.ScreenEngine", FakeScreen), patch.dict("sys.modules", {"glyph_cover": covers}):
            worker = Worker(Path(root), send)
            try:
                with patch.object(worker.screen, "recognize", side_effect=lambda *args: next(frames, ""), create=True), \
                        patch.object(worker.text, "translate", wraps=worker.text.translate) as translate:
                    worker.start_screen({"source": "ja", "interval": 0.5})
                    self.assertTrue(done.wait(5))
                    self.assertEqual(1, translate.call_count)
            finally:
                worker.close()
        screens = [e for e in events if e["type"] == "screen"]
        self.assertEqual(["first", "second"], [e["regions"][0]["cover_png"] for e in screens])
        self.assertEqual([False, True], [e.get("layout_only", False) for e in screens])


if __name__ == "__main__":
    unittest.main()
