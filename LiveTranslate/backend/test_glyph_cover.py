import base64
import io
import unittest

import numpy as np
from PIL import Image, ImageDraw

from glyph_cover import MAX_FRAME_PNG, attach_covers, collect_covers
from screen_geometry import LocatedText


def fixture(panel=(238, 240, 242), ink=(12, 17, 19), gradient=False):
    width, height = 96, 51
    y, x = np.mgrid[:height, :width]
    if gradient:
        clean = np.stack((30 + x, 45 + y, 160 - x), axis=2).astype("uint8")
    else:
        clean = np.full((height, width, 3), panel, dtype="uint8")
    matte = Image.new("L", (width, height))
    draw = ImageDraw.Draw(matte)
    for start in (13, 42):
        draw.rectangle((start, 11, start + 17, 32), outline=255, width=2)
        draw.line((start + 8, 8, start + 8, 35), fill=255, width=2)
        draw.line((start + 1, 21, start + 15, 21), fill=255, width=2)
    rgb = Image.composite(Image.new("RGB", (width, height), ink), Image.fromarray(clean), matte)
    ocr = rgb.convert("L").resize((2*width, 2*height))
    dx, dy = -400, -79
    ocr.info["glyph_source"] = (rgb, dx, dy)
    boxes = [(dx + start, dy + 8, dx + start + 18, dy + 36) for start in (13, 42)]
    located = LocatedText("日本", [("日本", [(0,1,boxes[0]),(1,2,boxes[1])])])
    return ocr, located, boxes, clean, np.asarray(matte)>0


def unpack(payload):
    with Image.open(io.BytesIO(payload)) as image:
        return np.array(image)


