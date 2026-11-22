"""Word-level OCR guard regressions using only authored, synthetic geometry."""
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from ocr_guard import (EnglishGuard, Word, combine_row_results, corroborate_lines, filter_words, has_target_script,
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


if __name__ == "__main__":
    unittest.main()
