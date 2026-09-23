from unittest.mock import patch
from plugins.corpus.preparation import cross_boundary as cb
from plugins.corpus.preparation.read_pg import ChunkEvidence, UnitEvidence, IntegrityError
from plugins.corpus.preparation.contract import sha256_of_bytes
from plugins.corpus.service import CorpusService
from plugins.corpus.preparation.search_pg import SearchHit

ev = ChunkEvidence("s", "b", "c", "paragraph", None, (), (UnitEvidence("kept", "Verified rating", 1, None, ()),), "Verified rating", (), (("kept",0,15),), True)
raw = "TAMPERED HEADER"
rows = [
("b","kept",2,"Verified rating",{"page":1,"bbox":[0,20,100,40]},sha256_of_bytes(b"Verified rating"),"kept",[]),
("b","noise",1,raw,{"page":1,"bbox":[0,10,100,30]},"0"*64,"noise",["header_repeated_geometric"])]
# Use real UnitStatus values to exercise the actual public aggregator.
from plugins.corpus.preparation.contract import UnitStatus
rows = [r[:6]+(UnitStatus.KEPT.value if r[1]=="kept" else UnitStatus.NOISE.value,)+r[7:] for r in rows]
class Cursor:
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def execute(self,*args): pass
    def fetchall(self): return rows
class Conn:
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def cursor(self): return Cursor()
with patch("psycopg.connect",return_value=Conn()), patch("plugins.corpus.preparation.read_pg._check_target"):
    result=cb.aggregate_band_chunks("fake",(ev,))
    assert raw in result[0].text
    print("BUG: public aggregate_band_chunks accepts corrupted NOISE content_hash; text =",repr(result[0].text))
svc=CorpusService("fake")
hit=SearchHit("s","b","c1","paragraph","Match",(),(),1.0,"answer")
actual=svc._selected_chunk_hits((hit,),{"s":("c0","c1","c2")},1)
print("limit=1 actual chunk/snippet =",[(x.chunk_id,x.snippet) for x in actual],"; original exact hit = c1")

