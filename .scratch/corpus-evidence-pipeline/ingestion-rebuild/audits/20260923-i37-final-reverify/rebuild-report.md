# I3-7 重验重建（用 I3-6 冻结版本 teardown 重建沙箱并全量 build/check/publish）

- 生成：2026-09-23T12:37:26+08:00；冻结版本 manifest `.scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-final-freeze-manifest.json`（sha256 4152179ffeed，链头 i0c-r4z / 绑定修订 i0c-r5a）
- 清单 `.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i31-dev-lane/dev-scope-manifest.json`（sha256 8487c51b548e，8 份）
- 路径：teardown 重建沙箱再全量重跑（U 2026-09-20 受支持重建路径，i42 同款）
- teardown：exit 0
- apply：exit 0（tables None / indexes None）
- 守卫：`.scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i3-e2e.json`（3faac9e01fc3）；`CORPUS_DEV_LANE=1`；沙箱 `corpus-db 容器（127.0.0.1:543）i2_sandbox_corpus，teardown 重建`

## 逐来源

| 领域 | 格式 | 来源 | provenance | 单元/切块 | build | check | publish | 阻断缺口 |
|---|---|---|---|---|---|---|---|---|
| company | pdf | 2026-08-16_2026.08.16-华创证券 | approved_set | 727/36 | 58735cff57d8 | 0 | 0（gen 1） | image_region_unreadable@issue:image_region_unreadable:page:2 |
| company | pdf | 2026-09-06_2026.09.06-国信证券 | approved_set | 786/206 | a3b681fdd55d | 0 | 0（gen 1） | image_region_unreadable@issue:image_region_unreadable:page:7 |
| industry | pdf | 2026-08-13_2026.08.13-长江证券 | approved_set | 1255/291 | 1227c2a34d05 | 0 | 0（gen 1） | image_region_unreadable@issue:image_region_unreadable:page:1；image_region_unreadable@issue:image_region_unreadable:page:2；table_lines_without_extraction@issue:table_lines_without_extraction:page:12；table_lines_without_extraction@issue:table_lines_without_extraction:page:13；table_lines_without_extraction@issue:table_lines_without_extraction:page:17；table_lines_without_extraction@issue:table_lines_without_extraction:page:18；table_lines_without_extraction@issue:table_lines_without_extraction:page:21；table_lines_without_extraction@issue:table_lines_without_extraction:page:22；table_lines_without_extraction@issue:table_lines_without_extraction:page:24；table_lines_without_extraction@issue:table_lines_without_extraction:page:3 |
| industry | pdf | 2026-09-06_2026.09.06-华福证券 | approved_set | 229/55 | 99bf1ba24564 | 0 | 0（gen 1） | 无 |
| macro | pdf | 2026-09-06_2026.09.06-华创证券 | approved_set | 243/32 | e3820ab34c2e | 0 | 0（gen 1） | 无 |
| macro | pdf | 2026-09-06_2026.09.06-光大证券 | approved_set | 512/187 | 7734638eca66 | 0 | 0（gen 1） | table_lines_without_extraction@issue:table_lines_without_extraction:page:6 |
| company | md | 工业富联_投委会决策报告_20260829.md | dev_lane | 91/20 | 6b55ddbbcfdc | 0 | 0（gen 1） | 无 |
| industry | docx | 9月8日 光模块技术演进与供应链重构：从1.6T到3 | dev_lane | 44/7 | 6475cbacca15 | 0 | 0（gen 1） | 无 |

- 汇总：built **8/8**；published 8；blocked 0；active(new build) 8
- revs：parse ["28fd6541c91aad284905e19175272b3fb3133293bd5417675ae9b57f732fdfcf", "4949696523d10ca145fcaaef7bde4c0fcaa0f92de7afd95b2abc3f97d87a427a", "5947b799bcf746ddbe648bc1430af544ebac6a37d995d38917147575a46f848d", "6e9be61c68c9c3b3b3e99850883e6340cd69eea0f29cb667ab9e2a639b2b76c5", "747860affaab837c29c5f6386cf76b6d0225c03a1490680a277752f03a15524a", "7a505b2c771611a59a42f35a60f6e6e751302d83dc6b5b5cd3baae0ec70fd57d", "b6efff470a194e3fa99f0aa64de5617f3f12e7f5f735da0dca9cb546d1c67008", "b9e90e3845de2e3fc99d8fd30dd56a65f2de96c7c40ddf7f9de025968cfaac87"]；clean ["f17753283f310fe85f66f4b67593b7a24594c001520d3fb0767f7aa9b1dedf57"]；chunk ["ff430da84301a9210502a749da48f09f1da39f2ecc82a729336e393c44a04ee3"]；index ["index-4-zhcfg-2"]
- **全部新 build 成为 active：True**（与冻结 REV 常量一致：reader-pdf-6 / clean-3 / chunk-3 / index-4-zhcfg-2）
- 说明：teardown 重建后按冻结代码全部重解析；本报告为 I3-7 重验的重建步证据。
