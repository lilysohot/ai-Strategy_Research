# 小范围主 agent 对照：答案与取证记录

## n01 / off

紫荆量子光电股份有限公司2026年上半年营业收入和净利润是多少？

检索已完成，结论如下：

**未能回答：本地资料库中没有"紫荆量子光电股份有限公司"的任何已发布资料。**

检索过程与依据：
1. 以"紫荆量子光电""紫荆量子""紫荆量子光电股份有限公司"等多个检索词在研报语料库中检索，均无词法命中（lexical_candidates 为 0 或仅向量近似），语料库中不存在该公司的研报、中报或相关报道文档。
2. 为排除近似干扰，对最接近的两处命中取回原文核验：
   - doc_id `cv2:568f9e752f0fa65a0e7f52d89b25af3ff8e8078e68510aeb77baac09c289ceea`（chunk:568f9e752f0fa65a:body:0003）：讲的是一家主营半导体划片机的公司（2026年上半年营业收入4.53亿元、归母净利润0.74亿元），**并非**"紫荆量子光电"；
   - doc_id `cv2:7ceca88433b092aef112bb25c95d221665080c5f9c979ad37eb4cbeeee40e509`（chunk:7ceca88433b092ae:body:0012）：涉及的是中讯半导体（截至2026年上半年尚未产生营业收入），**也并非**该公司。

因此，无法给出"紫荆量子光电股份有限公司2026年上半年营业收入和净利润"的数字；资料库中也无该公司任何年份的数据可作为替代来源。按照要求，不作其他公司、其他年份或预测数的替代推断。

**建议**：若该公司确实发布过2026年半年度报告，其半年度报告全文/摘要或相关券商点评研报不在当前已发布的本地资料库收录范围内，需补充该资料后再查询。

耗时 66.92 秒；search 5 次；fetch 2 次；返回正文 1634 字符；重复相同片段去重后 1634 字符。

```json
{
  "searches": [
    {
      "query": "紫荆量子光电",
      "count": 10,
      "delivery_preview": null,
      "coverage": {
        "requested_scope_ref": "corpus_schema",
        "effective_scope_ref": "corpus_publications.active_build_id",
        "publication_snapshot_ref": "corpus_publications@48e8e60844f69177d5eb672a1d1b1010",
        "processing": "scoped",
        "query_status": "matched",
        "availability": "unknown",
        "reason_codes": [
          "partial_published",
          "gap_regions_present"
        ],
        "counts": {
          "sources": 22,
          "published": 18,
          "withdrawn": 0,
          "pending": 0,
          "failed_jobs": 0,
          "builds": 28,
          "published_with_gaps": 16
        },
        "retrieval": {
          "requested": "hybrid",
          "used": "hybrid",
          "reason": null,
          "profile": "fbd9941b77ff17a534932b7bbec32358ae5088df9854d62a93b2e38801c3e107",
          "expected_chunks": 703,
          "ready_chunks": 703,
          "lexical_candidates": 11,
          "vector_candidates": 200,
          "query_cache_hit": false,
          "query_usage": {
            "prompt_tokens": 33,
            "total_tokens": 33
          },
          "elapsed_ms": 408
        }
      },
      "previews": 0,
      "locators": [
        "chunk:7ceca88433b092ae:body:0014",
        "chunk:568f9e752f0fa65a:table:0005",
        "chunk:022ae1713fb760ff:body:0011",
        "chunk:16a9a510ef9e405f:body:0006",
        "chunk:6b55ddbbcfdc484d:list:0001",
        "chunk:7ceca88433b092ae:body:0014",
        "chunk:568f9e752f0fa65a:table:0005",
        "chunk:022ae1713fb760ff:body:0011",
        "chunk:16a9a510ef9e405f:body:0006",
        "chunk:6b55ddbbcfdc484d:body:0003"
      ]
    },
    {
      "query": "紫荆量子光电股份有限公司 2026年上半年 营业收入 净利润",
      "count": 10,
      "delivery_preview": null,
      "coverage": {
        "requested_scope_ref": "corpus_schema",
        "effective_scope_ref": "corpus_publications.active_build_id",
        "publication_snapshot_ref": "corpus_publications@48e8e60844f69177d5eb672a1d1b1010",
        "processing": "scoped",
        "query_status": "matched",
        "availability": "unknown",
        "reason_codes": [
          "partial_published",
          "gap_regions_present"
        ],
        "counts": {
          "sources": 22,
          "published": 18,
          "withdrawn": 0,
          "pending": 0,
          "failed_jobs": 0,
          "builds": 28,
          "published_with_gaps": 16
        },
        "retrieval": {
          "requested": "hybrid",
          "used": "hybrid",
          "reason": null,
          "profile": "fbd9941b77ff17a534932b7bbec32358ae5088df9854d62a93b2e38801c3e107",
          "expected_chunks": 703,
          "ready_chunks": 703,
          "lexical_candidates": 200,
          "vector_candidates": 200,
          "query_cache_hit": false,
          "query_usage": {
            "prompt_tokens": 46,
            "total_tokens": 46
          },
          "elapsed_ms": 728
        }
      },
      "previews": 0,
      "locators": [
        "chunk:568f9e752f0fa65a:body:0003",
        "chunk:16a9a510ef9e405f:body:0007",
        "chunk:9fa4cd7cf1ab602a:table:0000",
        "chunk:7ceca88433b092ae:body:0014",
        "chunk:022ae1713fb760ff:body:0003",
        "chunk:568f9e752f0fa65a:body:0016",
        "chunk:16a9a510ef9e405f:body:0016",
        "chunk:9fa4cd7cf1ab602a:table:0009",
        "chunk:022ae1713fb760ff:body:0021"
      ]
    },
    {
      "query": "紫荆量子",
      "count": 10,
      "delivery_preview": null,
      "coverage": {
        "requested_scope_ref": "corpus_schema",
        "effective_scope_ref": "corpus_publications.active_build_id",
        "publication_snapshot_ref": "corpus_publications@48e8e60844f69177d5eb672a1d1b1010",
        "processing": "scoped",
        "query_status": "matched",
        "availability": "unknown",
        "reason_codes": [
          "partial_published",
          "gap_regions_present"
        ],
        "counts": {
          "sources": 22,
          "published": 18,
          "withdrawn": 0,
          "pending": 0,
          "failed_jobs": 0,
          "builds": 28,
          "published_with_gaps": 16
        },
        "retrieval": {
          "requested": "hybrid",
          "used": "hybrid",
          "reason": null,
          "profile": "fbd9941b77ff17a534932b7bbec32358ae5088df9854d62a93b2e38801c3e107",
          "expected_chunks": 703,
          "ready_chunks": 703,
          "lexical_candidates": 0,
          "vector_candidates": 200,
          "query_cache_hit": false,
          "query_usage": {
            "prompt_tokens": 32,
            "total_tokens": 32
          },
          "elapsed_ms": 432
        }
      },
      "previews": 0,
      "locators": [
        "chunk:2055995f24f1db3a:body:0010",
        "chunk:9ebd323f89e55cc1:table:0001",
        "chunk:6b55ddbbcfdc484d:list:0001",
        "chunk:82dac0d446ef83cd:body:0070",
        "chunk:e1b21386e9b62dde:body:0029",
        "chunk:2055995f24f1db3a:body:0014",
        "chunk:9ebd323f89e55cc1:table:0006",
        "chunk:6b55ddbbcfdc484d:body:0003",
        "chunk:82dac0d446ef83cd:table:0032",
        "chunk:e1b21386e9b62dde:body:0017"
      ]
    },
    {
      "query": "2026年上半年公司实现营业收入4.53亿",
      "count": 5,
      "delivery_preview": null,
      "coverage": {
        "requested_scope_ref": "corpus_schema",
        "effective_scope_ref": "corpus_publications.active_build_id",
        "publication_snapshot_ref": "corpus_publications@48e8e60844f69177d5eb672a1d1b1010",
        "processing": "scoped",
        "query_status": "matched",
        "availability": "unknown",
        "reason_codes": [
          "partial_published",
          "gap_regions_present"
        ],
        "counts": {
          "sources": 22,
          "published": 18,
          "withdrawn": 0,
          "pending": 0,
          "failed_jobs": 0,
          "builds": 28,
          "published_with_gaps": 16
        },
        "retrieval": {
          "requested": "hybrid",
          "used": "hybrid",
          "reason": null,
          "profile": "fbd9941b77ff17a534932b7bbec32358ae5088df9854d62a93b2e38801c3e107",
          "expected_chunks": 703,
          "ready_chunks": 703,
          "lexical_candidates": 200,
          "vector_candidates": 200,
          "query_cache_hit": false,
          "query_usage": {
            "prompt_tokens": 44,
            "total_tokens": 44
          },
          "elapsed_ms": 765
        }
      },
      "previews": 0,
      "locators": [
        "chunk:568f9e752f0fa65a:body:0003",
        "chunk:16a9a510ef9e405f:body:0007",
        "chunk:9fa4cd7cf1ab602a:body:0003",
        "chunk:7ceca88433b092ae:body:0012",
        "chunk:147e841aab35836a:body:0007"
      ]
    },
    {
      "query": "紫荆量子光电股份有限公司",
      "count": 5,
      "delivery_preview": null,
      "coverage": {
        "requested_scope_ref": "corpus_schema",
        "effective_scope_ref": "corpus_publications.active_build_id",
        "publication_snapshot_ref": "corpus_publications@48e8e60844f69177d5eb672a1d1b1010",
        "processing": "scoped",
        "query_status": "matched",
        "availability": "unknown",
        "reason_codes": [
          "partial_published",
          "gap_regions_present"
        ],
        "counts": {
          "sources": 22,
          "published": 18,
          "withdrawn": 0,
          "pending": 0,
          "failed_jobs": 0,
          "builds": 28,
          "published_with_gaps": 16
        },
        "retrieval": {
          "requested": "hybrid",
          "used": "hybrid",
          "reason": null,
          "profile": "fbd9941b77ff17a534932b7bbec32358ae5088df9854d62a93b2e38801c3e107",
          "expected_chunks": 703,
          "ready_chunks": 703,
          "lexical_candidates": 62,
          "vector_candidates": 200,
          "query_cache_hit": false,
          "query_usage": {
            "prompt_tokens": 35,
            "total_tokens": 35
          },
          "elapsed_ms": 524
        }
      },
      "previews": 0,
      "locators": [
        "chunk:7ceca88433b092ae:body:0014",
        "chunk:022ae1713fb760ff:body:0004",
        "chunk:16a9a510ef9e405f:body:0014",
        "chunk:82dac0d446ef83cd:body:0019",
        "chunk:568f9e752f0fa65a:body:0038"
      ]
    }
  ],
  "fetches": [
    {
      "args": {
        "doc_id": "cv2:568f9e752f0fa65a0e7f52d89b25af3ff8e8078e68510aeb77baac09c289ceea",
        "locator": "chunk:568f9e752f0fa65a:body:0003",
        "max_chars": 3000
      },
      "text_chars": 1122,
      "fetch_complete": null,
      "ok": true,
      "locators_returned": [
        "chunk:568f9e752f0fa65a:body:0003"
      ],
      "followed_by_assistant": true
    },
    {
      "args": {
        "doc_id": "cv2:7ceca88433b092aef112bb25c95d221665080c5f9c979ad37eb4cbeeee40e509",
        "locator": "chunk:7ceca88433b092ae:body:0012",
        "max_chars": 3000
      },
      "text_chars": 512,
      "fetch_complete": null,
      "ok": true,
      "locators_returned": [
        "chunk:7ceca88433b092ae:body:0012"
      ],
      "followed_by_assistant": true
    }
  ]
}
```

