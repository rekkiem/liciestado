from app.bid_analyzer import BidAnalyzer
from unittest.mock import MagicMock

def test_buscar_por_organismo_null():
    ba = BidAnalyzer()
    db = MagicMock()
    assert ba._buscar_por_organismo(db, None, 10) == []
    assert ba._buscar_por_organismo(db, "", 10) == []
