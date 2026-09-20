# I3-1 光力 p7 区域判级与收口（r38）

沿用 xyl 四份原签署，原文件未修改。光力 p7 现已发布，开发集 **8/8**，
company 3/3、industry 3/3、macro 2/2；PDF 6/6、DOCX 1/1、MD 1/1。
13 处缺口生命周期 acknowledged、0 blocking，默认分级及台账仍保留，coverage scoped。
I3-1 完成；I3-3/4/5、I3-6/7 与 M6 另行判定。

`human-gap-review-2` / `gap-policy-3` 在页级 required_locators 之下，完整展开人签
所引用批准投影的三条 p7 引文（含补充证据）。程序核对原 PDF SHA-256，从同一份字节
取得全部图像框，核对全部匹配 kept 单元的完整框和原 PDF 文字支持，并检验严格不相交。
不允许自填 bbox，不依据检索结果删目标，不用近似人签 y=155 截短完整正文框。
其余缺口类型、旋转页、跨单元引文、缺框/坏框、缺源/变源保持 fail-closed。

旧 schema-1 凭证逐字序列化及 review_id 保持兼容；新凭证没有覆盖旧凭证，光力此前未登记。
实际 PG 专用入口登记两次验证幂等，正式发布门复验，所有八份重新 check，通过。
build/quality_report 不变，七组真实 search/fetch/逐字核验通过，audit conflicts=0。

证据：

- [完整来源/发布/取证结果](release-e2e.json)
- [原签转写与区域预检](region-precheck.json)、[可执行凭证](review-dddc7cd0.json)、[发布检查点](publication.json)
- [回归：315 passed / 7 skipped](regression-e2e-guard.txt)，其中区域新增 11 项；跳过项未算作通过
- [守卫：19 passed](guard-self-tests.txt)

测试含重叠与多图位置、缺坐标/非有限坐标/伪框、坏源/缺源、缺引文、其他缺口码拒绝，
以及原凭证兼容、幂等发布和变源后复验拒绝。零模型、原 i3-e2e 守卫及冻结金标不变。
生产库未触及。区域 gate 每次需要可读取的哈希相符原 PDF；文件丢失即拒绝重验。

`archives.json` 记录编辑前归档，r38 作为 r37 子版本绑定实现、反例、实测、文档与验证器。
