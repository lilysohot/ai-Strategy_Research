"""Read-only OCR audit; writes inspection artifacts only."""
from run_batch import *
import csv
import fitz
from statistics import mean
from PIL import Image, ImageChops
records=load('ocr-provenance.json')
results=[]
for row in records:
    item={'parent_source_id':row['parent_source_id'],'derived_source_id':row['derived_source_id'], 'pages':[]}
    for kind in ('parent','derived'):
        path=Path(row[kind+'_path'])
        item[kind+'_hash_ok']=hashlib.sha256(path.read_bytes()).hexdigest()==row[kind+'_source_id']
        assert item[kind+'_hash_ok']
    with fitz.open(row['parent_path']) as original, fitz.open(row['derived_path']) as derivative:
        assert len(original)==len(derivative)==len(row['pages'])
        for p,info in enumerate(row['pages']):
            with open(info['tsv_path']) as f:
                words=[w for w in csv.DictReader(f,delimiter='\t') if w['text'].strip() and float(w['conf'])>=0]
            text=derivative[p].get_text()
            a=original[p].get_pixmap(dpi=90,alpha=False)
            b=derivative[p].get_pixmap(dpi=90,alpha=False)
            ia=Image.frombytes('RGB',(a.width,a.height),a.samples)
            ib=Image.frombytes('RGB',(b.width,b.height),b.samples)
            assert ia.size==ib.size
            dif=ImageChops.difference(ia,ib)
            hist=dif.histogram()
            mae=sum((i%256)*n for i,n in enumerate(hist))/(ia.width*ia.height*3)
            item['pages'].append({'page':p+1,'dimensions_match':original[p].rect==derivative[p].rect,
                'ocr_words':len(words),'mean_tesseract_confidence':round(mean(float(w['conf']) for w in words),2),
                'words_below_70':sum(float(w['conf'])<70 for w in words),'extracted_chars':len(text.strip()),
                'render_mean_absolute_difference_0_255':round(mae,4)})
            if p in (0,1,2):
                original[p].get_pixmap(dpi=130).save(str(HERE/f'audit-{row["parent_source_id"][:8]}-p{p+1}.png'))
                (HERE/f'audit-{row["parent_source_id"][:8]}-p{p+1}.txt').write_text(text)
    with psycopg.connect(TARGET_DSN) as conn:
        conn.execute('SET TRANSACTION READ ONLY')
        for kind in ('parent','derived'):
            sid=row[kind+'_source_id']
            pub=conn.execute('SELECT active_build_id,generation FROM corpus.corpus_publications WHERE source_id=%s',(sid,)).fetchone()
            archive=conn.execute('SELECT archive_path FROM corpus.corpus_sources WHERE source_id=%s',(sid,)).fetchone()[0]
            item[kind+'_publication']=pub
            item[kind+'_archive_hash_ok']=hashlib.sha256((ARCHIVE/archive).read_bytes()).hexdigest()==sid
            if pub and pub[0]:
                build=conn.execute('SELECT quality_report FROM corpus.corpus_builds WHERE build_id=%s',(pub[0],)).fetchone()[0]
                item['quality_report']=build
    results.append(item)
save('ocr-audit-readonly.json',{'target_db':TARGET,'scope':'No OCR rerun, no publication mutation, no external model call','sources':results})
print(json.dumps(results,ensure_ascii=False,indent=2,default=str))
