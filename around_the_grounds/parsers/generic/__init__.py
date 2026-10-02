from .airtable import AirtableParser
from .ajax import AjaxParser
from .bevwerk import BevwerkParser
from .canva import CanvaParser
from .html_selector import HtmlSelectorParser
from .html_taplist import (
    CraftpeakWotParser,
    DigitalPourParser,
    HtmlTaplistParser,
    TapHunterParser,
)
from .json_ld import JsonLdParser
from .firestore_taplist import FirestoreTaplistParser
from .menu_tools import MenuToolsParser
from .pdf_taplist import PdfTaplistParser
from .sheet_taplist import SheetTaplistParser
from .squarespace_events import SquarespaceEventsParser
from .text_taplist import TextTaplistParser
from .untappd_embed import UntappdEmbedParser
from .untappd_venue import UntappdVenueParser
from .wordpress import WordPressParser

__all__ = [
    "WordPressParser",
    "HtmlSelectorParser",
    "AjaxParser",
    "JsonLdParser",
    "UntappdEmbedParser",
    "UntappdVenueParser",
    "SheetTaplistParser",
    "HtmlTaplistParser",
    "CraftpeakWotParser",
    "DigitalPourParser",
    "BevwerkParser",
    "CanvaParser",
    "TextTaplistParser",
    "PdfTaplistParser",
    "AirtableParser",
    "TapHunterParser",
    "FirestoreTaplistParser",
    "MenuToolsParser",
    "SquarespaceEventsParser",
]
