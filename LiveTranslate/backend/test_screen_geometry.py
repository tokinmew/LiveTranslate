"""Physical source rectangles, exclusion of English, and position-only updates."""
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

from ocr_guard import Word, combine_row_results, filter_words, verify_hangul_suffixes
from screen_geometry import LocatedText, capture_map, line_regions, map_crop, physical_box, trim_oversized_word
from test_worker import FakeAudio, FakeScreen, FakeText
from worker import Worker


def tsv(text, x, y, w=38, h=18):
    return f"5\t1\t1\t1\t1\t1\t{x}\t{y}\t{w}\t{h}\t98\t{text}"


class MappingTests(unittest.TestCase):
    def test_full_height_suffix_does_not_pin_a_subtitle_to_top_of_the_crop(self):
        from PIL import Image, ImageDraw
        frame=Image.new("L",(220,140),"white")
        ImageDraw.Draw(frame).rectangle((160,44,193,67),fill=12)
        self.assertEqual(trim_oversized_word(frame,(150,0,200,140),24),(160,44,194,68))

    def test_hangul_suffix_needs_entire_row_confirmation_and_english_token_stays_vetoed(self):
        from PIL import Image
        frame=Image.new("L",(360,50),255)
        terms=["기","차","는","다섯","시에","출발합니다"]
        raw="기차는 다섯 시에 출발합니다"
        data="\n".join(tsv(term,i*40,10,32) for i,term in enumerate(terms))
        candidate=Word("XYL-",(40,10,112,28))
        ordinary=Word("Options",(40,10,112,28))
        self.assertEqual(verify_hangul_suffixes(frame,raw,data,[candidate,ordinary],lambda *a:(raw,"")),[ordinary])
        self.assertEqual(verify_hangul_suffixes(frame,raw,data,[candidate],lambda *a:("다른 말","")),[candidate])
        self.assertEqual(verify_hangul_suffixes(frame,"기 차 는 다섯 시에 출발합니다",data,[candidate],lambda *a:(raw,"")),[candidate])

    def test_source_in_physical_pixels_after_padding_and_resizing(self):
        from PIL import Image
        frame = Image.new("L",(1000,600))
        capture_map(frame,dict(left=-1711,top=-85,width=500,height=300))
        row = map_crop(Image.new("L",(224,54)),frame,(200,80,600,140),12)
        self.assertEqual(physical_box(row,(12,12,212,42)),(-1611,-45,-1411,-15))

    def test_two_stitched_rows_map_to_different_on_screen_origins(self):
        from PIL import Image
        rows = [Image.new("L",(185,52)) for _ in range(2)]
        for row, pos in zip(rows,[(-1800,-280),(650,488)]):
            capture_map(row,dict(left=pos[0],top=pos[1],width=185,height=52))
        words = [("地図",tsv("地図",14,10)), ("地図",tsv("地図",44,17))]
        image,raw,data = combine_row_results(rows, words)
        positions = []
        self.assertEqual(filter_words(raw,data,[],image,positions),"地図\n地図")
        self.assertEqual([spans[0][2] for _,spans in positions],
                         [(-1786,-270,-1748,-252),(694,505,732,523)])

    def test_spatially_separate_labels_and_rejected_english_guess(self):
        from PIL import Image
        frame=Image.new("L",(900,90),"white")
        capture_map(frame,{})
        data = "\n".join([tsv("地図",10,10),tsv("天気",610,10),tsv("設定",814,10)])
        positions = []
        filter_words("地図 天気 設定", data, [Word("Options",(814,10,852,28))], frame, positions)
        line,spans=positions[0]
        found=list(line_regions(line,spans))
        self.assertEqual([value.strip() for value,_ in found],["地図","天気"])
        self.assertEqual([words[0][2] for _,words in found],[(10,10,48,28),(610,10,648,28)])

    def test_watch_moves_repeat_without_translating_again_or_repeating_history(self):
        events=[]
        progress=threading.Event()
        def send(event):
            events.append(event)
            if event["type"]=="screen_clear":
                progress.set()
        def frame(*xs):
            return LocatedText("こんにちは", [("こんにちは",[(0,5,(x,20,x+80,42))]) for x in xs])
        frames=iter([frame(-120,150),frame(-110,100),frame(-110,100),"Settings"])
        with TemporaryDirectory() as root, patch("worker.TextEngine",FakeText), patch("worker.AudioEngine",FakeAudio), patch("worker.ScreenEngine",FakeScreen):
            w=Worker(Path(root),send)
            try:
                with patch.object(w.screen,"recognize",side_effect=lambda *a: next(frames, ""),create=True), patch.object(w.text,"translate",wraps=w.text.translate) as translate:
                    w.start_screen({"source":"ja","interval":0.5})
                    self.assertTrue(progress.wait(5))
                    w.dispatch({"command":"stop_screen"})
                    self.assertEqual(translate.call_count,1)
            finally:
                w.close()
        screens=[event for event in events if event["type"]=="screen"]
        self.assertEqual([[r["left"] for r in e["regions"]] for e in screens],[[-120,150],[-110,100]])
        self.assertEqual([e.get("layout_only",False) for e in screens],[False,True])


if __name__ == "__main__":
    unittest.main()