## n01 / pilot

紫荆量子光电股份有限公司2026年上半年营业收入和净利润是多少？

**结论：本地已发布资料库中没有“紫荆量子光电股份有限公司”的任何资料，无法回答其2026年上半年营业收入和净利润——信息不足，明确指出如下，不做任何替代。**

检索与核验过程（均为本地资料库内操作，未调用外部数据）：
1. 以公司全称“紫荆量子光电股份有限公司”及“紫荆量子”“紫荆”“量子光电”等多组关键词检索，词法命中为 0 或仅命中无关碎片词（“光电”“股份”“有限公司”），命中文档均为其他公司/其他主题的研报（光通信、PCB、储能、化工、美国非农点评等），片段中均不含“紫荆量子光电”。
2. 按流程用 corpus_fetch 抽取近邻命中的上下文原文核验（如 doc_id: cv2:568f9e752f0fa65a0e7f52d89b25af3ff8e8078e68510aeb77baac09c289ceea，locator: chunk:568f9e752f0fa65a:body:0025 / heading:0008 / body:0026），内容为另一家公司的估值与盈利预测表，与问题公司无关。
3. 资料库覆盖元信息显示 22 个来源中 18 个已发布、16 个存在缺口区域（gap_regions_present），但所有可检索内容中均未出现该公司名称或其 2026 年半年报数据。

说明：
- 库内确有其他公司 2026 年上半年经营数据（如长鑫科技、中微公司、天孚通信、光力科技等），但均非问题所指公司，按要求不予替代。
- 来源标题/doc_id/locator：不适用——资料库中不存在关于该公司的文档，无可引用来源。

**最终答案：根据当前已发布的本地资料库，无法提供紫荆量子光电股份有限公司 2026 年上半年营业收入和净利润；该信息在资料库中缺失。**

耗时 173.295 秒；search 7 次；fetch 1 次；返回正文 216 字符；重复相同片段去重后 216 字符。

