# Caption classification — draft for review

**Status: v0, not wired into anything.** Written before anyone had
looked at the corpus, from what `app/relevance.py` already documents
about what these searches return. Every category below is a guess
until it has been checked against a real sample, and the checking
procedure is at the bottom. Mark it up.

Run first, and bring the output back here:

```
./.venv/bin/python -m app.analyse --captions ~/Desktop/captions.txt
```

That writes every distinct Douyin caption, one per line, with **no
ids, no dates and no removal outcomes** — see "Why the dump is blind"
below.

---

## What this is for

Two separate questions, and they want different things from a label:

1. **Descriptive.** What is this corpus made of? A table of categories
   with counts, for the thesis' corpus section.
2. **Predictive.** Does what a post is about predict whether it is
   removed? A category used as a covariate.

The second constrains the design far more than the first. With ~61
removals in hand, a model can support something like **six predictors
at most** before it is fitting noise, so the scheme has to produce a
few well-populated categories rather than many thin ones. Anything
with under ~15 posts in it should be merged or dropped before it goes
near a regression.

## Why the dump is blind

`--captions` deliberately writes no outcome. If the captions used to
*design* the categories arrive labelled "this one was removed", the
categories that emerge are partly a description of removal, and the
later finding that content predicts removal is circular — the
taxonomy was fitted to the answer. Same rule at classification time:
the model never sees whether a post survived.

## Three axes, not one list

A single flat list forces one label onto posts that differ on
unrelated dimensions. These three are separable, and the second is
the one most likely to carry a finding.

### Axis A — 内容类型 (what the post is). One label.

| code | 名称 | 判断依据 |
|---|---|---|
| `couple` | 情侣日常 | 两个女性以伴侣关系出现：纪念日、同居、吵架和好、"我老婆" |
| `identity` | 出柜 / 身份叙述 | 出柜、向家人坦白、身份认同、"我是拉拉" |
| `feelings` | 情感叙事 / 心情文案 | 暗恋、分手、想念、单向倾诉；文案为主体 |
| `vlog` | 个人生活 | 日常、工作、旅行、穿搭；不以关系为主题 |
| `selfie` | 自拍 / 外貌 | 自拍、变装、妆容、身材 |
| `perform` | 舞蹈 / 手势舞 / 对口型 | 跟拍热门音频、手势舞、唱跳 |
| `fiction` | 虚构作品 | 短剧、小说、广播剧、漫画、剪辑（`relevance.FICTION` 已经在标） |
| `explain` | 科普 / 议论 | 解释名词、权益讨论、社群议题、新闻评论 |
| `seek` | 征友 / 社群 | 找朋友、找对象、拉群、同城 |
| `promo` | 商业 | 带货、课程、付费服务 |
| `unclear` | 无法判断 | 文本不足以判断 |
| `none` | 无 caption | 根本没有文本 — 不是一个内容类别，是一个缺失 |

`none` 必须单独存在。约 62 条抖音帖子完全没有 caption；把它们塞进
`unclear` 会让"无法判断"这一类同时包含"有文本但看不懂"和"根本没文本"
两种完全不同的东西。

### Axis B — 标记方式 (how it signals). 可多选。

这一轴来自你自己已经观察到的现象 —— `#wlw` 能搜到、`#l #e` 搜不到、
`#lwl` 返回的全是图文。如果标记方式和下架率相关，那是**这个研究最有
意思的发现之一**：它说的是作者在规避，以及规避是否有效。

| code | 名称 | 例 |
|---|---|---|
| `explicit` | 明确术语 | 女同性恋、拉拉、les、lesbian、出柜 |
| `evasive` | 变体 / 规避写法 | `#lwl`、`#l #e`、字母缩写、拼音、谐音、拆字、emoji 代称 |
| `english` | 英文标签 | `#wlw` `#gl` `#couple` |
| `genre` | 作品类标签 | 百合、GL、双女主、短剧 |
| `untagged` | 无任何标记 | 文本在讲这件事，但不带任何可搜索的词 |

### Axis C — 出镜 (risk-relevant). One label.

| code | 名称 |
|---|---|
| `face` | 文本显示真人出镜 / 本人叙述 |
| `noface` | 明确不出镜（纯文字、作品剪辑、风景） |
| `unknown` | 看不出来 |

Axis C 从 caption 判断是不可靠的 —— 真正的答案在画面里。保留它是为了
之后接上你 Google Cloud 那套视频分析时有个位置可以对齐；在那之前，
预期绝大多数会是 `unknown`，而那本身就是"caption 不够用"的证据。

