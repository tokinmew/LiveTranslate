"""Source pixels, wording, placement, misses, and genuinely changing content."""
import unittest
from collections import OrderedDict
from PIL import Image, ImageChops, ImageDraw
from screen_geometry import LocatedText
from screen_tracking import ScreenCaptionHistory, ScreenTracker, sample_frame


BOX = (18, 10, 70, 32)
SECOND = (101, 12, 153, 34)


def observed(text, boxes=(BOX,)):
    return LocatedText(text, [(text, [(0,len(text),b)]) for b in boxes] if text else [])


def panel(fg=240, bg=20):
    image = Image.new("RGB", (200,48), (bg,)*3)
    draw = ImageDraw.Draw(image)
    for left, top, _, bottom in (BOX, SECOND):
        for i in range(6):
            x = left+5+i*7
            draw.line((x,top+3,x,bottom-3), fill=(fg,)*3, width=3)
    return image


class ScreenTrackingTests(unittest.TestCase):
    def setUp(self):
        self.tracker = ScreenTracker()

    def frame(self, image, text, boxes=(BOX,), lang="ja", colors=42):
        original = sample_frame(observed(text, boxes), (image,0,0),
                                (lang, tuple(self.tracker.previous)))
        measured = tuple(((lang, text), box) for box in boxes) if text else ()
        placements, held = self.tracker.placements(measured, original.screen_samples)
        result = {"regions": [{"original": key[1], "text": "EN "+key[1], "left": b[0], "top": b[1],
                               "width": b[2]-b[0], "height": b[3]-b[1], "background_rgb": colors,
                               "cover_png": "current"} for key,b in placements]}
        self.tracker.accept(placements, result, original.screen_samples, held)
        return [(key[1],b) for key,b in placements], result["regions"]

    def test_same_pixels_keep_original_even_when_ocr_moves_different_letter(self):
        image = panel()
        first = "お知らせ"
        self.frame(image, first)
        shifted = tuple(v+1 for v in BOX)
        second, rows = self.frame(image, "お和らせ", (shifted,), colors=420)
        self.assertEqual([(first,shifted)], second)
        self.assertEqual(420,rows[0]["background_rgb"])

    def test_same_ink_recolored_source_keeps_original_but_updates_local_color(self):
        self.frame(panel(), "設定")
        placed, rows = self.frame(panel(fg=24,bg=230), "設足", colors=0xE6E6E6)
        self.assertEqual([("設定", BOX)], placed)
        self.assertEqual(0xE6E6E6, rows[0]["background_rgb"])

    def test_scrolling_source_and_ocr_box_move_together(self):
        image = panel()
        self.frame(image, "通知")
        moved = ImageChops.offset(image,3,0)
        box = BOX[0]+3,BOX[1],BOX[2]+3,BOX[3]
        words,_ = self.frame(moved,"通和",(box,))
        self.assertEqual([("通知",box)],words)

    def test_numeric_and_negative_edits_advance_on_the_first_changed_frame(self):
        image = panel()
        self.frame(image, "地図１")
        draw = ImageDraw.Draw(image)
        draw.rectangle((34,15,40,19), fill="white")
        self.assertEqual("地図２",self.frame(image, "地図２")[0][0][0])
        # A new glyph immediately before a previously valid box must count.
        draw.line((BOX[0]-3,13,BOX[0]-3,28), fill="white", width=2)
        extended = (BOX[0]-3, BOX[1], BOX[2], BOX[3])
        self.assertEqual("非公開",self.frame(image, "非公開", (extended,))[0][0][0])

    def test_color_independent_ink_alone_cannot_lock_a_number_or_negation(self):
        for old,new in (("残り2分","残り3分"), ("公開","非公開"), ("2.1時間","21時間")):
            with self.subTest(before=old, after=new):
                self.tracker = ScreenTracker()
                self.frame(panel(), old)
                self.assertEqual(new,self.frame(panel(fg=24,bg=230), new)[0][0][0])

    def test_distinct_han_number_groups_do_not_reuse_a_previous_label(self):
        for language in ("han", "zh", "zt", "ja"):
            with self.subTest(language=language):
                self.tracker = ScreenTracker()
                self.frame(panel(), "二 十", lang=language)
                image = panel()
                ImageDraw.Draw(image).rectangle((21, 17, 31, 22), fill="white")
                placed, _ = self.frame(image, "二十", lang=language)
                self.assertEqual([("二十", BOX)], placed)

    def test_an_appended_word_beyond_the_old_patch_updates_immediately(self):
        image = panel()
        self.frame(image, "今日は")
        # The original lettering and its surrounding margin stay untouched.
        # The next word is inside the expanded OCR box, outside the old patch.
        ImageDraw.Draw(image).rectangle((83, 15, 87, 27), fill="white")
        expanded = BOX[0], BOX[1], 89, BOX[3]
        placed, _ = self.frame(image, "今日は休み", (expanded,))
        self.assertEqual([("今日は休み", expanded)], placed)

    def test_one_missed_frame_retains_unmodified_appearance_and_then_expires(self):
        image = panel()
        self.frame(image, "設定", colors=12345)
        held,rows = self.frame(image, "", boxes=(), colors=65432)
        self.assertEqual([("設定",BOX)], held)
        self.assertEqual(12345,rows[0]["background_rgb"])
        self.assertEqual([], self.frame(image, "", boxes=())[0])
        self.frame(image, "設定")
        self.assertEqual([], self.frame(Image.new("RGB",image.size,"gray"), "", boxes=())[0])

    def test_ocr_spacing_and_independent_order_without_samples(self):
        image = panel()
        self.frame(image, "設定", (BOX,SECOND))
        current, _ = self.tracker.placements(((("ja","設 定"),SECOND), (("ja","設 定"),BOX)), {})
        self.assertEqual(((("ja","設定"),BOX), (("ja","設定"),SECOND)), current)
        changed,_ = self.tracker.placements(((("ja","設定?"),BOX),), {})
        self.assertEqual((("ja","設定?"),BOX),changed[0])

    def test_width_variants_keep_first_spelling_and_superscript_changes_do_not(self):
        image = panel()
        self.frame(image, "次へ！")
        placement,_ = self.tracker.placements(((("ja","次へ!"),BOX),),{})
        self.assertEqual((("ja","次へ！"),BOX),placement[0])
        self.tracker = ScreenTracker()
        self.frame(image, "面積m²")
        placement,_ = self.tracker.placements(((("ja","面積m2"),BOX),),{})
        self.assertEqual((("ja","面積m2"),BOX),placement[0])

    def test_occluded_source_cannot_reappear_as_ghost_under_new_observed_label(self):
        image = panel()
        self.frame(image, "設定")
        # Incomplete detector geometry is insufficient evidence for claiming
        # that both an old and a new label coexist in the same area.
        small = (BOX[0], BOX[1], BOX[0]+20, BOX[3])
        placements,_ = self.frame(image, "地図", (small,))
        self.assertEqual([("地図",small)],placements)

    def test_clipped_and_very_large_regions_omit_pixel_evidence(self):
        image = panel()
        frame = observed("設定", ((-1,0,33,40),(0,0,9999,9999)))
        result = sample_frame(frame,(image,0,0),("ja",()))
        self.assertEqual({},result.screen_samples)

    def test_already_translated_overlay_can_refresh_while_the_text_model_is_busy(self):
        from worker import Worker
        worker = Worker.__new__(Worker)
        # Any attempt to acquire the model lock on this cache-only path fails.
        worker.text_lock = None
        key = ("ja","設定")
        cache = OrderedDict([(key, {"text":"Settings", "language":"ja"})])
        _, result = worker._translate_segments((key,), "ja", cache=cache, placements=((key,BOX),))
        self.assertEqual("Settings",result["regions"][0]["text"])