```json
{
  "searches": [
    {
      "query": "紫荆量子光电",
      "count": 10,
      "delivery_preview": "pilot",
      "coverage": {
        "requested_scope_ref": "corpus_schema",
        "effective_scope_ref": "corpus_publications.active_build_id",
        "publication_snapshot_ref": "corpus_publications@48e8e60844f69177d5eb672a1d1b1010",
        "processing": "scoped",
        "query_status": "matched",
        "availability": "unknown",
        "reason_codes": [
          "partial_published",
          "gap_regions_present"
        ],
        "counts": {
          "sources": 22,
          "published": 18,
          "withdrawn": 0,
          "pending": 0,
          "failed_jobs": 0,
          "builds": 28,
          "published_with_gaps": 16
        },
        "retrieval": {
          "requested": "hybrid",
          "used": "hybrid",
          "reason": null,
          "profile": "fbd9941b77ff17a534932b7bbec32358ae5088df9854d62a93b2e38801c3e107",
          "expected_chunks": 703,
          "ready_chunks": 703,
          "lexical_candidates": 11,
          "vector_candidates": 200,
          "query_cache_hit": false,
          "query_usage": {
            "prompt_tokens": 33,
            "total_tokens": 33
          },
          "elapsed_ms": 546
        }
      },
      "previews": 6,
      "locators": [
        "chunk:7ceca88433b092ae:body:0014",
        "chunk:568f9e752f0fa65a:table:0005",
        "chunk:022ae1713fb760ff:body:0011",
        "chunk:16a9a510ef9e405f:body:0006",
        "chunk:6b55ddbbcfdc484d:list:0001",
        "chunk:7ceca88433b092ae:body:0014",
        "chunk:568f9e752f0fa65a:table:0005",
        "chunk:022ae1713fb760ff:body:0011",
        "chunk:16a9a510ef9e405f:body:0006",
        "chunk:6b55ddbbcfdc484d:body:0003"
      ]
    },
    {
      "query": "2026年上半年 营业收入 净利润",
      "count": 10,
      "delivery_preview": "pilot",
      "coverage": {
        "requested_scope_ref": "corpus_schema",
        "effective_scope_ref": "corpus_publications.active_build_id",
        "publication_snapshot_ref": "corpus_publications@48e8e60844f69177d5eb672a1d1b1010",
        "processing": "scoped",
        "query_status": "matched",
        "availability": "unknown",
        "reason_codes": [
          "partial_published",
          "gap_regions_present"
        ],
        "counts": {
          "sources": 22,
          "published": 18,
          "withdrawn": 0,
          "pending": 0,
          "failed_jobs": 0,
          "builds": 28,
          "published_with_gaps": 16
        },
        "retrieval": {
          "requested": "hybrid",
          "used": "hybrid",
          "reason": null,
          "profile": "fbd9941b77ff17a534932b7bbec32358ae5088df9854d62a93b2e38801c3e107",
          "expected_chunks": 703,
          "ready_chunks": 703,
          "lexical_candidates": 200,
          "vector_candidates": 200,
          "query_cache_hit": false,
          "query_usage": {
            "prompt_tokens": 40,
            "total_tokens": 40
          },
          "elapsed_ms": 634
        }
      },
      "previews": 3,
      "locators": [
        "chunk:568f9e752f0fa65a:table:0000",
        "chunk:9fa4cd7cf1ab602a:table:0000",
        "chunk:16a9a510ef9e405f:body:0007",
        "chunk:147e841aab35836a:body:0007",
        "chunk:7ceca88433b092ae:body:0002",
        "chunk:568f9e752f0fa65a:body:0016",
        "chunk:9fa4cd7cf1ab602a:table:0009",
        "chunk:16a9a510ef9e405f:body:0016",
        "chunk:147e841aab35836a:body:0014"
      ]
    },
    {
      "query": "紫荆量子",
      "count": 10,
      "delivery_preview": "pilot",
      "coverage": {
        "requested_scope_ref": "corpus_schema",
        "effective_scope_ref": "corpus_publications.active_build_id",
        "publication_snapshot_ref": "corpus_publications@48e8e60844f69177d5eb672a1d1b1010",
        "processing": "scoped",
        "query_status": "matched",
        "availability": "unknown",
        "reason_codes": [
          "partial_published",
          "gap_regions_present"
        ],
        "counts": {
          "sources": 22,
          "published": 18,
          "withdrawn": 0,
          "pending": 0,
          "failed_jobs": 0,
          "builds": 28,
          "published_with_gaps": 16
        },
        "retrieval": {
          "requested": "hybrid",
          "used": "hybrid",
          "reason": null,
          "profile": "fbd9941b77ff17a534932b7bbec32358ae5088df9854d62a93b2e38801c3e107",
          "expected_chunks": 703,
          "ready_chunks": 703,
          "lexical_candidates": 0,
          "vector_candidates": 200,
          "query_cache_hit": false,
          "query_usage": {
            "prompt_tokens": 32,
            "total_tokens": 32
          },
          "elapsed_ms": 465
        }
      },
      "previews": 0,
      "locators": [
        "chunk:2055995f24f1db3a:body:0010",
        "chunk:9ebd323f89e55cc1:table:0001",
        "chunk:6b55ddbbcfdc484d:list:0001",
        "chunk:82dac0d446ef83cd:body:0070",
        "chunk:e1b21386e9b62dde:body:0029",
        "chunk:2055995f24f1db3a:body:0014",
        "chunk:9ebd323f89e55cc1:table:0006",
        "chunk:6b55ddbbcfdc484d:body:0003",
        "chunk:82dac0d446ef83cd:table:0032",
        "chunk:e1b21386e9b62dde:body:0017"
      ]
    },
    {
      "query": "紫荆量子光电股份有限公司 半年度报告",
      "count": 10,
      "delivery_preview": "pilot",
      "coverage": {
        "requested_scope_ref": "corpus_schema",
        "effective_scope_ref": "corpus_publications.active_build_id",
        "publication_snapshot_ref": "corpus_publications@48e8e60844f69177d5eb672a1d1b1010",
        "processing": "scoped",
        "query_status": "matched",
        "availability": "unknown",
        "reason_codes": [
          "partial_published",
          "gap_regions_present"
        ],
        "counts": {
          "sources": 22,
          "published": 18,
          "withdrawn": 0,
          "pending": 0,
          "failed_jobs": 0,
          "builds": 28,
          "published_with_gaps": 16
        },
        "retrieval": {
          "requested": "hybrid",
          "used": "hybrid",
          "reason": null,
          "profile": "fbd9941b77ff17a534932b7bbec32358ae5088df9854d62a93b2e38801c3e107",
          "expected_chunks": 703,
          "ready_chunks": 703,
          "lexical_candidates": 124,
          "vector_candidates": 200,
          "query_cache_hit": false,
          "query_usage": {
            "prompt_tokens": 39,
            "total_tokens": 39
          },
          "elapsed_ms": 519
        }
      },
      "previews": 9,
      "locators": [
        "chunk:16a9a510ef9e405f:body:0007",
        "chunk:568f9e752f0fa65a:body:0014",
        "chunk:7ceca88433b092ae:body:0014",
        "chunk:82dac0d446ef83cd:body:0070",
        "chunk:022ae1713fb760ff:body:0000",
        "chunk:16a9a510ef9e405f:body:0016",
        "chunk:568f9e752f0fa65a:body:0014",
        "chunk:7ceca88433b092ae:body:0014",
        "chunk:82dac0d446ef83cd:body:0019",
        "chunk:022ae1713fb760ff:body:0021"
      ]
    },
    {
      "query": "量子光电",
      "count": 5,
      "delivery_preview": "pilot",
      "coverage": {
        "requested_scope_ref": "corpus_schema",
        "effective_scope_ref": "corpus_publications.active_build_id",
        "publication_snapshot_ref": "corpus_publications@48e8e60844f69177d5eb672a1d1b1010",
        "processing": "scoped",
        "query_status": "matched",
        "availability": "unknown",
        "reason_codes": [
          "partial_published",
          "gap_regions_present"
        ],
        "counts": {
          "sources": 22,
          "published": 18,
          "withdrawn": 0,
          "pending": 0,
          "failed_jobs": 0,
          "builds": 28,
          "published_with_gaps": 16
        },
        "retrieval": {
          "requested": "hybrid",
          "used": "hybrid",
          "reason": null,
          "profile": "fbd9941b77ff17a534932b7bbec32358ae5088df9854d62a93b2e38801c3e107",
          "expected_chunks": 703,
          "ready_chunks": 703,
          "lexical_candidates": 11,
          "vector_candidates": 200,
          "query_cache_hit": false,
          "query_usage": {
            "prompt_tokens": 32,
            "total_tokens": 32
          },
          "elapsed_ms": 476
        }
      },
      "previews": 3,
      "locators": [
        "chunk:7ceca88433b092ae:body:0014",
        "chunk:568f9e752f0fa65a:table:0005",
        "chunk:022ae1713fb760ff:body:0011",
        "chunk:16a9a510ef9e405f:body:0006",
        "chunk:9ebd323f89e55cc1:table:0001"
      ]
    },
    {
      "query": "紫荆",
      "count": 5,
      "delivery_preview": "pilot",
      "coverage": {
        "requested_scope_ref": "corpus_schema",
        "effective_scope_ref": "corpus_publications.active_build_id",
        "publication_snapshot_ref": "corpus_publications@48e8e60844f69177d5eb672a1d1b1010",
        "processing": "scoped",
        "query_status": "matched",
        "availability": "unknown",
        "reason_codes": [
          "partial_published",
          "gap_regions_present"
        ],
        "counts": {
          "sources": 22,
          "published": 18,
          "withdrawn": 0,
          "pending": 0,
          "failed_jobs": 0,
          "builds": 28,
          "published_with_gaps": 16
        },
        "retrieval": {
          "requested": "hybrid",
          "used": "hybrid",
          "reason": null,
          "profile": "fbd9941b77ff17a534932b7bbec32358ae5088df9854d62a93b2e38801c3e107",
          "expected_chunks": 703,
          "ready_chunks": 703,
          "lexical_candidates": 0,
          "vector_candidates": 200,
          "query_cache_hit": false,
          "query_usage": {
            "prompt_tokens": 31,
            "total_tokens": 31
          },
          "elapsed_ms": 618
        }
      },
      "previews": 0,
      "locators": [
        "chunk:568f9e752f0fa65a:heading:0008",
        "chunk:82dac0d446ef83cd:body:0067",
        "chunk:628ec76d5b4001b7:body:0016",
        "chunk:022ae1713fb760ff:heading:0002",
        "chunk:9ebd323f89e55cc1:table:0000"
      ]
    },
    {
      "query": "紫荆量子光电股份有限公司",
      "count": 5,
      "delivery_preview": "pilot",
      "coverage": {
        "requested_scope_ref": "corpus_schema",
        "effective_scope_ref": "corpus_publications.active_build_id",
        "publication_snapshot_ref": "corpus_publications@48e8e60844f69177d5eb672a1d1b1010",
        "processing": "scoped",
        "query_status": "matched",
        "availability": "unknown",
        "reason_codes": [
          "partial_published",
          "gap_regions_present"
        ],
        "counts": {
          "sources": 22,
          "published": 18,
          "withdrawn": 0,
          "pending": 0,
          "failed_jobs": 0,
          "builds": 28,
          "published_with_gaps": 16
        },
        "retrieval": {
          "requested": "hybrid",
          "used": "hybrid",
          "reason": null,
          "profile": "fbd9941b77ff17a534932b7bbec32358ae5088df9854d62a93b2e38801c3e107",
          "expected_chunks": 703,
          "ready_chunks": 703,
          "lexical_candidates": 62,
          "vector_candidates": 200,
          "query_cache_hit": false,
          "query_usage": {
            "prompt_tokens": 35,
            "total_tokens": 35
          },
          "elapsed_ms": 642
        }
      },
      "previews": 3,
      "locators": [
        "chunk:7ceca88433b092ae:body:0014",
        "chunk:022ae1713fb760ff:body:0004",
        "chunk:16a9a510ef9e405f:body:0014",
        "chunk:82dac0d446ef83cd:body:0019",
        "chunk:568f9e752f0fa65a:body:0038"
      ]
    }
  ],
  "fetches": [
    {
      "args": {
        "doc_id": "cv2:568f9e752f0fa65a0e7f52d89b25af3ff8e8078e68510aeb77baac09c289ceea",
        "locators": [
          "chunk:568f9e752f0fa65a:body:0025",
          "chunk:568f9e752f0fa65a:heading:0008",
          "chunk:568f9e752f0fa65a:body:0026"
        ],
        "view": "compact"
      },
      "text_chars": 216,
      "fetch_complete": true,
      "ok": true,
      "locators_returned": [
        "chunk:568f9e752f0fa65a:body:0025",
        "chunk:568f9e752f0fa65a:heading:0008",
        "chunk:568f9e752f0fa65a:body:0026"
      ],
      "followed_by_assistant": true
    }
  ]
}
```

