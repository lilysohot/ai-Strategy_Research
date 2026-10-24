"""Read-only release inventory; print only allowlisted non-secret settings."""
import json
import os
import subprocess
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

ROOT = Path.cwd()
load_dotenv(ROOT / '.env')
keys = ['CORPUS_TARGET_DB', 'CORPUS_READ_CHAIN', 'CORPUS_NATIVE_RETRIEVAL',
        'CORPUS_NATIVE_TARGET_DB', 'CORPUS_VECTOR_TARGET_DB', 'CORPUS_NATIVE_INDEX',
        'CORPUS_VECTOR_INPUT_VARIANT', 'CORPUS_NATIVE_SNIPPET_BLOCKS',
        'CORPUS_VECTOR_TIMEOUT_SECONDS', 'CORPUS_RETRIEVAL_MODE', 'CORPUS_RETRIEVAL_RANKING']
values = dotenv_values(ROOT / '.env')
print('dotenv', json.dumps({k: values.get(k) for k in keys}))
for p in Path('/proc').iterdir():
    if not p.name.isdigit():
        continue
    try:
        argv = (p / 'cmdline').read_bytes().decode().split('\0')
        if not any('uvicorn' in a or 'server.monitor' in a for a in argv[:4]):
            continue
        env = dict(v.split('=', 1) for v in (p / 'environ').read_bytes().decode().split('\0') if '=' in v)
        print('process', json.dumps({'pid': p.name, 'cwd': str((p / 'cwd').resolve()),
              'argv': argv[:9], 'settings': {k: env.get(k) for k in keys}}))
    except (OSError, UnicodeError):
        pass
from plugins.corpus.retrieval.native_live import configured_seed
from plugins.corpus.retrieval.embedding import VectorConfig
os.environ['CORPUS_NATIVE_INDEX'] = str(ROOT / 'data/corpus-native-context/20261023/manifest.json')
os.environ['CORPUS_VECTOR_INPUT_VARIANT'] = 'contextual-note-v1'
seed = configured_seed('postgres')
cfg = VectorConfig.from_env()
assert cfg.profile == seed.manifest['profile'], 'context_vector_profile_mismatch'
print('seed', json.dumps({'schema': seed.manifest['schema'], 'profile': seed.manifest['profile'],
      'sources': len(seed.manifest['source_allowlist']), 'chunks': len(seed.chunks)}))
print('git', subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip())