class ScreenCaptionHistoryTests(unittest.TestCase):
    def test_brief_disappearance_does_not_create_another_transcript_row(self):
        history = ScreenCaptionHistory()
        source = (("ja", "ホーム"),)
        self.assertTrue(history.observe(source, "Home", 0))
        self.assertFalse(history.observe((), "", .5))
        self.assertFalse(history.observe(source, "Home", 1))

    def test_continuing_reappearance_is_quiet_until_a_real_absence(self):
        history = ScreenCaptionHistory()
        source = (("ko", "홈"),)
        self.assertTrue(history.observe(source, "Home", 0))
        for now in range(1, 100):
            self.assertFalse(history.observe(source, "Home", now))
        self.assertTrue(history.observe(source, "Home", 130))

    def test_genuine_home_signs_are_accepted_and_distinct_sources_are_not_banned(self):
        history = ScreenCaptionHistory()
        for source in (("ja", "ホーム"), ("zh", "家"), ("ko", "홈")):
            self.assertTrue(history.observe((source,), "Home", 0))

    def test_different_translation_or_meaning_is_a_new_transcript_row(self):
        history = ScreenCaptionHistory()
        self.assertTrue(history.observe((("ja", "次は家"),), "Next is home", 0))
        self.assertTrue(history.observe((("ja", "次は家"),), "Home is next", 1))
        self.assertTrue(history.observe((("ja", "次は駅"),), "Next is the station", 2))
        self.assertTrue(history.observe((("ja", "次は家？"),), "Next is home?", 3))

    def test_physical_order_and_width_spacing_variants_do_not_repeat_the_same_caption(self):
        history = ScreenCaptionHistory()
        self.assertTrue(history.observe((("ja", "設 定"), ("ja", "次へ！")), "Settings\nNext!", 0))
        self.assertFalse(history.observe((("ja", "次へ!"), ("ja", "設定")), "Settings  Next!", 1))
        self.assertTrue(history.observe((("ja", "次へ？"), ("ja", "設定")), "Settings Next?", 2))

    def test_new_watch_has_no_previous_target_or_language_history(self):
        source = (("ja", "ホーム"),)
        first, second = ScreenCaptionHistory(), ScreenCaptionHistory()
        self.assertTrue(first.observe(source, "Home", 0))
        self.assertTrue(second.observe(source, "Home", 1))

    def test_genuine_content_change_then_return_creates_a_new_occurrence(self):
        history = ScreenCaptionHistory()
        home, settings = (("ja", "ホーム"),), (("ja", "設定"),)
        self.assertTrue(history.observe(home, "Home", 0))
        self.assertTrue(history.observe(settings, "Settings", 1))
        self.assertTrue(history.observe(home, "Home", 2))
        self.assertFalse(history.observe(home, "Home", 3))

    def test_large_passage_is_not_retained_and_short_following_caption_still_works(self):
        history = ScreenCaptionHistory()
        home = (("ja", "ホーム"),)
        self.assertTrue(history.observe(home, "Home", 0))
        self.assertTrue(history.observe((("ja", "長文" * 5000),), "Long text", 0))
        self.assertTrue(history.observe(home, "Home", 1))