## p01 / off

国金电子报告怎样解释麒麟芯片晶体管更多、做同样工作却更省电？

清单已验证通过（supported）。以下为最终答案。

**答案**

国金电子行业周报（转述华为何庭波9月4日发布于中科院预发布平台ChinaXiv的论文《Huawei's τ Chip Was Supposed to Melt?》）对“晶体管更多、做同样工作却更省电”的解释是：

**反常识的核心原因：芯片绝大部分能耗并非消耗在晶体管本身的计算运算上，而是消耗在金属走线的数据搬运上——“如同上班族通勤的能量消耗远大于工位办公”。** 据此有三层机理：
1. **逻辑折叠大幅缩短信号走线长度**，直接削减占据功耗大头的互连电容开销；
2. 走线变短后，电路**可以进一步降低工作电压**；
3. **动态功耗与电压平方成正比**，降电压由此带来幅度更大的功耗收益。

报告给出的实测数据支撑：麒麟2026晶体管密度从约每平方毫米1.55亿提升到2.38亿个（跃升55%）；在同等性能测试条件下，对比前代平面架构麒麟9030 Pro，麒麟2026的NPU功耗下降66%、GPU功耗下降58%、CPU性能大核功耗下降41%——晶体管数量暴涨的同时，完成同等工作的芯片工作温度更低。

**来源**
- 标题：国金证券电子行业周报（语料中标题字段为乱码，正文页眉标注“行业周报”；多处图表来源标注“来源：Wind，国金证券研究所”，内容为电子板块PCB/半导体设备/消费电子景气跟踪）
- doc_id：`cv2:16a9a510ef9e405fa8fd97df975b23b009e728c983c04cafda8bcf0973eed287`
- locator：核心解释与数据 `chunk:16a9a510ef9e405f:body:0001`（第1页“投资逻辑”）；券商归属佐证 `chunk:16a9a510ef9e405f:body:0003`

