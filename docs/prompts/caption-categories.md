# Caption classification — draft for review

**Status: v2, tag axes shipped as code, content axis awaiting your sign-off.**
Built against a real dump of 417 distinct captions, 372 of them in scope
(2026-10-01). Axes 2-5 are string matching and live in `app/labels.py`;
only `content` needs a model. Every count below is from that
dump. Nothing here runs until you have signed it off.

Re-export before using it — the first dump had two faults, both now
fixed, and both changed what the sample looked like:

```
./.venv/bin/python -m app.analyse --captions ~/Desktop/captions.txt
```

---

## Two faults in the first dump, and why they mattered

**1. The removed posts had no captions.** When Douyin answers with a
different video's record, the post is gone and `fetch_videos.wipe`
empties the fetched row — correctly, nothing in it belonged to that
id any more. The caption went with it. The dump read captions off
those fetched rows, so it returned text for the posts that survived
and blanks for the posts that were removed.

That is survivorship bias in the one place it is fatal. The whole
point of classifying captions is to ask whether content predicts
removal, and the removed half was arriving empty. `captions()` now
reads the **phone's capture first** — never wiped, and for a removed
post the only surviving copy of what it said — and falls back to the
fetched row only for ids the phone never saw.

**2. Out-of-scope rows were in the sample.** 师傅教做菜, 三角洲行动,
杭州黑珍珠探店, 桑拿鸡, 洛杉矶汽车旅馆, 聊斋动画. The topic filter
marks rather than deletes (rightly — a row a filter drops is a
disappearance nothing can ever observe), so the dump has to exclude
them itself. It now does. Left in, they would have produced
categories for cookery and shooter games.

Some of those may also be Douyin's substitute videos leaking in
through pasted links rather than genuine captures. Worth a look
separately; it does not change the classification design.

---

## What I would label: three fields, your three items

### 1. 内容类型 `content` — one label

Grounded in the dump. Counts are my hand reading of the 435, so
treat them as order-of-magnitude, not measurements.

| code | 名称 | 大致占比 | 真实例子 |
|---|---|---|---|
| `flirt` | 搭讪 / 挑逗 / 喊话 | **最大一类，≈35%** | 「你要我好友位不」「只有我喜欢的女孩能看到这条视频」「姐姐带你上天堂」 |
| `feelings` | 情感文案 / 心碎 | ≈20% | 「可是我想念你的时候 你又在哪里」「我们明明是最懂彼此的人，最后却退回陌生」 |
| `couple` | 情侣日常 | ≈12% | 「跟老婆在一起307天了」「两个女生的三周年礼物vlog」「#同居日常 #妻妻」 |
| `perform` | 手势舞 / 卡点 / 跟拍 | ≈12% | 「#瓜蛋摇」「#lui摇」「#钦钦摇 #手势舞」「#抖音潮流舞蹈大赛」 |
| `selfie` | 自拍 / 穿搭 / 变装 | ≈10% | 「右滑看我变中性」「#Lolita安利 #变装」「#地铁ootd」 |
| `fiction` | 虚构 / 二创 | ≈5% | 「《疯批的标记》p8 #双女主」「#漫剧#双女主#原创」 |
| `community` | 社群 / 线下 / 场所 | <3% | 「昆明拉吧（全女酒吧）KNINE」「#全女bar」「#上海拉吧」 |
| `meta` | 平台 / 账号自述 | <3% | 「涨了一个粉丝」「和我的53个粉丝汇报一下」「该叫我什么？被屏了重发」 |
| `unclear` | 无法判断 | — | 「😴」「🙄。#wlw」「出海打鱼」 |
| `none` | 无 caption | 另计 | — |

**`flirt` 是我加的，不在你的列表里，但它是最大的一类。** 你原本给的
是"恋爱关系"，而实际语料里绝大多数不是在描述一段关系，是在**对着
镜头向不特定的女生喊话**。「你要我好友位不」出现了至少三次，是一种
格式。把它和 `couple`（真的在讲"我和她"）分开，因为这两类在可识别
性、是否出镜、是否涉及真实伴侣上完全不同 —— 如果下架有差异，多半
差在这条线上。