class GlyphCoverTests(unittest.TestCase):
    def check_repair(self, params):
        frame, located, boxes, clean, matte = fixture(**params)
        covers = collect_covers(frame, located)
        self.assertEqual(set(boxes), set(covers))
        for box, data in covers.items():
            l,t,r,b = box
            left, top = frame.info["glyph_source"][1:]
            section = np.s_[t-top:b-top, l-left:r-left]
            patch = unpack(data)
            np.testing.assert_array_equal(patch[..., 3] == 255, matte[section])
            np.testing.assert_array_equal(patch[matte[section], :3], clean[section][matte[section]])
            self.assertFalse(patch[~matte[section]].any())
        whole = [dict(left=boxes[0][0], top=boxes[0][1], width=boxes[1][2]-boxes[0][0],
                      height=boxes[0][3]-boxes[0][1], text="Japan")]
        attach_covers(whole, covers)
        joined = unpack(base64.b64decode(whole[0]["cover_png"], validate=True))
        np.testing.assert_array_equal(joined[..., 3]>0, matte[8:36,13:60])

    def test_light_dark_and_colored_smooth_panels(self):
        for kw in ({}, {"panel":(12,20,43), "ink":(244,242,231)},
                   {"gradient":True, "ink":(240,240,240)}):
            with self.subTest(options=kw):
                self.check_repair(kw)

    def test_english_and_mixed_unsplittable_box_and_adjacent_rows(self):
        frame, located, boxes, _, _ = fixture()
        located = LocatedText("x", [("English", [(0,7,boxes[0])]),
                                    ("USB日本", [(0,5,boxes[0])]),
                                    ("日", [(0,1,boxes[1])])])
        covers = collect_covers(frame, located)
        self.assertIsNone(covers[boxes[0]])
        self.assertTrue(covers[boxes[1]])
        rows = [dict(left=boxes[0][0],top=boxes[0][1],width=18,height=28,text="A"),
                dict(left=boxes[1][0],top=boxes[1][1],width=18,height=28,text="B")]
        attach_covers(rows,covers)
        self.assertNotIn("cover_png",rows[0])
        self.assertIn("cover_png",rows[1])
        combined = dict(left=boxes[0][0],top=boxes[0][1],width=boxes[1][2]-boxes[0][0],
                        height=28,text="Combined")
        attach_covers([combined],covers)
        self.assertNotIn("cover_png",combined)

    def test_blank_and_noisy_scenes_supply_a_local_color_without_a_guessed_repair(self):
        frame, located, boxes, _, _ = fixture()
        rng = np.random.default_rng(869)
        for image in (Image.new("RGB", (96,51), "navy"),
                      Image.fromarray(rng.integers(0,256,size=(51,96,3),dtype="uint8"))):
            frame.info["glyph_source"]=(image,-400,-79)
            covers = collect_covers(frame,located)
            self.assertFalse(any(covers.values()))
            rows = [dict(left=l,top=t,width=r-l,height=b-t,text="Day") for l,t,r,b in boxes]
            attach_covers(rows,covers)
            for row in rows:
                self.assertNotIn("cover_png",row)
                self.assertIn("background_rgb",row)
                if image.getpixel((0,0)) == (0,0,128):
                    self.assertEqual(128,row["background_rgb"])

    def test_bands_and_repeating_textures_recover_the_clean_scene_at_glyphs(self):
        frame, located, boxes, _, matte = fixture()
        yy, xx = np.mgrid[:51,:96]
        patterns = [yy//3%2, xx//3%2, (xx//3+yy//3)%2, ((xx+yy)%7<3).astype(int)]
        for pattern in patterns:
            bg = np.where(pattern[...,None], [122,69,134], [57,103,93]).astype("uint8")
            source = np.where(matte[...,None], [241,241,244], bg).astype("uint8")
            frame.info["glyph_source"] = Image.fromarray(source), -400, -79
            covers = collect_covers(frame, located)
            for rect in boxes:
                with self.subTest(box=rect, pattern=pattern[:2,:8].tolist()):
                    self.assertTrue(covers[rect])
                    rgba = unpack(covers[rect])
                    l,t,r,b = rect
                    section = np.s_[t+79:b+79,l+400:r+400]
                    replacement = np.where(rgba[...,3,None]>0,rgba[...,:3],source[section])
                    np.testing.assert_array_equal(replacement,bg[section])

    def test_changes_to_only_the_sampled_background_refresh_the_caption(self):
        other = []
        for color in ((91,30,64),(95,32,75)):
            frame,located,boxes,_,_ = fixture(panel=color)
            frame.info["glyph_source"] = Image.new("RGB",(96,51),color), -400,-79
            other.append(collect_covers(frame,located))
        self.assertNotEqual(*other)

    def test_distinct_white_ink_on_irregular_texture_leaves_other_areas_live(self):
        frame,located,boxes,_,matte = fixture()
        rng = np.random.default_rng(568)
        texture = rng.integers(-30,31,size=(51,96,3)) + [75,103,127]
        source = np.where(matte[...,None], [248,246,249], texture).astype("uint8")
        frame.info["glyph_source"] = Image.fromarray(source), -400, -79
        covers = collect_covers(frame,located)
        for box in boxes:
            self.assertTrue(covers[box])
            rgba = unpack(covers[box])
            l,t,r,b = box
            section = np.s_[t+79:b+79,l+400:r+400]
            ink = matte[section]
            repaired = rgba[...,3] > 0
            self.assertTrue(repaired[ink].all())
            self.assertLess(repaired.mean(),.80)
            self.assertLess(np.mean(np.abs(rgba[ink,:3].astype(int)-texture[section][ink])),24.)

    def test_mixed_phrase_keeps_gutters_transparent_and_covers_each_word(self):
        frame,located,boxes,_,_ = fixture()
        image = frame.info["glyph_source"][0].copy()
        noise = np.random.default_rng(1888).integers(0,256,size=(49,39,3),dtype="uint8")
        image.paste(Image.fromarray(noise),(39,1))
        frame.info["glyph_source"] = image,-400,-79
        covers = collect_covers(frame,located)
        self.assertTrue(covers[boxes[0]])
        self.assertIsNone(covers[boxes[1]])
        l,t,r,b = boxes[0]
        x,_,right,_ = boxes[1]
        row = dict(left=l,top=t,width=right-l,height=b-t,text="Japan")
        attach_covers([row], covers)
        combined = unpack(base64.b64decode(row["cover_png"]))
        np.testing.assert_array_equal(combined[:,:r-l],unpack(covers[boxes[0]]))
        self.assertFalse(combined[:,r-l:x-l].any())
        self.assertTrue((combined[:,x-l:,3]==255).all())
        expected = [(covers.colors[boxes[1]] >> shift)&255 for shift in (16,8,0)]
        self.assertTrue((combined[:,x-l:,:3]==expected).all())

    def test_missing_metadata_oversized_and_outside_captured_area(self):
        self.assertEqual({},collect_covers(None,LocatedText("x")))
        frame, _, _, _, _ = fixture()
        invalid = [(-400,-79,4000,-50),(-390,-70,-389,3000),(-500,-70,-485,-52),
                   (-390,-70,-391,-68)]
        for box in invalid:
            self.assertEqual({},collect_covers(frame,LocatedText("日",[("日",[(0,1,box)])])))

    def test_budget_and_partial_overlap_cannot_hide_only_half_a_phrase(self):
        frame, loc, boxes, *_ = fixture()
        covers = collect_covers(frame, loc)
        l,t,r,b = boxes[0]
        clipped = dict(left=l+1, top=t, width=r-l-1, height=b-t, text="day")
        attach_covers([clipped], covers)
        self.assertNotIn("cover_png", clipped)
        # Once the bounded OCR index is full there may be unexamined words
        # inside a larger translation. The guaranteed cover is the GUI fallback.
        spans = list(loc.regions[0][1])
        spans.extend((0,1,(5000+n,0,5001+n,9)) for n in range(128))
        too_many=LocatedText("日本",[("日本",spans)])
        self.assertFalse(collect_covers(frame,too_many))

    def test_wire_budget_bounds_and_distinct_patches(self):
        frame, loc, boxes, *_ = fixture()
        cover = collect_covers(frame, loc)
        l,t,r,b = boxes[0]
        row = {"left":l, "top":t, "width":r-l, "height":b-t,"text":"day"}
        many = [dict(row) for _ in range(1000)]
        too_large = dict(row, width=2049)
        attach_covers([too_large],cover)
        self.assertNotIn("cover_png",too_large)
        attach_covers(many,cover)
        included = [base64.b64decode(r["cover_png"]) for r in many if "cover_png" in r]
        self.assertEqual(32,len(included))
        self.assertLessEqual(sum(map(len,included)),MAX_FRAME_PNG)
        self.assertTrue(all(data == cover[boxes[0]] for data in included))


if __name__ == "__main__":
    unittest.main()
