"""Word-level OCR guard regressions using only authored, synthetic geometry."""
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from ocr_guard import (EnglishGuard, Word, combine_row_results, corroborate_lines, filter_desktop_fragments, filter_words, has_target_script,
                       join_vertical_glyphs, overlapping_text_lines, parse_tsv, plain_horizontal_rows,
                       prefer_korean_row, prefer_single_line, uncertain_korean_row, weak_foreign_line)


def tsv(text, x, confidence=95, y=5, line=1, width=24):
    return f"5\t1\t1\t1\t{line}\t1\t{x}\t{y}\t{width}\t20\t{confidence}\t{text}"


class OcrGuardTests(unittest.TestCase):
    def test_english_lines_do_not_survive_mixed_block(self):
        raw = "Play\n東京駅へ\nHome"
        data = "\n".join([tsv("Play",0,line=1), tsv("東京駅へ",60,line=2), tsv("Home",0,line=3)])
        self.assertEqual("東京駅へ", filter_words(raw,data,[]))
        self.assertEqual("", filter_words("Exit",tsv("Exit",5),[]))

    def test_replace_wrong_source_token_on_english_word(self):
        wrong = Word("File",(5,5,30,25))
        self.assertEqual("",filter_words("曰月",tsv("曰月",5),[wrong]))

    def test_known_inline_name_and_neighboring_foreign_remain(self):
        raw = "USB 接続しています"
        data = tsv("USB",5)+"\n"+tsv("接続しています",33,width=100)
        self.assertEqual(raw,filter_words(raw,data,[Word("USB",(5,5,29,25))]))

    def test_confidence_fallback_and_context(self):
        self.assertEqual("",filter_words("曰",tsv("曰",10,44),None))
        self.assertEqual("電車",filter_words("電車",tsv("電車",10,94),None))
        data="\n".join([tsv("日",5,96),tsv("本",33,93),tsv("語",60,0)])
        self.assertEqual("日本語",filter_words("日本語",data,None))

    def test_desktop_confidence_rejects_faint_icon_words_without_changing_region_reads(self):
        raw = "加 个"
        data = tsv("加", 0, 57.64, width=12) + "\n" + tsv("个", 25, 64.94, width=12)
        self.assertEqual(raw, filter_words(raw, data, []))
        self.assertEqual("", filter_words(raw, data, [], desktop_auto=True))

    def test_desktop_confidence_keeps_weak_glyph_supported_by_two_strong_words(self):
        data = "\n".join([tsv("日", 5, 96), tsv("本", 33, 93), tsv("語", 60, 0)])
        self.assertEqual("日本語", filter_words("日本語", data, [], desktop_auto=True))

    def test_unavailable_english_reader_requires_stronger_full_scene_single_fragment(self):
        raw = "0660 히"
        data = tsv("0660", 0, 96) + "\n" + tsv("히", 100, 72.49)
        self.assertEqual("", filter_words(raw, data, None, desktop_auto=True))
        self.assertEqual(raw, filter_words(raw, data, None))
        data = "\n".join([tsv("日", 5, 96), tsv("本", 33, 93), tsv("語", 60, 0)])
        self.assertEqual("日本語", filter_words("日本語", data, None, desktop_auto=True))

    def test_bad_tsv_does_not_turn_into_an_unguarded_caption(self):
        self.assertEqual([],parse_tsv("level\ttext\n5\tbad"))
        self.assertEqual("",filter_words("日本語","",[]))
        self.assertEqual("",filter_words("日本語",tsv("日本語",5,float("nan")),[]))

    def test_script_ranges_cover_extended_priorities(self):
        for text in ("電車","ひらがな","カタカナ","ｶﾀｶﾅ","괜찮아","𠀀"):
            self.assertTrue(has_target_script(text), text)
        for text in ("EXIT","école","12345","…"):
            self.assertFalse(has_target_script(text), text)

    def test_overlapping_uneven_lines_eligible_for_single_line_retry(self):
        parts=tsv("日本語を",2,80,width=90)+"\n"+tsv("英語に翻訳",65,87,y=7,line=2,width=80)
        self.assertTrue(overlapping_text_lines(parts))
        disjoint=tsv("日本語",2,94)+"\n"+tsv("英語",2,90,y=40,line=2)
        self.assertFalse(overlapping_text_lines(disjoint))
        self.assertTrue(prefer_single_line("日本語を英語に翻訳",parts,"日本語を英語に翻訳",tsv("日本語を英語に翻訳",5,90)))
        self.assertFalse(prefer_single_line("日本語を英語に翻訳",parts,"の",tsv("の",5,90)))

    def test_japanese_vertical_rejoins_glyphs_but_respects_lines_and_latin(self):
        self.assertEqual("日本語\nUSB 端子",join_vertical_glyphs("日 本 語\nUSB 端 子"))

    def test_korean_reread_requires_supported_context_and_preserves_names(self):
        old = tsv('지금날씨는',0,94) + '\n' + tsv('東京',40,93) + '\n' + tsv('日中地',80,20)
        self.assertTrue(uncertain_korean_row(old))
        self.assertFalse(uncertain_korean_row(tsv('오늘은',0,94) + '\n' + tsv('東京',40,92)))
        self.assertFalse(uncertain_korean_row(tsv('오늘は',0,95) + '\n' + tsv('東京',40,20)))
        kept = tsv('지금날씨는',0,95) + '\n' + tsv('東京',40,80) + '\n' + tsv('입니다',80,90)
        self.assertTrue(prefer_korean_row(old,kept))
        self.assertFalse(prefer_korean_row(old,tsv('지금날씨는입니다',0,95)))
        self.assertFalse(prefer_korean_row(old,kept.replace('\t90\t','\t35\t')))

    def test_separate_physical_rows_keep_distinct_geometry(self):
        try:
            from PIL import Image, ImageDraw
            import numpy
        except ImportError:
            self.skipTest('Pillow and NumPy required for generated row geometry')
        image = Image.new('L',(200,110),255)
        draw = ImageDraw.Draw(image)
        for y in (15,65):
            for x in range(15,100,10):
                draw.rectangle((x,y,x+4,y+11),fill=0)
        rows = plain_horizontal_rows(image)
        self.assertEqual(2,len(rows))
        _, raw, data = combine_row_results(rows,[('京都',tsv('京都',5)),('한국',tsv('한국',5))])
        words = parse_tsv(data)
        self.assertEqual('京都\n한국',raw)
        self.assertNotEqual(words[0].line,words[1].line)
        self.assertEqual(rows[0].height+8,words[1].box[1]-words[0].box[1])

    def test_numeric_repetition_routes_to_verifier_only_when_interleaved(self):
        self.assertTrue(weak_foreign_line('04060 6니니@60@ 니0니니니?'))
        self.assertFalse(weak_foreign_line('하하하하하하 12345678'))
        self.assertFalse(weak_foreign_line('라라라라라라12345678'))
        self.assertFalse(weak_foreign_line('오늘의 결제 번호 123456789012'))
        self.assertEqual('',corroborate_lines('04060 6니니@60@ 니0니니니?', 'uileD ern@or 니0니니니?'))
        self.assertEqual('결제 번호 123456789012',corroborate_lines('결제 번호 123456789012',
                                                               'View Settings\n결제 번호 123456789012'))
        self.assertEqual('',corroborate_lines('결제 번호 123456789012','결제 번호 765432100005'))

    def test_independent_ocr_fallback_discards_english_garbage(self):
        self.assertEqual("",corroborate_lines("G1  7  77   了 567 33","7 了 TEST"))
        self.assertEqual("",corroborate_lines("く >","く"))
        self.assertEqual("實時翻譯",corroborate_lines("實時翻譯","支持實時翻譯"))

    def test_english_word_spans_include_acronym_only_on_supported_lines(self):
        img=MagicMock(size=(200,100),width=200,height=100)
        img.convert().tobytes.return_value=bytes(20000)
        output=b"0\t0\t0\t24\t10\tFile\n0\t32\t0\t57\t10\tXP\n0\t60\t0\t98\t10\tOptions\n1\t10\t40\t18\t50\t7\n"
        with patch("ocr_guard.subprocess.run",return_value=SimpleNamespace(returncode=0,stdout=output)) as run:
            self.assertEqual(["File","XP","Options"],[r.text for r in EnglishGuard().detect(img)])
        self.assertEqual(20008,len(run.call_args.kwargs["input"]))

    def test_unavailable_guard_skips_repeated_process_startup(self):
        img=MagicMock(size=(100,100),width=100,height=100)
        img.convert().tobytes.return_value=bytes(10000)
        g=EnglishGuard()
        with patch("ocr_guard.subprocess.run",side_effect=subprocess.TimeoutExpired("OCR",6)) as run:
            self.assertIsNone(g.detect(img))
            self.assertIsNone(g.detect(img))
            self.assertEqual(1,run.call_count)

    def test_numeric_stutter_is_filtered_but_real_quantities_survive(self):
        observation=[Word("Time",(510,5,580,25))]
        self.assertEqual("",filter_words("017 19187 태11 0800",tsv("태11",150),observation))
        self.assertEqual("20분",filter_words("20분",tsv("20분",50),observation))
        self.assertEqual("口",filter_words("口",tsv("口",50),observation))


