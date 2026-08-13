import base64
from dataclasses import dataclass
from typing import Optional

@dataclass
class ImgLabel:
    name: str
    image_path: Optional[str] = None
    image_base64: Optional[str] = None
    range_x: int = 0
    range_y: int = 0
    range_width: int = 1920
    range_height: int = 1080
    target_x: int = 0
    target_y: int = 0
    target_width: int = 100
    target_height: int = 100
    threshold: float = 80.0
    # EasyCon search-method number.  5 is CCOEFF_NORMED; 14 is masked
    # SQDIFF_NORMED with the original alpha channel as its mask.
    search_method: int = 5

    def load_image(self, path: str):
        self.image_path = path
        with open(path, "rb") as f:
            self.image_base64 = base64.b64encode(f.read()).decode()

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "ImgBase64": self.image_base64 or "",
            "RangeX": self.range_x,
            "RangeY": self.range_y,
            "RangeWidth": self.range_width,
            "RangeHeight": self.range_height,
            "TargetX": self.target_x,
            "TargetY": self.target_y,
            "TargetWidth": self.target_width,
            "TargetHeight": self.target_height,
            "searchMethod": self.search_method,
        }

    @staticmethod
    def from_dict(data: dict) -> "ImgLabel":
        label = ImgLabel(name=data.get("name", ""))
        label.image_base64 = data.get("ImgBase64", "")
        label.range_x = data.get("RangeX", 0)
        label.range_y = data.get("RangeY", 0)
        label.range_width = data.get("RangeWidth", 1920)
        label.range_height = data.get("RangeHeight", 1080)
        label.target_x = data.get("TargetX", 0)
        label.target_y = data.get("TargetY", 0)
        label.target_width = data.get("TargetWidth", 100)
        label.target_height = data.get("TargetHeight", 100)
        label.search_method = int(data.get("searchMethod", 5))
        return label