`none`（46 条无 caption）必须独立。塞进 `unclear` 会让"无法判断"
同时装着"有字但看不懂"和"根本没字"两种完全不同的东西。

### 2. 女同相关标记 `wlw_tags` — 可多选，字符串匹配

**不需要模型。** 这一轴是字符串匹配，代码在 `app/labels.py`，完全可
复现、零成本、不需要报一致性系数。下面是 372 条 in-scope caption 上
跑出来的真实分布：

| code | 覆盖的写法 | 条数 | 占比 |
|---|---|---|---|
| `wlw` | `#wlw` | 276 | 74.2% |
| `lwl` | `#lwl` | 117 | 31.5% |
| `plain` | 喜欢女的 / 两个女生 / 妻妻 / 全女 / 不直 | 27 | 7.3% |
| `la` | `#la` `#lala` `#les` `#拉` `#拉圈` `#拉吧` | 25 | 6.7% |
| `split` | `#l #e` / `#l#e` / `#L #E`（被拆开的 le） | **19** | **5.1%** |
| `le` | `#le` `#el`（完整写在一起） | 14 | 3.8% |
| `gl` | `#gl` `#双女主` `#百合` `#纯爱` | 5 | 1.3% |
| `other_abbr` | `#mls` `#lmp` `#detw` `#s1` | 4 | 1.1% |
| `none` | 一个都没有 | 1 | 0.3% |

`#lwl` 是 `wlw` 倒过来写，已经是一个独立的既定标签 —— 它的存在本身
就是规避的证据。`split` 那 19 条是你那个观察的硬数据：`#l #e` 被拆成
两个单字母标签，而拆开之后搜不到。

### 3. 角色词 `tph_tags` — 四层，也是字符串匹配

**这一层只记录作者写了什么，不对外形做任何推断。** 上一版把 `#短发`
和 `#甜妹` 当成"隐含的 T 和 P"计入，那是刻板印象不是观察 —— 作者
两样都没说。发型、穿搭、长相类标签因此不属于角色词，下面任何一层
里都没有它们。

| code | 内容 | 条数 | 占比 |
|---|---|---|---|
| `absent` | 完全没有角色词 | 309 | 83.1% |
| `relational` | 关系称谓，不含 t/p/h 字母 | 26 | 7.0% |
| `compound` | 含 t/p/h 的复合标签 | 25 | 6.7% |
| `direct` | 单字母角色标签 | 12 | 3.2% |
| `pairing` | 描述两个人的配置 | 3 | 0.8% |

- **`direct`** — `#t` `#p` `#h` `#s` `#1` `#0` `#攻` `#受`
- **`compound`** — `#长发t`(17) `#高p`(3) `#姐1`(3) `#短发p`(2) `#萌t` `#姐t` `#短发t` `#普信t` `#妹1`
- **`pairing`** — `#ttl` `#ppl` `#tpl`。**单独一层，不算在 compound
  里**：它们描述的是一段关系里两个人的配置，不是某一个人的身份标签。
  把 `#ppl` 当成一个人的角色词，会把"一对 P 的恋爱"和"某人自称 P"
  放进同一个桶。
- **`relational`** — `#姐姐`(12) `#妹妹`(3) `#御姐` `#年上` `#年下`
  `#恋姐` `#姐感` `#小妈感` `#老婆奴` `#妻妻` `#我的妻子` `#妻子`
  `#小狗` `#小猫`。承担位置关系，但不含任何 t/p/h 字母。**不主张
  它们对应 T、P 或 H 中的任何一个。**

目前只匹配 hashtag，不匹配正文。「跟老婆在一起307天了」说的是同一
件事，但放开到正文会把这个词的所有用法都拖进来；要不要放开，是拿着
语料再定的事，不该是默认。

### 4. `compliance` — 向审核系统说话

372 条里 **7 条**。`#无不良倾向` `#无不良影响` `#正常穿搭无诱导行为`，
以及正文里的「被屏了重发」「我直接就是解封了」「全部都打码了」。