class DesktopFragmentTests(unittest.TestCase):
    def fragment(self, text, box, start=0, end=None):
        return text, [(start, len(text) if end is None else end, box)]

    def test_full_desktop_icon_guesses_have_no_text_support(self):
        positions = [self.fragment("一", (1792, 11, 1802, 13)),
                     self.fragment("回", (1838, 7, 1848, 17)),
                     self.fragment("十", (1715, 55, 1727, 67)),
                     self.fragment("回", (349, 654, 355, 656)),
                     self.fragment("서", (12, 280, 28, 297)),
                     self.fragment("@ 加", (12, 330, 28, 347)),
                     self.fragment("品", (12, 380, 28, 397))]
        self.assertEqual("", filter_desktop_fragments("\n".join(line for line, _ in positions), positions))
        self.assertEqual([], positions)

    def test_unrelated_rows_or_distant_glyphs_cannot_corroborate_each_other(self):
        for second in ((0, 40, 20, 60), (500, 0, 520, 20), (25, 0, 65, 40)):
            with self.subTest(second=second):
                positions = [self.fragment("東", (0, 0, 20, 20)), self.fragment("京", second)]
                self.assertEqual("", filter_desktop_fragments("東\n京", positions))
                self.assertEqual([], positions)

    def test_real_adjacent_short_cjk_runs_remain(self):
        for source in ("東京", "はい", "한국", "口に入る", "次の電車は何時ですか"):
            with self.subTest(source=source):
                positions = [self.fragment(source, (0, 0, 20 * len(source), 20))]
                anchors = [Word(source, (0, 0, 20 * len(source), 20), 94)] if len(source) <= 2 else []
                self.assertEqual(source, filter_desktop_fragments(source, positions, anchors))
                self.assertEqual(1, len(positions))

    def test_adjacent_glyphs_across_ocr_rows_share_horizontal_evidence(self):
        positions = [self.fragment("東", (-140, -42, -120, -22)),
                     self.fragment("京", (-116, -41, -96, -21))]
        expected = list(positions)
        anchors = [Word(source, spans[0][2], 94) for source, spans in positions]
        self.assertEqual("東\n京", filter_desktop_fragments("東\n京", positions, anchors))
        self.assertEqual(expected, positions)

    def test_pure_icon_confusable_runs_remain_ambiguous(self):
        for source in ("口回十", "一口", "ロノニ", "回回回回"):
            with self.subTest(source=source):
                positions = [self.fragment(source, (0, 0, 20 * len(source), 20))]
                self.assertEqual("", filter_desktop_fragments(source, positions))
                self.assertEqual([], positions)

    def test_ascii_text_does_not_support_a_single_foreign_guess(self):
        positions = [self.fragment("@ 加 Products", (0, 0, 190, 20))]
        self.assertEqual("", filter_desktop_fragments("@ 加 Products", positions))
        self.assertEqual([], positions)

    def test_meaningful_neighbor_can_support_a_real_short_label(self):
        positions = [self.fragment("口", (0, 0, 20, 20)), self.fragment("東京", (24, 0, 64, 20))]
        self.assertEqual("口\n東京", filter_desktop_fragments("口\n東京", positions))
        self.assertEqual(2, len(positions))

    def test_duplicate_boxes_do_not_add_independent_source_evidence(self):
        positions = [self.fragment("서", (0, 0, 20, 20)), self.fragment("서", (0, 0, 20, 20))]
        self.assertEqual("", filter_desktop_fragments("서\n서", positions))
        self.assertEqual([], positions)

    def test_rejected_duplicate_text_has_its_own_position_removed(self):
        positions = [self.fragment("東", (0, 0, 20, 20)), self.fragment("京", (24, 0, 44, 20)),
                     self.fragment("東", (500, 500, 520, 520))]
        anchors = [Word("東", (0, 0, 20, 20), 94), Word("京", (24, 0, 44, 20), 94)]
        self.assertEqual("東\n京", filter_desktop_fragments("東\n京\n東", positions, anchors))
        self.assertEqual(2, len(positions))
        self.assertTrue(all(box[0] < 100 for _, spans in positions for _, _, box in spans))

    def test_unsupported_fragment_is_removed_from_an_otherwise_valid_line(self):
        positions = [("東京   口", [(0, 2, (0, 0, 40, 20)), (5, 6, (500, 0, 520, 20))])]
        self.assertEqual("東京", filter_desktop_fragments("東京   口", positions, [Word("東京", (0, 0, 40, 20), 94)]))
        self.assertEqual([("東京", [(0, 2, (0, 0, 40, 20))])], positions)

    def test_missing_invalid_or_unpositioned_evidence_fails_closed(self):
        for spans in ([], [(0, 2, None)], [(0, 2, (0, 0, 0, 20))],
                      [(0, 2, (0, 0, float("nan"), 20))]):
            with self.subTest(spans=spans):
                positions = [("東京", spans)]
                self.assertEqual("", filter_desktop_fragments("東京", positions))
                self.assertEqual([], positions)
        positions = [self.fragment("東京口", (0, 0, 40, 20), end=2)]
        self.assertEqual("東京", filter_desktop_fragments("東京口", positions, [Word("東京", (0, 0, 40, 20), 94)]))
        self.assertEqual([("東京", [(0, 2, (0, 0, 40, 20))])], positions)


    def test_exact_local_read_can_preserve_complex_single_character_labels(self):
        box = (-80, -20, -60, 0)
        for source in ("門", "人", "左", "서", "加", "ｱ"):
            with self.subTest(source=source):
                positions = [self.fragment(source, box)]
                anchors = [Word(" ア " if source == "ｱ" else source, box, 94)]
                self.assertEqual(source, filter_desktop_fragments(source, positions, anchors))
                self.assertEqual(1, len(positions))

    def test_single_label_proof_must_be_exact_confident_and_at_the_same_box(self):
        box = (0, 0, 20, 20)
        for anchor in (Word("門", box, 87), Word("門", box, float("nan")),
                       Word("問", box, 99), Word("門", (500, 0, 520, 20), 99), Word("Door門", box, 99)):
            with self.subTest(anchor=anchor):
                positions = [self.fragment("門", box)]
                self.assertEqual("", filter_desktop_fragments("門", positions, [anchor]))
                self.assertEqual([], positions)

    def test_confidence_cannot_disambiguate_single_icon_shapes(self):
        for source, box in (("一", (1792, 11, 1802, 13)), ("回", (1838, 7, 1848, 17)),
                            ("十", (1715, 55, 1727, 67)), ("口", (0, 0, 20, 20)),
                            ("図", (0, 0, 20, 20)), ("圖", (0, 0, 20, 20)), ("图", (0, 0, 20, 20)),
                            ("ㅁ", (0, 0, 20, 20)), ("ㅅ", (0, 0, 20, 20)),
                            ("ㄴ", (0, 0, 20, 20)), ("ㄱ", (0, 0, 20, 20))):
            with self.subTest(source=source):
                positions = [self.fragment(source, box)]
                self.assertEqual("", filter_desktop_fragments(source, positions, [Word(source, box, 99)]))
                self.assertEqual([], positions)

    def test_graph_words_and_normal_hangul_syllables_are_not_blanket_banned(self):
        for source in ("中文圖片", "圖案", "地图", "図書", "네", "응"):
            with self.subTest(source=source):
                box = (0, 0, 20 * len(source), 20)
                positions = [self.fragment(source, box)]
                anchors = [Word(source, box, 94)] if len(source) <= 2 else []
                self.assertEqual(source, filter_desktop_fragments(source, positions, anchors))
        for source in ("圖", "ㅁ"):
            self.assertEqual(source, filter_words(source, tsv(source, 0), []))

    def test_verified_compact_word_of_confusable_characters_is_preserved(self):
        box = (0, 0, 40, 20)
        positions = [self.fragment("一口", box)]
        self.assertEqual("一口", filter_desktop_fragments("一口", positions, [Word("一口", box, 94)]))
        self.assertEqual(1, len(positions))

    def test_whole_word_proof_preserves_split_thin_stroke_and_full_glyph(self):
        spans = [(0, 1, (0, 9, 20, 11)), (1, 2, (24, 0, 44, 20))]
        positions = [("一口", spans)]
        anchors = [Word("一 口", (0, 0, 44, 20), 94)]
        self.assertEqual("一口", filter_desktop_fragments("一口", positions, anchors))
        self.assertEqual([("一口", spans)], positions)
        positions = [("一口", spans)]
        singles = [Word("一", spans[0][2], 99), Word("口", spans[1][2], 99)]
        self.assertEqual("", filter_desktop_fragments("一口", positions, singles))

    def test_loose_icon_runs_remain_rejected_even_with_exact_high_confidence_read(self):
        positions = [("一口回", [(0, 1, (0, 0, 20, 20)), (1, 2, (40, 0, 60, 20)),
                                (2, 3, (80, 0, 100, 20))])]
        proof = [Word("一口回", (0, 0, 100, 20), 99)]
        self.assertEqual("", filter_desktop_fragments("一口回", positions, proof))
        self.assertEqual([], positions)

    def test_unusually_narrow_real_words_need_local_verification(self):
        box = (0, 0, 16, 20)
        positions = [self.fragment("東京", box)]
        self.assertEqual("", filter_desktop_fragments("東京", positions))
        positions = [self.fragment("東京", box)]
        self.assertEqual("東京", filter_desktop_fragments("東京", positions, [Word("東京", box, 94)]))

    def test_one_icon_cannot_supply_multiple_guessed_characters_or_support_neighbors(self):
        box = (0, 0, 8, 20)
        positions = [self.fragment("加个 \\ ※", box)]
        self.assertEqual("", filter_desktop_fragments("加个 \\ ※", positions))
        positions = [("口 패소 VM ※", [(0, 1, (0, 0, 16, 20)), (2, 4, (20, 0, 28, 20))])]
        self.assertEqual("", filter_desktop_fragments("口 패소 VM ※", positions))
        positions = [self.fragment("패소", box)]
        self.assertEqual("", filter_desktop_fragments("패소", positions, [Word("패소", box, 99)]))

    def test_long_source_line_preserves_narrow_and_uneven_word_boxes(self):
        source = "次の電車は何時ですか"
        spans = [(0, 2, (-180, -30, -140, -10)),
                 (2, 4, (-136, -40, -114, 0)),
                 (4, 5, (-110, -25, -102, -15)),
                 (5, 7, (-98, -30, -58, -10)),
                 (7, 10, (-54, -44, -29, 2))]
        positions = [(source, spans)]
        self.assertEqual(source, filter_desktop_fragments(source, positions))
        self.assertEqual([(source, spans)], positions)

    def test_long_context_cannot_be_borrowed_from_separate_screen_lines(self):
        source = "東\n京\n門"
        positions = [self.fragment("東", (0, 0, 20, 20)), self.fragment("京", (300, 0, 320, 20)),
                     self.fragment("門", (0, 300, 20, 320))]
        self.assertEqual("", filter_desktop_fragments(source, positions))
        self.assertEqual([], positions)

    def test_two_character_components_need_local_proof_not_just_nearby_guesses(self):
        for source in ("東京", "はい", "한국", "ニン", "时个"):
            with self.subTest(source=source):
                box = (0, 0, 40, 20)
                positions = [self.fragment(source, box)]
                self.assertEqual("", filter_desktop_fragments(source, positions))
                positions = [self.fragment(source, box)]
                self.assertEqual(source, filter_desktop_fragments(source, positions, [Word(source, box, 94)]))
        positions = [self.fragment("加", (0, 0, 12, 12)), self.fragment("个", (25, 0, 37, 12))]
        self.assertEqual("", filter_desktop_fragments("加\n个", positions))

    def test_exact_short_word_proof_accepts_overlapping_tesseract_glyph_boxes(self):
        cases = (("一口", [(0, 1, (68, 61, 129, 89)), (1, 2, (108, 59, 129, 101))],
                  (68, 59, 129, 101)),
                 ("二十", [(0, 1, (69, 60, 132, 90)), (1, 2, (105, 56, 133, 101))],
                  (69, 56, 133, 101)))
        for source, spans, box in cases:
            with self.subTest(source=source):
                positions = [(source, spans)]
                self.assertEqual(source, filter_desktop_fragments(source, positions, [Word(source, box, 93)]))
                self.assertEqual([(source, spans)], positions)

    def test_long_word_with_overlapping_word_envelope_keeps_all_source_glyphs(self):
        source = "工場入口"
        spans = [(0, 2, (37, 60, 160, 90)), (2, 3, (113, 60, 143, 90)),
                 (3, 4, (141, 60, 160, 90))]
        positions = [(source, spans)]
        self.assertEqual(source, filter_desktop_fragments(source, positions))
        self.assertEqual([(source, spans)], positions)

    def test_japanese_row_with_tall_overlapping_envelopes_keeps_ordinary_text(self):
        source = "次の電車は何時ですか。"
        spans = [(0, 1, (262, 254, 299, 291)), (1, 2, (313, 257, 335, 288)),
                 (2, 4, (340, 254, 666, 291)), (4, 5, (441, 224, 466, 303)),
                 (5, 7, (465, 224, 556, 303)), (7, 8, (552, 224, 585, 303)),
                 (8, 10, (584, 224, 642, 303))]
        positions = [(source, spans)]
        self.assertEqual(source, filter_desktop_fragments(source, positions))
        self.assertEqual([(source, spans)], positions)

    def test_repeated_identical_physical_evidence_does_not_invent_a_second_character(self):
        box = (0, 0, 20, 20)
        positions = [("서서", [(0, 1, box), (1, 2, box)])]
        self.assertEqual("", filter_desktop_fragments("서서", positions, [Word("서서", box, 99)]))
        positions = [("서서", [(0, 1, box), (1, 2, box)])]
        self.assertEqual("서", filter_desktop_fragments("서서", positions, [Word("서", box, 99)]))


if __name__ == "__main__":
    unittest.main()
