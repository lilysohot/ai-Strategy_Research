"""Reuse the frozen 57-question tool harness against production, unchanged scoring."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()
from plugins.corpus.service import dsn, CorpusService

ROOT=Path.cwd();HERE=Path(__file__).parent
production_dsn=dsn()
spec=importlib.util.spec_from_file_location('frozen_tools',ROOT/'.scratch/corpus-native-tools-20261022/verify_tools.py')
harness=importlib.util.module_from_spec(spec);spec.loader.exec_module(harness)
release=ROOT/'data/corpus-native-release/20261022'
os.environ.update(CORPUS_DSN=production_dsn,CORPUS_TARGET_DB='postgres',
    CORPUS_VECTOR_TARGET_DB='postgres',CORPUS_NATIVE_TARGET_DB='postgres',
    CORPUS_NATIVE_RETRIEVAL='release',CORPUS_READ_CHAIN='new',
    CORPUS_RETRIEVAL_MODE='lexical',CORPUS_NATIVE_INDEX=str(release/'manifest.json'))
harness.OUT=release;harness.HERE=HERE
harness.service=CorpusService(production_dsn)
harness.prior.batch.TARGET='postgres';harness.prior.batch.TARGET_DSN=production_dsn
harness.prior.index.manifest['publications']=json.loads((release/'manifest.json').read_text())['publications']
harness.enabled=lambda value:os.environ.__setitem__('CORPUS_NATIVE_RETRIEVAL','release' if value=='pilot' else value)
asyncio.run(harness.main())