样本太小不能单独做统计，但它是定性材料里最有说服力的那种，而且标记
成本为零。

### 5. `truncated` — 被折叠截断的 caption

372 条里 6 条以 `... 展开` 结尾 —— 屏幕只显示到这里，后面的从来没有
被采集到。它和自己的完整版是两个不同的字符串，所以会在去重后作为
第二行活下来。**标记而不删除**：它是对一条真实帖子的真实观测，它不是
的只是一条完整的 caption。

### 1. 内容类型 `content` — 唯一需要模型的一项

我手工编了 **60 条随机样本**（一个人、一遍、没有第二编码者，所以这是
一个形状，不是一个测量）：

| code | 名称 | 60 条中 | 判断依据 |
|---|---|---|---|
| `feelings` | 情感文案 / 独白 | 15 | 「可是我想念你的时候 你又在哪里」 |
| `flirt` | 向不特定对象喊话 / 搭讪 | 14 | 「你要我好友位不」「多陪陪我好不好？」 |
| `unclear` | 无法判断 | **10** | 「神的三年」「一半一伴」「#wlw 看不懂吗」 |
| `perform` | 手势舞 / 卡点 / 跟拍 | 8 | `#钦钦摇` `#手势舞` `#卡点` |
| `selfie` | 自拍 / 穿搭 / 变装 | 7 | 「#地铁ootd」「看我变装」 |
| `couple` | 情侣日常 | 5 | 「淡淡的稳稳的幸福的两个人 #同居日常 #妻妻」 |
| `explain` | 科普 / 使用说明 | 1 | 「判断淡人喜不喜欢你的使用说明书」 |
| `fiction` | 虚构 / 二创 | 0 | — |
| `community` | 线下 / 场所 | 0 | — |
| `meta` | 账号自述 | 0 | — |

三件事值得先说：

1. **`feelings` + `flirt` 合起来接近一半。** 这两类都不是在描述一段
   具体关系，而是对着镜头说话 —— 一个是对自己，一个是对不特定的人。
   `couple`（真的在讲"我和她"）只有 5/60。
2. **`unclear` 高达 17%。** 多数是一行没有指涉对象的短句。这不是编码
   失败，是这个语料的性质：抖音 caption 经常只是一句歌词。要降低它，
   只能靠画面，不能靠改定义。
3. `fiction` / `community` / `meta` 在这 60 条里一条都没有。它们在全集
   里存在但很稀疏 —— 做回归的时候这三类大概率要合并或丢掉。

## Prompt

