import json, sys
from pathlib import Path
import pyvips
from the_frame_v2.domain.document import ArtworkDocument
from the_frame_v2.imaging.render import render_document
out = Path(sys.argv[1])
white = pyvips.Image.black(1200, 800, bands=3) + 255
white.cast("uchar").copy(interpretation="srgb").pngsave(str(out / "white.png"))
xy = pyvips.Image.xyz(1200, 800)
checker = ((((xy[0] / 40).floor() + (xy[1] / 40).floor()) % 2) * 180 + 40)
photo = checker.bandjoin([xy[0] * 255 / 1200, xy[1] * 255 / 800]).cast("uchar").copy(interpretation="srgb")
photo.pngsave(str(out / "checker.png"))
def slot(i, pid, rect, **kw):
    x, y, w, h = rect
    return {"id": f"s{i}", "photo_id": pid, "rect": {"x": x, "y": y, "w": w, "h": h}, "source": {"crop": {"x": 0, "y": 0, "w": 1200, "h": 800}}, "quality_lock": "free", **kw}
scenes = {
  "shadows": {"placement": "manual", "mat": {"color": "#F2EFE8"}, "slots": [
      slot(1, "white", (400, 500, 1200, 800), shadow={"type": "drop", "offset_x": 0, "offset_y": 24, "blur": 48, "color": "#000000", "opacity": 0.5}),
      slot(2, "white", (2200, 500, 1200, 800), shadow={"type": "inner", "offset_x": 0, "offset_y": 8, "blur": 30, "color": "#000000", "opacity": 0.6}),
      slot(3, "white", (400, 1500, 1200, 500), shadow={"type": "drop", "offset_x": 10, "offset_y": 6, "blur": 12, "color": "#3B3024", "opacity": 0.8}, source={"crop": {"x": 0, "y": 0, "w": 1200, "h": 500}}),
      slot(4, "white", (2200, 1500, 1200, 500), shadow={"type": "inner", "offset_x": 0, "offset_y": 3, "blur": 120, "color": "#000000", "opacity": 0.5}, source={"crop": {"x": 0, "y": 0, "w": 1200, "h": 500}}),
  ]},
  "texture": {"placement": "manual", "mat": {"color": "#B0A090", "texture": {"id": "linen-01", "strength": 0.6}}, "slots": []},
  "rotated": {"placement": "manual", "mat": {"color": "#D8D2C6"}, "slots": [
      slot(1, "checker", (1320, 680, 1200, 800), rotation=7, bands=[{"width": 20, "color": "#FFFFFF"}]),
  ]},
  "captions": {"placement": "manual", "mat": {"color": "#FFFFFF"}, "slots": [], "captions": [
      {"id": "c1", "text": "Kyoto — April 2026", "font": "cormorant-garamond", "weight": 500, "size": 120, "color": "#000000", "letter_spacing": 0.05, "x": 1920, "y": 400, "anchor": "middle"},
      {"id": "c2", "text": "Arashiyama bamboo", "font": "inter", "weight": 300, "size": 80, "color": "#000000", "letter_spacing": 0.2, "x": 3600, "y": 800, "anchor": "end"},
      {"id": "c3", "text": "AVATAR Toyota", "font": "josefin-sans", "weight": 700, "size": 200, "color": "#000000", "letter_spacing": 0, "x": 200, "y": 1300, "anchor": "start"},
      {"id": "c4", "text": "Fontaine-lès-Dijon", "font": "eb-garamond", "weight": 400, "size": 64, "color": "#000000", "letter_spacing": 0, "x": 1000, "y": 1800, "anchor": "start"},
      {"id": "c5", "text": "Tilted caption", "font": "inter", "weight": 600, "size": 90, "color": "#000000", "letter_spacing": 0.02, "x": 2800, "y": 1800, "anchor": "middle", "rotation": -8},
  ]},
}
resolve = {"white": out / "white.png", "checker": out / "checker.png"}.get
meta = {}
for name, raw in scenes.items():
    doc = ArtworkDocument.model_validate({"schema": 1, **raw})
    r = render_document(doc, resolve)
    r.image.pngsave(str(out / f"{name}.png"), compression=1)
    meta[name] = {"document": doc.canonical(), "text_boxes": [b.__dict__ if hasattr(b, "__dict__") else {"x": b.x, "y": b.y, "w": b.w, "h": b.h} for b in r.text_boxes]}
(out / "scenes.json").write_text(json.dumps(meta))
fonts = json.loads(Path("src/the_frame_v2/assets/fonts/manifest.json").read_text())
(out / "fonts.json").write_text(json.dumps(fonts))
print("ok")