说明：以上仅为该报告转述论文的说法，语料库内无其他来源可交叉验证；报告本身将其作为半导体设备板块的产业逻辑依据。

耗时 183.913 秒；search 2 次；fetch 4 次；返回正文 4812 字符；重复相同片段去重后 4812 字符。

```json
{
  "searches": [
    {
      "query": "麒麟 晶体管 省电",
      "count": 10,
      "delivery_preview": null,
      "coverage": {
        "requested_scope_ref": "corpus_schema",
        "effective_scope_ref": "corpus_publications.active_build_id",
        "publication_snapshot_ref": "corpus_publications@48e8e60844f69177d5eb672a1d1b1010",
        "processing": "scoped",
        "query_status": "matched",
        "availability": "unknown",
        "reason_codes": [
          "partial_published",
          "gap_regions_present"
        ],
        "counts": {
          "sources": 22,
          "published": 18,
          "withdrawn": 0,
          "pending": 0,
          "failed_jobs": 0,
          "builds": 28,
          "published_with_gaps": 16
        },
        "retrieval": {
          "requested": "hybrid",
          "used": "hybrid",
          "reason": null,
          "profile": "fbd9941b77ff17a534932b7bbec32358ae5088df9854d62a93b2e38801c3e107",
          "expected_chunks": 703,
          "ready_chunks": 703,
          "lexical_candidates": 4,
          "vector_candidates": 200,
          "query_cache_hit": false,
          "query_usage": {
            "prompt_tokens": 35,
            "total_tokens": 35
          },
          "elapsed_ms": 660
        }
      },
      "previews": 0,
      "locators": [
        "chunk:16a9a510ef9e405f:body:0001",
        "chunk:2055995f24f1db3a:body:0010",
        "chunk:9fa4cd7cf1ab602a:body:0005",
        "chunk:147e841aab35836a:body:0010",
        "chunk:568f9e752f0fa65a:table:0008",
        "chunk:16a9a510ef9e405f:body:0001",
        "chunk:2055995f24f1db3a:body:0010",
        "chunk:9fa4cd7cf1ab602a:body:0018",
        "chunk:147e841aab35836a:body:0000",
        "chunk:568f9e752f0fa65a:heading:0002"
      ]
    },
    {
      "query": "国金 电子 麒麟 芯片 功耗",
      "count": 10,
      "delivery_preview": null,
      "coverage": {
        "requested_scope_ref": "corpus_schema",
        "effective_scope_ref": "corpus_publications.active_build_id",
        "publication_snapshot_ref": "corpus_publications@48e8e60844f69177d5eb672a1d1b1010",
        "processing": "scoped",
        "query_status": "matched",
        "availability": "unknown",
        "reason_codes": [
          "partial_published",
          "gap_regions_present"
        ],
        "counts": {
          "sources": 22,
          "published": 18,
          "withdrawn": 0,
          "pending": 0,
          "failed_jobs": 0,
          "builds": 28,
          "published_with_gaps": 16
        },
        "retrieval": {
          "requested": "hybrid",
          "used": "hybrid",
          "reason": null,
          "profile": "fbd9941b77ff17a534932b7bbec32358ae5088df9854d62a93b2e38801c3e107",
          "expected_chunks": 703,
          "ready_chunks": 703,
          "lexical_candidates": 59,
          "vector_candidates": 200,
          "query_cache_hit": false,
          "query_usage": {
            "prompt_tokens": 40,
            "total_tokens": 40
          },
          "elapsed_ms": 468
        }
      },
      "previews": 0,
      "locators": [
        "chunk:022ae1713fb760ff:body:0004",
        "chunk:16a9a510ef9e405f:body:0001",
        "chunk:2055995f24f1db3a:body:0010",
        "chunk:1d0117eb6e17c63c:body:0007",
        "chunk:7ceca88433b092ae:body:0011",
        "chunk:022ae1713fb760ff:body:0004",
        "chunk:16a9a510ef9e405f:body:0011",
        "chunk:2055995f24f1db3a:body:0010",
        "chunk:7ceca88433b092ae:body:0004",
        "chunk:022ae1713fb760ff:body:0022"
      ]
    }
  ],
  "fetches": [
    {
      "args": {
        "doc_id": "cv2:16a9a510ef9e405fa8fd97df975b23b009e728c983c04cafda8bcf0973eed287",
        "locators": [
          "chunk:16a9a510ef9e405f:body:0000",
          "chunk:16a9a510ef9e405f:heading:0000",
          "chunk:16a9a510ef9e405f:body:0001",
          "chunk:16a9a510ef9e405f:body:0002",
          "chunk:16a9a510ef9e405f:heading:0001"
        ],
        "max_chars": 6000
      },
      "text_chars": 1125,
      "fetch_complete": false,
      "ok": true,
      "locators_returned": [
        "chunk:16a9a510ef9e405f:body:0000",
        "chunk:16a9a510ef9e405f:heading:0000",
        "chunk:16a9a510ef9e405f:body:0001"
      ],
      "followed_by_assistant": true
    },
    {
      "args": {
        "doc_id": "cv2:022ae1713fb760ffa04efb1939fc0ce25a330aecf0df7350c954ccbe8a7a66ef",
        "locators": [
          "chunk:022ae1713fb760ff:body:0000",
          "chunk:022ae1713fb760ff:body:0001",
          "chunk:022ae1713fb760ff:body:0002",
          "chunk:022ae1713fb760ff:body:0003",
          "chunk:022ae1713fb760ff:body:0004",
          "chunk:022ae1713fb760ff:body:0005"
        ],
        "max_chars": 6000
      },
      "text_chars": 2288,
      "fetch_complete": false,
      "ok": true,
      "locators_returned": [
        "chunk:022ae1713fb760ff:body:0000",
        "chunk:022ae1713fb760ff:body:0001"
      ],
      "followed_by_assistant": true
    },
    {
      "args": {
        "cursor": "eyJidWlsZF9pZCI6IjE2YTlhNTEwZWY5ZTQwNWZhOGZkOTdkZjk3NWIyM2IwMDllNzI4Yzk4M2MwNGNhZmRhOGJjZjA5NzNlZWQyODciLCJkb2NfaWQiOiJjdjI6MTZhOWE1MTBlZjllNDA1ZmE4ZmQ5N2RmOTc1YjIzYjAwOWU3MjhjOTgzYzA0Y2FmZGE4YmNmMDk3M2VlZDI4NyIsIm1pIjozLCJvZmYiOjAsInJlcSI6WyJjaHVuazoxNmE5YTUxMGVmOWU0MDVmOmJvZHk6MDAwMCIsImNodW5rOjE2YTlhNTEwZWY5ZTQwNWY6aGVhZGluZzowMDAwIiwiY2h1bms6MTZhOWE1MTBlZjllNDA1Zjpib2R5OjAwMDEiLCJjaHVuazoxNmE5YTUxMGVmOWU0MDVmOmJvZHk6MDAwMiIsImNodW5rOjE2YTlhNTEwZWY5ZTQwNWY6aGVhZGluZzowMDAxIl0sInN1bSI6IjgwZjRlMjMwZjUwYjUwZTciLCJ0eXBlIjoiY29udGVudCIsInVucmVzb2x2ZWQiOltdLCJ2IjoxLCJ2aWV3IjoiZnVsbCJ9",
        "doc_id": "cv2:16a9a510ef9e405fa8fd97df975b23b009e728c983c04cafda8bcf0973eed287",
        "max_chars": 6000
      },
      "text_chars": 463,
      "fetch_complete": true,
      "ok": true,
      "locators_returned": [
        "chunk:16a9a510ef9e405f:body:0002",
        "chunk:16a9a510ef9e405f:heading:0001"
      ],
      "followed_by_assistant": true
    },
    {
      "args": {
        "doc_id": "cv2:16a9a510ef9e405fa8fd97df975b23b009e728c983c04cafda8bcf0973eed287",
        "locators": [
          "chunk:16a9a510ef9e405f:body:0003",
          "chunk:16a9a510ef9e405f:heading:0002",
          "chunk:16a9a510ef9e405f:heading:0003",
          "chunk:16a9a510ef9e405f:heading:0004",
          "chunk:16a9a510ef9e405f:heading:0005",
          "chunk:16a9a510ef9e405f:body:0012"
        ],
        "max_chars": 6000,
        "view": "compact"
      },
      "text_chars": 936,
      "fetch_complete": false,
      "ok": true,
      "locators_returned": [
        "chunk:16a9a510ef9e405f:body:0003",
        "chunk:16a9a510ef9e405f:heading:0002",
        "chunk:16a9a510ef9e405f:heading:0003",
        "chunk:16a9a510ef9e405f:heading:0004",
        "chunk:16a9a510ef9e405f:heading:0005"
      ],
      "followed_by_assistant": true
    }
  ]
}
```