---

## The prompt

分类用中文写，因为 caption 是中文；输出用英文 code，因为要进表。

```
你在为一项关于中文女同性恋（WLW）内容在抖音上被下架情况的学术研究
做内容编码。你会看到一条抖音帖子的 caption 文本。请只根据这段文本
进行分类。

重要规则：
1. 只依据给出的文本。不要推测画面内容，不要补全被截断的句子。
2. 不要依据你对该内容是否"敏感"或"会不会被平台处理"的判断来分类。
   该信息与本任务无关，且会污染后续分析。
3. 文本不足以判断时，使用 unclear / unknown，不要猜。宁可标为不确定，
   也不要给一个勉强的类别。
4. caption 中的话题标签（#xxx）既是内容线索，也是 B 轴的判断依据。

请输出严格的 JSON，不要有任何其他文字：

{
  "content": "<A 轴 code，单选>",
  "signals": ["<B 轴 code，可多个>"],
  "visibility": "<C 轴 code，单选>",
  "confidence": <0 到 1 的小数>,
  "evidence": "<引用 caption 中决定了 content 分类的那一小段原文，
                不超过 20 字；没有依据则填空字符串>"
}

A 轴 content 可选值：
couple   两个女性以伴侣关系出现（纪念日、同居、吵架和好、"我老婆"）
identity 出柜、向家人坦白、身份认同叙述
feelings 暗恋、分手、想念、单向情感倾诉，文案为主体
vlog     日常生活、工作、旅行、穿搭，不以关系为主题
selfie   自拍、变装、妆容、身材展示
perform  舞蹈、手势舞、对口型、跟拍热门音频
fiction  短剧、小说、广播剧、漫画、影视剪辑等虚构或二创作品
explain  科普、权益讨论、社群议题、新闻评论
seek     征友、找对象、拉群、同城交友
promo    带货、课程、付费服务等商业推广
unclear  文本不足以判断

B 轴 signals 可选值（可多选，至少一个）：
explicit 出现明确术语：女同性恋、拉拉、les、lesbian、出柜、女女
evasive  使用变体或规避写法：字母缩写、拼音、谐音、拆字、emoji 代称、
         被拆开或加空格的标签
english  使用英文标签：wlw、gl、couple、lesbian 作为 hashtag
genre    使用作品类标签：百合、GL、双女主、短剧
untagged 文本涉及该主题但不含任何可被搜索到的标记词

C 轴 visibility 可选值：
face     文本显示有真人出镜或为本人第一人称叙述
noface   文本显示无真人出镜（纯文字、作品剪辑、风景等）
unknown  无法判断

caption：
<<<
{caption}
>>>
```

### 调用上的几个约定

- **一条一次调用**，不要批量塞进一个 prompt。批量会让模型在同一批内
  互相参照（"这批大多是情侣，这条大概也是"），而那是批次效应，不是
  数据。
- **temperature 0**。这是编码任务不是生成任务。
- **不传任何 id、日期、点赞数、是否下架**。只传 caption 文本。
- 重复的 caption 只分类一次（`--captions` 已经去重）。
- 模型拒答或输出非 JSON 时，记为 `unclear` 并**保留原始返回**，不要
  重试到它给出一个答案为止 —— 一条需要重试三次才肯分类的 caption，
  本身就是数据。

## Before this counts as coding

一个 LLM 的输出在论文里不能直接当作编码结果。最低限度：

1. **你自己手工编码 50 条**（从 `captions.txt` 随机抽，不看模型结果）。
2. 和模型结果算一致性（Cohen's κ）。A 轴 κ < 0.6 说明类别定义有问题，
   要改定义重来，而不是改数据。
3. 在论文方法部分报告 κ、抽样方式、以及模型名称和版本。
4. 分歧的那些逐条看一遍 —— 分歧集中在哪两个类别之间，通常直接告诉你
   这两类该合并还是该重新定义。

## Open questions for you

- `feelings` 和 `couple` 会不会大面积重叠？（"想她" vs "和她三周年"）
- `fiction` 已经有一个正则在标了。要不要让模型重标一遍做交叉验证，
  还是直接信已有的标签？
- 图文（note）的文字很多在**图片里**，caption 可能只有一行。要不要
  给 note 单独一套规则，还是等 OCR？我的看法：等 OCR，现在把 note 的
  低 confidence 当成信号而不是噪音。
