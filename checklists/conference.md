# 会议模式 gate 清单

本文件由 `tools/newpaper/checklists.py` 从 `tools/ccfa/stages.py` 生成。
不要手工编辑；改状态机后重新生成。


## 1. [idea]

- [ ] gate `scope_defined`
  - 通过条件：问题陈述、至少一条可检验假设、目标 venue 均写明

## 2. [grounded]

- [ ] gate `novelty_grounded`
  - 通过条件：列出三篇最近邻工作及各自盲区，说明本工作填补的是哪一个无人测量的合取；novelty-audit 记录检索范围/日期与逐 claim 差异；禁止没人做过式表述

## 3. [data-ready]

- [ ] gate `provenance_recorded`
  - 通过条件：逐份数据有来源、分类与校验和；来源文档可被脚本核对；不合规来源已排除

## 4. [experiment-design]

- [ ] gate `design_frozen`
  - 通过条件：每个 claim 对应一个实验；baseline 来源明确；metric 定义明确；statistics-plan 含 alpha/多重比较、功效与样本量、种子、停止规则、缺失数据处理与平台画像

## 5. [experiments-running]

- [ ] gate `results_recorded`
  - 通过条件：experiments/log/ 逐次运行留有配置、种子、commit、退出码、指标

## 6. [results-ready]

- [ ] gate `claims_supported`
  - 通过条件：每个 claim 指到具体数值，且该数值通过行内标记脚本核对；无支撑项标记待验证或删除

## 7. [writing]

- [ ] gate `draft_complete`
  - 通过条件：正文、图表、引用齐备；页数符合 venue；所有引用条目来自检索期已核验的条目

## 8. [internal-review]

- [ ] gate `review_cleared`
  - 通过条件：跨模型评审报告无 blocking 项；引用、数字、图表三项核验通过；人工证明复核、引用语义支持与图表语义支持台账无未复核项

## 9. [submission-check]

- [ ] gate `package_ready`
  - 通过条件：模板、匿名、页数、元数据检查通过；复现包在干净环境实际重跑成功；repro-environment 记录 lockfile 哈希与系统工具版本证据；governance 台账齐备（署名/贡献、COI、伦理与许可、AI 使用、查重、双用途与负责任披露）

## 10. [submitted]

- [ ] gate `venue_decided`
  - 通过条件：收到 venue 决定，评审意见归档

## 11. [rebuttal]

- [ ] gate `rebuttal_submitted`
  - 通过条件：逐条回应完成，修改范围与承诺一致

## 12. [camera-ready]

- [ ] gate `final_package_ready`
  - 通过条件：终稿符合 camera-ready 规范；确定性终稿检查通过

## 13. [archived]

- [ ] gate `archived`
  - 通过条件：终稿、复现包、数据来源文档归档