## p01 / pilot

国金电子报告怎样解释麒麟芯片晶体管更多、做同样工作却更省电？

清单已验证通过（1 条结论均 supported）。以下为最终答案：

---

**答案**

国金证券电子行业周报（投资逻辑部分，主题为"韬定律"与业绩斜率：AI PCB 及半导体设备迎来布局良机）对该反常识现象的解释是：

- **现象数据**：麒麟2026 芯片晶体管密度从约每平方毫米 1.55 亿提升到 2.38 亿个，跃升 55%；在同等性能测试条件下，对比前代平面架构麒麟9030 Pro，NPU 功耗下降 66%、GPU 功耗下降 58%、CPU 性能大核功耗下降 41%——晶体管数量暴涨的同时，完成同等工作的芯片工作温度更低。

- **省电原因（报告转述论文解释的"反常识核心原因"）**：芯片绝大部分能耗并非消耗在晶体管本身的计算运算上，而是消耗在金属走线的数据搬运上，"如同上班族通勤的能量消耗远大于工位办公"。逻辑折叠大幅缩短信号走线长度，直接削减占据功耗大头的互连电容开销；同时走线变短后，电路可以进一步降低工作电压，而动态功耗与电压平方成正比，由此带来幅度更大的功耗收益。

- **来源背景**：该解释出自华为半导体负责人何庭波 9 月 4 日在中科院科技论文预发布平台 ChinaXiv 发布的论文《Huawei's τ Chip Was Supposed to Melt?》，国金电子周报在其"投资逻辑"部分予以转述。

**来源**
- 来源标题：国金证券电子行业周报·投资逻辑（"韬定律"与业绩斜率：AI PCB 及半导体设备迎来布局良机）
- doc_id：`cv2:16a9a510ef9e405fa8fd97df975b23b009e728c983c04cafda8bcf0973eed287`
- locator：`chunk:16a9a510ef9e405f:body:0001`（出处归属佐证：`chunk:16a9a510ef9e405f:body:0011`，图表落款"来源：Wind，国金证券研究所"）

耗时 115.834 秒；search 2 次；fetch 2 次；返回正文 2125 字符；重复相同片段去重后 2125 字符。

```json
{
  "searches": [
    {
      "query": "麒麟 晶体管 省电",
      "count": 4,
      "delivery_preview": "pilot",
      "coverage": {
        "requested_scope_ref": "corpus_schema",
        "effective_scope_ref": "corpus_publications.active_build_id",
        "publication_snapshot_ref": "corpus_publications@48e8e60844f69177d5eb672a1d1b1010",
        "processing": "scoped",
        "query_status": "matched",
        "availability": "unknown",
        "reason_codes": [
          "partial_published",
          "gap_regions_present"
        ],
        "counts": {
          "sources": 22,
          "published": 18,
          "withdrawn": 0,
          "pending": 0,
          "failed_jobs": 0,
          "builds": 28,
          "published_with_gaps": 16
        },
        "retrieval": {
          "requested": "hybrid",
          "used": "lexical",
          "reason": "provider_transport_uncertain",
          "elapsed_ms": 15178
        }
      },
      "previews": 4,
      "locators": [
        "chunk:16a9a510ef9e405f:body:0001",
        "chunk:147e841aab35836a:body:0010",
        "chunk:2055995f24f1db3a:body:0010",
        "chunk:9fa4cd7cf1ab602a:body:0018"
      ]
    },
    {
      "query": "国金电子 麒麟芯片",
      "count": 10,
      "delivery_preview": "pilot",
      "coverage": {
        "requested_scope_ref": "corpus_schema",
        "effective_scope_ref": "corpus_publications.active_build_id",
        "publication_snapshot_ref": "corpus_publications@48e8e60844f69177d5eb672a1d1b1010",
        "processing": "scoped",
        "query_status": "matched",
        "availability": "unknown",
        "reason_codes": [
          "partial_published",
          "gap_regions_present"
        ],
        "counts": {
          "sources": 22,
          "published": 18,
          "withdrawn": 0,
          "pending": 0,
          "failed_jobs": 0,
          "builds": 28,
          "published_with_gaps": 16
        },
        "retrieval": {
          "requested": "hybrid",
          "used": "hybrid",
          "reason": null,
          "profile": "fbd9941b77ff17a534932b7bbec32358ae5088df9854d62a93b2e38801c3e107",
          "expected_chunks": 703,
          "ready_chunks": 703,
          "lexical_candidates": 59,
          "vector_candidates": 200,
          "query_cache_hit": false,
          "query_usage": {
            "prompt_tokens": 36,
            "total_tokens": 36
          },
          "elapsed_ms": 449
        }
      },
      "previews": 10,
      "locators": [
        "chunk:022ae1713fb760ff:body:0004",
        "chunk:16a9a510ef9e405f:body:0001",
        "chunk:2055995f24f1db3a:body:0010",
        "chunk:1d0117eb6e17c63c:body:0002",
        "chunk:568f9e752f0fa65a:body:0017",
        "chunk:022ae1713fb760ff:body:0004",
        "chunk:16a9a510ef9e405f:body:0011",
        "chunk:2055995f24f1db3a:body:0010",
        "chunk:568f9e752f0fa65a:body:0017",
        "chunk:022ae1713fb760ff:body:0012"
      ]
    }
  ],
  "fetches": [
    {
      "args": {
        "doc_id": "cv2:16a9a510ef9e405fa8fd97df975b23b009e728c983c04cafda8bcf0973eed287",
        "locators": [
          "chunk:16a9a510ef9e405f:heading:0000",
          "chunk:16a9a510ef9e405f:body:0000",
          "chunk:16a9a510ef9e405f:body:0001"
        ],
        "view": "compact"
      },
      "text_chars": 1125,
      "fetch_complete": true,
      "ok": true,
      "locators_returned": [
        "chunk:16a9a510ef9e405f:heading:0000",
        "chunk:16a9a510ef9e405f:body:0000",
        "chunk:16a9a510ef9e405f:body:0001"
      ],
      "followed_by_assistant": true
    },
    {
      "args": {
        "doc_id": "cv2:16a9a510ef9e405fa8fd97df975b23b009e728c983c04cafda8bcf0973eed287",
        "locators": [
          "chunk:16a9a510ef9e405f:heading:0005",
          "chunk:16a9a510ef9e405f:body:0010",
          "chunk:16a9a510ef9e405f:body:0011",
          "chunk:16a9a510ef9e405f:body:0012"
        ],
        "view": "compact"
      },
      "text_chars": 1000,
      "fetch_complete": true,
      "ok": true,
      "locators_returned": [
        "chunk:16a9a510ef9e405f:heading:0005",
        "chunk:16a9a510ef9e405f:body:0010",
        "chunk:16a9a510ef9e405f:body:0011",
        "chunk:16a9a510ef9e405f:body:0012"
      ],
      "followed_by_assistant": true
    }
  ]
}
```

