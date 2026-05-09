from dataclasses import asdict, dataclass, field


@dataclass
class OcrResultRecord:
    text: str = ""
    confidence: float | None = None
    confidenceSupported: bool = False
    engine: str = ""
    primaryEngine: str = ""
    fallbackUsed: bool = False


@dataclass
class BubbleRecord:
    coords: list[int]
    polygon: list[list[int]] = field(default_factory=list)
    direction: str = "vertical"
    textDirection: str = "vertical"
    autoTextDirection: str = "vertical"
    textlines: list[dict] = field(default_factory=list)
    originalText: str = ""
    translatedText: str = ""
    ocrResult: dict = field(default_factory=dict)
    textColor: str | None = None
    fillColor: str | None = None
    fontSize: int | None = None
    lineSpacing: float | None = None
    textAlign: str | None = None
    strokeEnabled: bool | None = None
    strokeColor: str | None = None
    strokeWidth: int | None = None
    position: dict = field(default_factory=dict)
    autoFgColor: list[int] | None = None
    autoBgColor: list[int] | None = None
    colorConfidence: float = 0.0


@dataclass
class PageRecord:
    id: str
    fileName: str
    sourcePath: str
    translatedPath: str | None = None
    status: str = "idle"
    cacheKey: str | None = None

    def to_dict(self):
        return asdict(self)