```
你在为一项关于中文女同性恋（WLW）内容在抖音上被下架情况的学术研究做
内容编码。你会看到一条抖音帖子的 caption（含话题标签）。只根据这段
文本分类。

规则：
1. 只依据给出的文本。不要推测画面内容，不要补全被截断的句子。
2. 不要考虑这条内容是否"敏感"、会不会被平台处理。该判断与本任务无关，
   且会污染后续分析。
3. 文本不足以判断时用 unclear，不要猜。
4. 标签（#xxx）既是内容线索，也是第 2、3 项的判断依据。标签本身可能
   被拆开写（如 #l #e 是一个被拆开的 le），遇到相邻的单字母标签要按
   拆开的标记处理。

输出严格 JSON，不要有任何其他文字：

{
  "content": "<单选>",
  "wlw_tags": ["<可多选>"],
  "tph_tags": ["<可多选>"],
  "tph_terms": ["<原文中出现的角色词，照抄，可为空>"],
  "compliance": <true 或 false>,
  "confidence": <0 到 1>,
  "evidence": "<决定 content 分类的原文片段，不超过 20 字>"
}

content 可选值：
flirt     向不特定女生搭讪、挑逗、喊话（"你要我好友位不"）
couple    描述与特定伴侣的关系或共同生活（"跟老婆在一起307天了"）
feelings  情感文案、失恋、想念、独白，没有明确对象互动
perform   手势舞、卡点、跟拍热门音频、舞蹈挑战
selfie    自拍、穿搭、变装、妆容、外形展示
fiction   短剧、漫剧、小说、影视解说、二创
community 线下场所、酒吧、社群活动、面基
meta      关于账号本身：涨粉、被限流、重发、解封
unclear   文本不足以判断

wlw_tags 可选值（至少一个；都没有则填 ["none"]）：
wlw         出现 #wlw
lwl         出现 #lwl
la          出现 #la #lala #拉 #拉圈 #拉吧
le          出现 #le #el（完整写在一起的）
split       出现被拆开的字母标签：#l #e、#l#e、#L #E
other_abbr  其他字母缩写：#ppl #ttl #mls #lmp #s1 等
gl          出现 #gl #双女主 #百合
plain       用明文而非缩写表达：喜欢女的、两个女生、老婆、妻妻、全女
none        以上都没有

tph_tags 可选值（至少一个；都没有则填 ["absent"]）：
direct      单字母角色标签：#t #p #h #s #1 #0 #攻 #受
compound    含 t/p/h 的复合标签：#长发t #短发t #短发p #高p #萌t
            #姐t #普信t #姐1 #妹1
pairing     描述两个人的配置而非某一个人：#ttl #ppl #tpl
relational  关系称谓，不含 t/p/h 字母：姐姐、妹妹、御姐、年上、年下、
            恋姐、小妈感、老婆、妻妻、家妻、妻子、小狗、小猫
absent      完全没有角色词

注意：发型、穿搭、长相类标签（#短发 #黑长直 #中性风 #甜妹 #辣妹）
**不是**角色词，不要归入任何一层。不要从外形推断某人是 T 还是 P。

tph_terms：把你判定为 compound 或 alternative 的那些词照原文抄下来，
不要翻译不要归一化。这一项用于之后扩充词表，比分类本身更重要。

compliance：caption 中是否出现向平台表态的声明，例如 #无不良倾向、
#无不良影响、#正常穿搭无诱导行为，或正文提到被屏蔽、重发、解封、打码。

caption：
<<<
{caption}
>>>
```

### 调用约定

- **一条一次调用。** 批量会让模型在同一批内互相参照（"这批大多是情侣，
  这条大概也是"），那是批次效应不是数据。
- **temperature 0。**
- **不传 id、日期、点赞数、是否下架。** 只传 caption 文本。
- 重复 caption 只分类一次（`--captions` 已去重）。
- 模型拒答或输出非 JSON 时记为 `unclear` 并**保留原始返回**，不要重试
  到它肯给答案为止 —— 一条要重试三次才肯分类的 caption 本身就是数据。

---

## 这还不算编码

LLM 输出不能直接当编码结果写进论文。最低限度：

1. 你自己手工编 **50 条**（从 `captions.txt` 随机抽，不看模型结果）。
2. 算 Cohen's κ。`content` 的 κ < 0.6 说明类别定义有问题，要改定义重来，
   不是改数据。`tph_tags` 和 `wlw_tags` 预期会很高（基本是字符串匹配），
   `content` 是真正需要验的那个。
3. 方法部分报告 κ、抽样方式、模型名称与版本、以及 prompt 全文。
4. 分歧的逐条看 —— 分歧集中在哪两类之间，通常直接告诉你这两类该合并
   还是该重新定义。我的预测：`flirt` vs `feelings` 会是主要分歧带。

## 留给你决定的

- `flirt` / `feelings` / `couple` 这三分法是我从语料里读出来的，不是
  你给的。合不合用由你定 —— 如果你的研究问题更关心"是否涉及真实伴侣"，
  也许应该是 `couple` vs `not couple` 的二分，剩下的细分放到 B 轴。
- `tph_tags` 的 (c) alternative 层：严格分析只用 (a)+(b)，还是都用？
  建议两种都跑，在论文里报两个数。
- 图文（note）的文字大多在**图片里**，caption 可能只有一行。建议等
  OCR，现在把 note 的低 confidence 当信号而不是噪音。
- 要不要把 `tph_terms` 收集到的词反馈成一个正则，进 `relevance.py`？
  那样下一轮采集就能直接标，不用再过模型。