## p16 / off

国联民生的CIOE前瞻里，华工正源和立讯技术分别计划展示什么NPO产品？

清单已验证通过（C1: supported）。答案如下：

**国联民生《通信行业周报：2026 CIOE 中国光博会前瞻》（2026-09-06，分析师张宁、范宇）第1页原文：**

> “2）NPO 加速推动光引擎向交换芯片侧靠近……**华工正源将动态展示 6.4T 去 DSP NPO 光引擎，立讯技术则计划展示 3.2T NPO 光引擎 Live Demo**。”

**结论：**
- **华工正源**：动态展示 **6.4T 去 DSP NPO 光引擎**
- **立讯技术**：计划展示 **3.2T NPO 光引擎 Live Demo**

**来源**
- 标题：《通信行业周报 2026 CIOE 中国光博会前瞻》（国联民生证券，2026年09月06日）
- doc_id：`cv2:7ceca88433b092aef112bb25c95d221665080c5f9c979ad37eb4cbeeee40e509`
- locator：`chunk:7ceca88433b092ae:body:0001`（第1页）

耗时 49.621 秒；search 2 次；fetch 1 次；返回正文 2068 字符；重复相同片段去重后 2068 字符。

```json
{
  "searches": [
    {
      "query": "CIOE 华工正源 NPO",
      "count": 10,
      "delivery_preview": null,
      "coverage": {
        "requested_scope_ref": "corpus_schema",
        "effective_scope_ref": "corpus_publications.active_build_id",
        "publication_snapshot_ref": "corpus_publications@48e8e60844f69177d5eb672a1d1b1010",
        "processing": "scoped",
        "query_status": "matched",
        "availability": "unknown",
        "reason_codes": [
          "partial_published",
          "gap_regions_present"
        ],
        "counts": {
          "sources": 22,
          "published": 18,
          "withdrawn": 0,
          "pending": 0,
          "failed_jobs": 0,
          "builds": 28,
          "published_with_gaps": 16
        },
        "retrieval": {
          "requested": "hybrid",
          "used": "hybrid",
          "reason": null,
          "profile": "fbd9941b77ff17a534932b7bbec32358ae5088df9854d62a93b2e38801c3e107",
          "expected_chunks": 703,
          "ready_chunks": 703,
          "lexical_candidates": 25,
          "vector_candidates": 200,
          "query_cache_hit": false,
          "query_usage": {
            "prompt_tokens": 39,
            "total_tokens": 39
          },
          "elapsed_ms": 450
        }
      },
      "previews": 0,
      "locators": [
        "chunk:7ceca88433b092ae:body:0004",
        "chunk:6475cbacca1575c5:body:0001",
        "chunk:022ae1713fb760ff:body:0004",
        "chunk:16a9a510ef9e405f:body:0007",
        "chunk:568f9e752f0fa65a:body:0014",
        "chunk:6475cbacca1575c5:body:0001",
        "chunk:022ae1713fb760ff:body:0004",
        "chunk:16a9a510ef9e405f:body:0014",
        "chunk:568f9e752f0fa65a:heading:0005",
        "chunk:022ae1713fb760ff:body:0013"
      ]
    },
    {
      "query": "立讯技术 NPO 展示",
      "count": 10,
      "delivery_preview": null,
      "coverage": {
        "requested_scope_ref": "corpus_schema",
        "effective_scope_ref": "corpus_publications.active_build_id",
        "publication_snapshot_ref": "corpus_publications@48e8e60844f69177d5eb672a1d1b1010",
        "processing": "scoped",
        "query_status": "matched",
        "availability": "unknown",
        "reason_codes": [
          "partial_published",
          "gap_regions_present"
        ],
        "counts": {
          "sources": 22,
          "published": 18,
          "withdrawn": 0,
          "pending": 0,
          "failed_jobs": 0,
          "builds": 28,
          "published_with_gaps": 16
        },
        "retrieval": {
          "requested": "hybrid",
          "used": "hybrid",
          "reason": null,
          "profile": "fbd9941b77ff17a534932b7bbec32358ae5088df9854d62a93b2e38801c3e107",
          "expected_chunks": 703,
          "ready_chunks": 703,
          "lexical_candidates": 54,
          "vector_candidates": 200,
          "query_cache_hit": false,
          "query_usage": {
            "prompt_tokens": 37,
            "total_tokens": 37
          },
          "elapsed_ms": 589
        }
      },
      "previews": 0,
      "locators": [
        "chunk:7ceca88433b092ae:body:0001",
        "chunk:022ae1713fb760ff:body:0004",
        "chunk:6475cbacca1575c5:body:0001",
        "chunk:16a9a510ef9e405f:body:0007",
        "chunk:568f9e752f0fa65a:body:0014",
        "chunk:7ceca88433b092ae:body:0001",
        "chunk:022ae1713fb760ff:body:0004",
        "chunk:16a9a510ef9e405f:body:0007",
        "chunk:568f9e752f0fa65a:body:0014",
        "chunk:7ceca88433b092ae:body:0014"
      ]
    }
  ],
  "fetches": [
    {
      "args": {
        "doc_id": "cv2:7ceca88433b092aef112bb25c95d221665080c5f9c979ad37eb4cbeeee40e509",
        "locators": [
          "chunk:7ceca88433b092ae:body:0001",
          "chunk:7ceca88433b092ae:body:0002",
          "chunk:7ceca88433b092ae:body:0003",
          "chunk:7ceca88433b092ae:body:0004",
          "chunk:7ceca88433b092ae:body:0005"
        ]
      },
      "text_chars": 2068,
      "fetch_complete": false,
      "ok": true,
      "locators_returned": [
        "chunk:7ceca88433b092ae:body:0001",
        "chunk:7ceca88433b092ae:body:0002"
      ],
      "followed_by_assistant": true
    }
  ]
}
```

