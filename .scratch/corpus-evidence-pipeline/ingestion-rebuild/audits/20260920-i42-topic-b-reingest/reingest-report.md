# I42 议题 B 重摄入（reader-pdf-6 / chunk-3 / index-4-zhcfg-2，teardown 重建）

- 生成：2026-09-21T00:27:47+08:00；清单 `.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i31-dev-lane/dev-scope-manifest.json`（sha256 8487c51b548e，8 份）
- 版本：reader reader-pdf-5 → **reader-pdf-6**；chunk chunk-2 → **chunk-3**；index index-3-zhcfg-2 → **index-4-zhcfg-2**
- 路径：teardown 重建沙箱再全量重跑（沿用 i35 受支持路径）
- teardown：exit 0（{'step': 'i2s1_teardown', 'dropped': 'corpus schema (CASCADE)', 'database_kept': 'i2_sandbox_corpus', 'residue': 0}）
- apply：exit 0（tables None / indexes None）
- 守卫：`.scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i3-e2e.json`（3faac9e01fc3）；`CORPUS_DEV_LANE=1`；沙箱 `corpus-db 容器（127.0.0.1:543）i2_sandbox_corpus，teardown 重建`

## 逐来源

| 领域 | 格式 | 来源 | provenance | 单元/切块 | build | check | publish | 阻断缺口 |
|---|---|---|---|---|---|---|---|---|
| company | pdf | 2026-08-16_2026.08.16-华创证券 | approved_set | 727/36 | 58735cff57d8 | 0 | 0（gen 1） | 无 |
| company | pdf | 2026-09-06_2026.09.06-国信证券 | approved_set | 786/206 | a3b681fdd55d | 0 | 0（gen 1） | 无 |
| industry | pdf | 2026-08-13_2026.08.13-长江证券 | approved_set | 1255/291 | 1227c2a34d05 | 0 | 0（gen 1） | 无 |
| industry | pdf | 2026-09-06_2026.09.06-华福证券 | approved_set | 229/55 | 99bf1ba24564 | 0 | 0（gen 1） | 无 |
| macro | pdf | 2026-09-06_2026.09.06-华创证券 | approved_set | 243/32 | e3820ab34c2e | 0 | 0（gen 1） | 无 |
| macro | pdf | 2026-09-06_2026.09.06-光大证券 | approved_set | 512/187 | 7734638eca66 | 0 | 0（gen 1） | 无 |
| company | md | 工业富联_投委会决策报告_20260829.md | dev_lane | 91/20 | 6b55ddbbcfdc | 0 | 0（gen 1） | 无 |
| industry | docx | 9月8日 光模块技术演进与供应链重构：从1.6T到3 | dev_lane | 44/7 | 6475cbacca15 | 0 | 0（gen 1） | 无 |

- 汇总：built **8/8**；published **8/8**；blocked 0（4 份曾因 check 缺口阻断，经 human gap-review 签认后放行）；active(new build) **8**
- index_rev：["index-4-zhcfg-2"]；chunk_rev：["ff430da84301a9210502a749da48f09f1da39f2ecc82a729336e393c44a04ee3"]；**全部新 build 成为 active：True（generation=1）**
- 说明：teardown 重建后代码全部重解析；新 build 因 parse_rev/chunk_rev/index_rev 变更产生新 build_id。4 份被堵来源（茅台 58735cff、光力 a3b681、长江 1227c2a3、光大 7734638e）分别登记 human gap-review（茅台 301799cf、光力 63c684c4、长江 bb68423b、光大 bf5b1af7）后全部 publish。
