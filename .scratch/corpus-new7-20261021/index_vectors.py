"""Incremental published-text vectors, bounded requests and no uncertain retries."""
from dataclasses import replace
from run_batch import *
from plugins.corpus.retrieval.embedding import VectorConfig, DoubaoEmbedder
from plugins.corpus.retrieval.index_pg import VectorIndex

parser=argparse.ArgumentParser()
parser.add_argument('--retry-uncertain',action='store_true')
args=parser.parse_args()
run_number=len(list(HERE.glob('vector-run-*.json')))+1
config=replace(VectorConfig.from_env(),target_db=TARGET,timeout=60)
assert config.input_variant=='published-search-text-v1'
index=VectorIndex(TARGET_DSN,config)
index.initialize()
before=index.status()
if not (HERE/'vector-build-start.json').exists(): save('vector-build-start.json',before)
maximum=before['uncached_inputs']
embedder=DoubaoEmbedder(config)
count=0
def embed(text,role):
    global count
    result=embedder.embed(text,role)
    count+=1
    print(json.dumps({'completed':count,'maximum_new_inputs':maximum,'role':role}),flush=True)
    return result
result=index.build(embed,max_requests=maximum,retry_uncertain=args.retry_uncertain)
save(f'vector-run-{run_number}.json',{'before':before,'retry_uncertain':args.retry_uncertain,'result':result})
save('vector-build.json',result)
save('vector-after.json',index.status())
print(json.dumps(result,ensure_ascii=False),flush=True)