## p16 / pilot

国联民生的CIOE前瞻里，华工正源和立讯技术分别计划展示什么NPO产品？

已取全原文，两家的NPO展品信息都已确认。按流程先提交证据清单，再给出最终答案。

耗时 277.178 秒；search 2 次；fetch 2 次；返回正文 5111 字符；重复相同片段去重后 5111 字符。

```json
{
  "searches": [
    {
      "query": "CIOE 前瞻 NPO 华工正源 立讯",
      "count": 10,
      "delivery_preview": "pilot",
      "coverage": {
        "requested_scope_ref": "corpus_schema",
        "effective_scope_ref": "corpus_publications.active_build_id",
        "publication_snapshot_ref": "corpus_publications@48e8e60844f69177d5eb672a1d1b1010",
        "processing": "scoped",
        "query_status": "matched",
        "availability": "unknown",
        "reason_codes": [
          "partial_published",
          "gap_regions_present"
        ],
        "counts": {
          "sources": 22,
          "published": 18,
          "withdrawn": 0,
          "pending": 0,
          "failed_jobs": 0,
          "builds": 28,
          "published_with_gaps": 16
        },
        "retrieval": {
          "requested": "hybrid",
          "used": "hybrid",
          "reason": null,
          "profile": "fbd9941b77ff17a534932b7bbec32358ae5088df9854d62a93b2e38801c3e107",
          "expected_chunks": 703,
          "ready_chunks": 703,
          "lexical_candidates": 27,
          "vector_candidates": 200,
          "query_cache_hit": false,
          "query_usage": {
            "prompt_tokens": 44,
            "total_tokens": 44
          },
          "elapsed_ms": 380
        }
      },
      "previews": 7,
      "locators": [
        "chunk:7ceca88433b092ae:body:0001",
        "chunk:6475cbacca1575c5:body:0001",
        "chunk:6b55ddbbcfdc484d:body:0005",
        "chunk:022ae1713fb760ff:body:0004",
        "chunk:16a9a510ef9e405f:body:0007",
        "chunk:6475cbacca1575c5:body:0001",
        "chunk:6b55ddbbcfdc484d:body:0005",
        "chunk:022ae1713fb760ff:body:0004",
        "chunk:16a9a510ef9e405f:body:0014",
        "chunk:6b55ddbbcfdc484d:table:0002"
      ]
    },
    {
      "query": "国联民生 CIOE 光博会",
      "count": 10,
      "delivery_preview": "pilot",
      "coverage": {
        "requested_scope_ref": "corpus_schema",
        "effective_scope_ref": "corpus_publications.active_build_id",
        "publication_snapshot_ref": "corpus_publications@48e8e60844f69177d5eb672a1d1b1010",
        "processing": "scoped",
        "query_status": "matched",
        "availability": "unknown",
        "reason_codes": [
          "partial_published",
          "gap_regions_present"
        ],
        "counts": {
          "sources": 22,
          "published": 18,
          "withdrawn": 0,
          "pending": 0,
          "failed_jobs": 0,
          "builds": 28,
          "published_with_gaps": 16
        },
        "retrieval": {
          "requested": "hybrid",
          "used": "hybrid",
          "reason": null,
          "profile": "fbd9941b77ff17a534932b7bbec32358ae5088df9854d62a93b2e38801c3e107",
          "expected_chunks": 703,
          "ready_chunks": 703,
          "lexical_candidates": 24,
          "vector_candidates": 200,
          "query_cache_hit": false,
          "query_usage": {
            "prompt_tokens": 38,
            "total_tokens": 38
          },
          "elapsed_ms": 501
        }
      },
      "previews": 4,
      "locators": [
        "chunk:7ceca88433b092ae:body:0005",
        "chunk:147e841aab35836a:body:0004",
        "chunk:16a9a510ef9e405f:body:0007",
        "chunk:568f9e752f0fa65a:body:0014",
        "chunk:6475cbacca1575c5:body:0005",
        "chunk:147e841aab35836a:body:0004",
        "chunk:16a9a510ef9e405f:body:0001",
        "chunk:568f9e752f0fa65a:heading:0002",
        "chunk:147e841aab35836a:body:0010",
        "chunk:16a9a510ef9e405f:body:0014"
      ]
    }
  ],
  "fetches": [
    {
      "args": {
        "doc_id": "cv2:7ceca88433b092aef112bb25c95d221665080c5f9c979ad37eb4cbeeee40e509",
        "locators": [
          "chunk:7ceca88433b092ae:body:0003",
          "chunk:7ceca88433b092ae:body:0004",
          "chunk:7ceca88433b092ae:body:0005",
          "chunk:7ceca88433b092ae:body:0006"
        ],
        "view": "compact"
      },
      "text_chars": 2182,
      "fetch_complete": false,
      "ok": true,
      "locators_returned": [
        "chunk:7ceca88433b092ae:body:0003",
        "chunk:7ceca88433b092ae:body:0004"
      ],
      "followed_by_assistant": true
    },
    {
      "args": {
        "cursor": "eyJidWlsZF9pZCI6IjdjZWNhODg0MzNiMDkyYWVmMTEyYmIyNWM5NWQyMjE2NjUwODBjNWY5Yzk3OWFkMzdlYjRjYmVlZWU0MGU1MDkiLCJkb2NfaWQiOiJjdjI6N2NlY2E4ODQzM2IwOTJhZWYxMTJiYjI1Yzk1ZDIyMTY2NTA4MGM1ZjljOTc5YWQzN2ViNGNiZWVlZTQwZTUwOSIsIm1pIjoyLCJvZmYiOjAsInJlcSI6WyJjaHVuazo3Y2VjYTg4NDMzYjA5MmFlOmJvZHk6MDAwMyIsImNodW5rOjdjZWNhODg0MzNiMDkyYWU6Ym9keTowMDA0IiwiY2h1bms6N2NlY2E4ODQzM2IwOTJhZTpib2R5OjAwMDUiLCJjaHVuazo3Y2VjYTg4NDMzYjA5MmFlOmJvZHk6MDAwNiJdLCJzdW0iOiJkZTkzY2JlNGZiYmJmNGIyIiwidHlwZSI6ImNvbnRlbnQiLCJ1bnJlc29sdmVkIjpbXSwidiI6MSwidmlldyI6ImNvbXBhY3QifQ",
        "doc_id": "cv2:7ceca88433b092aef112bb25c95d221665080c5f9c979ad37eb4cbeeee40e509"
      },
      "text_chars": 2929,
      "fetch_complete": true,
      "ok": true,
      "locators_returned": [
        "chunk:7ceca88433b092ae:body:0005",
        "chunk:7ceca88433b092ae:body:0006"
      ],
      "followed_by_assistant": true
    }
  ]
}
```
