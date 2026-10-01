# 画面编码手册（codebook）v0

配套文件：`video-coding.zh.md`（为什么这样设计）、`video-coding.md`（英文）。
本文件是**执行层**：每个字段的定义、判定规则、边界情况，以及可以
直接用的 prompt 全文。

字段名保持英文，它们会直接变成数据列名。

---

## 零、所有字段通用的三条铁律

**1. 只依据画面里能看到的东西。** 不推测画面外、不补全、不根据
「这种内容通常是什么样」来填。看不见就是看不见。

**2. 看不清一律用 `not_visible` / `null`，不要猜。**
一个诚实的"看不清"是数据；一个蒙对一半的猜测是噪声，而且它会和
真实观测混在一起，之后再也分不开。宁可空着。

**3. 不判断这个人是谁、是什么身份、什么取向。** 只记录头发多长、
衣服什么版型、手在哪里。身份是研究者在分析阶段用这些特征搭出来的，
不是模型给的。

---

## A. 可编码性（gate）

这一组决定后面所有字段是否有意义。

### `people_visible` : int

**定义**：整条内容中，**任一时刻**画面里出现过的、可辨认为人的
个体数量上限。

**规则**
- 以出现人数最多的那一帧为准，不是平均。
- 镜子里的倒影、照片里的人、海报上的人**算**，但在 `notes` 里写明。
- 只有手、只有脚、只有背影 —— **算 1 个人**。
- 完全没有人：`0`。

**不算**：卡通形象、虚拟人物、动物。

### `primary_subject` : "single" | "pair" | "group" | "none"

**定义**：这条内容在呈现谁。

**规则**
- `single`：一个人占据绝大部分镜头时间 / 画面。
- `pair`：两个人大致同等地被呈现（并排、互动、交替出镜）。
- `group`：三人及以上，没有明确主角。
- `none`：没有人，或人只是背景（街拍里路过的行人）。

**边界**：一个人出镜、另一个人只有手或只有声音 → `single`。

### `face_visible` : bool

**定义**：是否有至少一帧能看清一张脸的大部分（眼、鼻、嘴）。

**规则**
- 戴口罩、马赛克、打码、只有侧脸轮廓 → `false`。
- 戴墨镜但其余清晰 → `true`。

### `coding_possible` : bool

**定义**：画面里是否有足够的人物信息来填 B、C 两组。

**规则**：以下任一成立即为 `false`：
- 没有人（`people_visible = 0`）
- 纯文字卡、纯截图、纯聊天记录
- 只有风景、食物、宠物、物品
- 人在画面里但过小 / 过暗 / 过糊，看不出发型和衣着

**`false` 时，B 组和 C 组全部填 `null`，D 也填 `null`。**
F 组（屏幕文字）照常填 —— 一张纯文字卡没有人可编码，但它的文字
正是它的全部内容。

---

## B. 外形（对 primary subject；`pair` 时第二人另开一组）

### `hair_length` : 枚举

**定义**：头发在**最长处**的长度，以身体部位为锚点。

| 取值 | 判定 |
|---|---|
| `shaved` | 光头或寸头，看不出发型结构 |
| `cropped_above_ear` | 最长处不过耳垂 |
| `ear_to_jaw` | 过耳垂但不过下颌线 |
| `jaw_to_shoulder` | 过下颌线但不过肩线 |
| `below_shoulder` | 过肩 |
| `not_visible` | 戴帽子、戴头盔、只有背影且被遮挡、光线不足 |

**规则**
- 以**最长的那一缕**为准，不是平均。鲻鱼头按颈后那一缕算，所以
  鲻鱼头常常是 `ear_to_jaw` 或更长，同时 `hair_mullet = true`。
- 扎起来的头发：按**放下来的估计长度**判，判不出就 `not_visible`。
- 假发、接发照常计入，这是呈现，不是生理事实。

**不算**：发色、发质、是否卷曲 —— 那是别的字段或者不记录。

### `hair_mullet` : bool

**定义**：鲻鱼头。顶部与两侧较短，**颈后留明显长出一截**，长短
之间有清晰的层次界线。

**规则**
- 必须同时满足"上短/侧短"和"后长"。
- 只是后面稍长的层次感 → `false`。
- 看不到后脑 → `false`（不是 null；这一项是"是否观察到"）。

**为什么单列**：这是你语料里反复出现的、有文化标记性的具体发型
（`#鲻鱼头` 在 caption 里就出现过），而且它和"短发"不是一回事。

### `hair_undercut` : bool

**定义**：两侧或后颈被剃/推到明显短于顶部，形成可见的分界。

**规则**：必须看得到那条分界线。仅仅"两边比较短"不算。

### `hair_dyed` : bool

**定义**：非自然生长的发色。

**规则**
- 明显的红、蓝、绿、紫、粉、银白、挑染 → `true`。
- 棕色、栗色、浅褐 → `false`（这些可能是自然发色，判不了）。
- 光线造成的偏色不算。拿不准 → `false`。

### `makeup_visible` : "none" | "light" | "heavy" | "not_visible"

**定义**：可见的妆容程度。

| 取值 | 判定 |
|---|---|
| `none` | 看不出化妆痕迹 |
| `light` | 能看出但不醒目：淡唇色、修过的眉、薄底妆 |
| `heavy` | 醒目：明显眼妆 / 眼线 / 睫毛、明显唇色、修容、亮片 |
| `not_visible` | 脸看不清、戴口罩、距离太远 |

**规则**：滤镜不等于化妆。全脸美颜但看不出具体妆容 → `none`，
并在 `notes` 写 "heavy filter"。

### `nails` : "short_bare" | "long_or_decorated" | "not_visible"

**定义**：指甲长度与装饰。

**规则**
- `long_or_decorated`：明显长于指尖，或有颜色 / 美甲 / 贴片。
- `short_bare`：短且无色。
- 手没出现、太糊 → `not_visible`。**这一项多数情况会是
  `not_visible`，这是正常的。**

### `upper_garment` : "fitted" | "loose_or_boxy" | "not_visible"

**定义**：上半身衣着是否贴合身体轮廓。

**规则**
- `fitted`：能看出腰线 / 身体曲线，紧身、修身、短款。
- `loose_or_boxy`：宽松、廓形、oversize，看不出身体轮廓。
- 外套敞开时按**里层**判。
- 只有大头照 → `not_visible`。

**不算**：衣服好不好看、是不是"男性化" —— 只判版型。

### `menswear_items` : 数组

**定义**：画面中出现的、传统上属于男装的具体单品。**只记录看到的
物件，不做风格判断。**

可选值：`necktie`（领带）、`suit_jacket`（西装外套）、
`oversized_shirt`（oversize 衬衫）、`sports_jersey`（球衣）、
`cap`（鸭舌帽 / 棒球帽）、`chain`（链条项链）、`none`。

**规则**
- 可多选。一个都没有填 `["none"]`。
- 领结、领带夹按 `necktie`。
- 毛线帽、渔夫帽**不算** `cap`（`cap` 专指有帽檐的运动帽）。
- 细项链、吊坠不算 `chain`（`chain` 指粗链条）。

### `chest_presentation` : "flattened_or_bound" | "unmodified" | "not_visible"

> **默认关闭。** 这一项针对的是没有同意被编码的人的身体，而且
> 「是否束胸」是一个对当事人高度敏感的判断。它留在手册里是因为
> 束胸是真实存在、且确实被审核盯上的呈现方式；但**除非你明确说要，
> 否则这一项一律填 `not_visible`，不要判。**

若启用：
- `flattened_or_bound`：能看到束胸衣边缘，或胸部轮廓被明显压平且
  与衣物版型不符。
- 任何不确定 → `not_visible`。

### `skin_exposure` : "covered" | "arms_or_shoulders" | "midriff_or_legs" | "not_visible"

**定义**：可见的皮肤暴露程度，取**最高**的那一档。

**规则**
- `covered`：长袖长裤，或只拍到头肩。
- `arms_or_shoulders`：短袖、背心、露肩。
- `midriff_or_legs`：露腰、露脐、短裤、短裙、泳装。
- 只有大头照 → `covered`，不是 `not_visible`（头肩本来就不暴露）。

**为什么要记**：皮肤暴露是审核的已知触发点之一，而且它和性别呈现
是两个独立的维度 —— 不记录就会被混进"呈现距离"里去。

---

## C. 神态动作

全部是**行为**，不是形容词。每一项问的是"有没有发生"，不是
"看起来怎么样"。

### `stance_wide` : bool
站立时双脚分开**明显超过肩宽**。坐着、半身、没有站立画面 → `false`。

### `hands_in_pockets` : bool
至少一只手插进裤袋或外套口袋，并保持了可观察的一段时间。

### `arms_crossed` : bool
双臂在胸前交叉抱起。

### `gaze_direct` : bool
**定义**：主要对象在画面中**直视镜头**（而非看向别处、低头、
闭眼）。
**规则**：只要有明确的一段直视即可。偶尔扫过不算。

### `head_tilt_or_chin_tuck` : bool
**定义**：头部明显向一侧倾斜，或下巴向内收、略低头向上看镜头 ——
短视频里常见的"可爱"取角。
**规则**：必须是**保持住的姿势**，不是动作中途的一帧。

### `peace_sign_or_heart` : bool
比耶（V 字手势）、比心（手指心 / 双手心）。

### `hand_gesture_dance` : bool
**定义**：手势舞 —— 只动手和手臂，身体基本不位移，通常坐着或
站着不动。
**规则**：和 `full_body_dance` 可以同时为 true（有些视频两段都有）。

### `full_body_dance` : bool
**定义**：涉及躯干、腿部、位移的舞蹈。

### `lip_sync` : bool
**定义**：对口型 —— 嘴型跟随背景音乐 / 台词，但不是真唱。
**规则**：判不出是真唱还是对口型 → `false`。

> **为什么没有"男性化神态"这一项**：那是形容词，不是观察。
> 「站姿宽 + 手插口袋 + 不比心 + 直视镜头」这样一个组合索引，
> 应该在 R 里按一条写进论文、读者看得见的规则搭出来 —— 而不是
> 藏在 prompt 里，既看不见也改不了。

---

## D. 唯一的判断项

### `subject_appears_female` : true | false | "unclear"

**定义**：主要对象是否呈现为女性。

> 这一项**是推断，不是观察**，而且写在这里只有一个用途：决定 D 的
> 参照系是否适用。它不进入任何分析模型。

**规则**
- 判不出 → `"unclear"`，D 填 `null`。
- `false`（呈现为男性）→ D 仍填 `null`，并在 `notes` 里写明。
  这批语料是女性内容，男性出现时**标记并单独处理**，不要套用女性
  的参照系。

### `presentation_distance` : 1 | 2 | 3 | 4 | 5 | null

**定义**：主要对象的呈现方式，离**中国主流短视频中女性被常规呈现
的样子**有多远。

> **参照系是平台主流，不是女同亚文化，也不是编码者自己对性别的
> 感觉。** 这一点是整个字段的全部意义所在。

| 取值 | 锚点 |
|---|---|
| 1 | 常规女性化：长发（过肩）、可见妆容、修身衣着、柔和造型，几乎没有偏离 |
| 2 | 基本常规，有**一到两处**偏离（例如短发但其余常规；或无妆但衣着修身） |
| 3 | 混合，或没有明确方向：偏离和常规元素大致相当，说不上偏向哪边 |
| 4 | **三处及以上**男性化偏离（例如同时：耳上短发 + 宽松男装 + 无可见妆容） |
| 5 | 以主流标准看，整体呈现为强烈男性化：发型、衣着、配饰、姿态方向一致 |
| null | `coding_possible = false`，或 `subject_appears_female` 不为 true，或可见信息不足 |

**判定程序**（按顺序，减少随意性）
1. 先把 B 组已填好的字段列出来。
2. 数一数有几项偏离主流女性常规：短于下颌的头发、无可见妆容、
   宽松版型、男装单品、短素指甲。
3. 0 项 → 1；1–2 项 → 2；若偏离项与常规项相当 → 3；
   3 项以上 → 4；所有可见维度方向一致且强烈 → 5。
4. 若第 3 步的计数结果和你的整体印象冲突，**以计数为准**，并在
   `notes` 里写一句为什么。

**必须报告 κ。** κ < 0.6 说明锚点没起作用 —— **改锚点，不改数据。**

---

## E. 关系内容

### `two_women_together` : bool
**定义**：画面中同时出现两名呈现为女性的人。
**规则**：必须**同框**。交替出镜但从不同框 → `false`，在 `notes`
写明。

### `physical_affection` : 枚举
取**最高**的那一档。

| 取值 | 判定 |
|---|---|
| `none` | 无身体接触 |
| `proximity` | 明显贴近但不接触（贴脸合影、依偎而不触碰） |
| `hand_holding` | 牵手、挽手、手搭手 |
| `embrace` | 拥抱、搂肩、搂腰、靠在对方身上 |
| `kiss` | 亲吻（包括吻脸颊、吻额头） |

**规则**：只有一个人时填 `none`。

### `presented_as_couple` : bool
**定义**：这条内容是否把两个人呈现为一对。

**规则**：以下任一成立即为 `true`：
- 画面内文字写明（"三周年"、"我老婆"、"在一起 307 天"）
- 情侣装、成对的戒指 / 饰品
- 婚礼、同居、约会场景
- 构图明确是"我们两个"（合影、对视、十指相扣特写）

**不算**：仅仅是两个女性同框（闺蜜合影、舞蹈搭档）。

---

## F. 帖子的自述（证词，不是推断）

从**屏幕上的文字**读取：贴纸、字幕、画面内的文案、聊天记录截图，
以及图文的**图内文字（先 OCR）**。

> 这一组**绝不能影响 B、C、D**。屏幕上写着 `#长发T` 不改变你对
> 这个人头发长度的观察。这是防止循环论证从另一头合上的那道墙。

### `onscreen_tph_terms` : 字符串数组
出现的角色词，**逐字抄录，不翻译不归一化**。
例：`["长发t", "高p", "姐1", "攻", "年下"]`

### `onscreen_wlw_terms` : 字符串数组
出现的女同社群词。例：`["wlw", "lwl", "les", "拉", "女同", "l", "e"]`
**拆开写的字母标签要分别记录**：屏幕上是 `#l #e` 就记
`["l", "e"]`，不要合成 `"le"`。

### `onscreen_relationship_terms` : 字符串数组
例：`["老婆", "女朋友", "姐姐", "妹妹", "家妻", "小狗"]`

### `onscreen_moderation_terms` : 字符串数组
例：`["限流", "被屏", "重发", "解封", "无不良引导", "仅女生可见"]`

### `onscreen_contact` : bool
屏幕上出现 QQ 号、微信号、Telegram 账号，或"加我"类引导。

---

## G. 元数据

### `confidence` : 0.0–1.0
对**整条编码**的信心。画面糊、时长极短、信息少 → 低。

### `notes` : string
一行以内，**只在确实异常时写**。例：
"heavy filter, makeup unclear"、"second person only in reflection"、
"subject appears male"。
正常情况填空字符串。

---

## Prompt 全文

```
你在为一项关于中文女同性恋（WLW）内容在抖音上被审核下架的学术研究
做画面编码。你会看到一条抖音帖子的内容（视频，或图文的若干张图片）。

三条铁律：
1. 只依据画面里能看到的东西。不推测画面外，不补全，不根据"这类
   内容通常是什么样"来填。
2. 看不清一律用 not_visible 或 null，不要猜。诚实的"看不清"是数据，
   蒙对一半的猜测是噪声。
3. 不要判断这个人是谁、是什么身份、什么性取向。只记录可观察的
   特征：头发多长、衣服什么版型、手在哪里。

另外：不要考虑这条内容是否"敏感"、会不会被平台处理。该判断与本任务
无关，且会污染后续分析。

输出严格 JSON，不要有任何其他文字：

{
  "people_visible": <整数>,
  "primary_subject": "single" | "pair" | "group" | "none",
  "face_visible": <true/false>,
  "coding_possible": <true/false>,

  "subject": {
    "hair_length": "shaved" | "cropped_above_ear" | "ear_to_jaw"
                 | "jaw_to_shoulder" | "below_shoulder" | "not_visible",
    "hair_mullet": <true/false>,
    "hair_undercut": <true/false>,
    "hair_dyed": <true/false>,
    "makeup_visible": "none" | "light" | "heavy" | "not_visible",
    "nails": "short_bare" | "long_or_decorated" | "not_visible",
    "upper_garment": "fitted" | "loose_or_boxy" | "not_visible",
    "menswear_items": [...],
    "chest_presentation": "not_visible",
    "skin_exposure": "covered" | "arms_or_shoulders"
                   | "midriff_or_legs" | "not_visible",
    "stance_wide": <true/false>,
    "hands_in_pockets": <true/false>,
    "arms_crossed": <true/false>,
    "gaze_direct": <true/false>,
    "head_tilt_or_chin_tuck": <true/false>,
    "peace_sign_or_heart": <true/false>,
    "hand_gesture_dance": <true/false>,
    "full_body_dance": <true/false>,
    "lip_sync": <true/false>
  },
  "second_person": <同上结构，primary_subject 为 pair 时填，否则 null>,

  "subject_appears_female": true | false | "unclear",
  "presentation_distance": 1 | 2 | 3 | 4 | 5 | null,

  "two_women_together": <true/false>,
  "physical_affection": "none" | "proximity" | "hand_holding"
                      | "embrace" | "kiss",
  "presented_as_couple": <true/false>,

  "onscreen_tph_terms": [...],
  "onscreen_wlw_terms": [...],
  "onscreen_relationship_terms": [...],
  "onscreen_moderation_terms": [...],
  "onscreen_contact": <true/false>,

  "confidence": <0 到 1 的小数>,
  "notes": "<一行，无异常则空字符串>"
}

字段定义：

people_visible：任一时刻画面中出现过的人数上限，以人最多的那一帧
  为准。镜子倒影、照片里的人算，并在 notes 写明。只有手/脚/背影
  算 1 个人。卡通、虚拟人物、动物不算。

primary_subject：single = 一人占据绝大部分镜头；pair = 两人大致同等
  被呈现；group = 三人以上无明确主角；none = 无人或人仅为背景。
  一人出镜、另一人只有手或只有声音，算 single。

face_visible：是否有至少一帧能看清一张脸的大部分（眼鼻嘴）。口罩、
  马赛克、只有侧脸轮廓算 false；戴墨镜但其余清晰算 true。

coding_possible：以下任一成立即为 false —— 没有人；纯文字卡/截图/
  聊天记录；只有风景、食物、宠物、物品；人太小太暗太糊看不出发型
  和衣着。为 false 时，subject、second_person、
  presentation_distance 全部填 null，但屏幕文字字段照常填。

hair_length：以最长的一缕为准，不是平均。
  shaved = 光头或寸头，看不出发型结构
  cropped_above_ear = 最长处不过耳垂
  ear_to_jaw = 过耳垂但不过下颌线
  jaw_to_shoulder = 过下颌线但不过肩线
  below_shoulder = 过肩
  not_visible = 戴帽/被遮挡/光线不足
  头发扎起时按放下来的估计长度判，判不出填 not_visible。
  假发、接发照常计入。

hair_mullet：鲻鱼头 —— 顶部与两侧短，颈后留明显长出一截，长短之间
  有清晰层次界线。必须同时满足"上短侧短"和"后长"。只是后面稍长的
  层次感不算。看不到后脑填 false。

hair_undercut：两侧或后颈被剃/推到明显短于顶部，有可见分界线。
  仅"两边比较短"不算。

hair_dyed：非自然生长的发色。红蓝绿紫粉银白挑染算 true；棕色栗色
  浅褐算 false；光线偏色不算；拿不准填 false。

makeup_visible：none = 看不出化妆痕迹；light = 能看出但不醒目
  （淡唇色、修眉、薄底妆）；heavy = 醒目（明显眼妆眼线睫毛、明显
  唇色、修容、亮片）；not_visible = 脸看不清/口罩/距离远。
  滤镜不等于化妆：全脸美颜但看不出具体妆容填 none，并在 notes 写
  "heavy filter"。

nails：long_or_decorated = 明显长于指尖，或有颜色/美甲/贴片；
  short_bare = 短且无色；手没出现或太糊 = not_visible。
  这一项多数情况会是 not_visible，属正常。

upper_garment：fitted = 能看出腰线或身体曲线（紧身、修身、短款）；
  loose_or_boxy = 宽松、廓形、oversize，看不出身体轮廓；
  not_visible = 只有大头照。外套敞开时按里层判。只判版型，不判
  好不好看、是否"男性化"。

menswear_items：只记录看到的具体物件，可多选，没有填 ["none"]。
  necktie（含领结、领带夹）、suit_jacket、oversized_shirt、
  sports_jersey、cap（专指有帽檐的运动帽，毛线帽渔夫帽不算）、
  chain（粗链条，细项链吊坠不算）。

chest_presentation：本轮一律填 "not_visible"，不要判断。

skin_exposure：取最高档。covered = 长袖长裤，或只拍到头肩；
  arms_or_shoulders = 短袖、背心、露肩；
  midriff_or_legs = 露腰、露脐、短裤、短裙、泳装。
  只有大头照填 covered。

stance_wide：站立时双脚分开明显超过肩宽。坐着或无站立画面填 false。
hands_in_pockets：至少一只手插进裤袋或外套口袋并保持一段时间。
arms_crossed：双臂在胸前交叉抱起。
gaze_direct：有明确的一段直视镜头。偶尔扫过不算。
head_tilt_or_chin_tuck：头明显向一侧倾斜，或下巴内收略低头向上看
  镜头。必须是保持住的姿势，不是动作中途的一帧。
peace_sign_or_heart：比耶（V 字）、比心（手指心或双手心）。
hand_gesture_dance：只动手和手臂，身体基本不位移。
full_body_dance：涉及躯干、腿部、位移的舞蹈。
  两者可同时为 true。
lip_sync：嘴型跟随音乐或台词但不是真唱。判不出填 false。

subject_appears_female：主要对象是否呈现为女性。判不出填 "unclear"。
  这一项只用来决定下一项是否适用，不进入任何分析。

presentation_distance：主要对象的呈现方式，离【中国主流短视频中
  女性被常规呈现的样子】有多远。参照系是平台主流，不是女同亚文化，
  也不是你自己对性别的感觉。
  判定按以下程序：
  (1) 数一数有几项偏离主流女性常规：头发短于下颌、无可见妆容、
      宽松版型、出现男装单品、短素指甲。
  (2) 0 项 → 1；1-2 项 → 2；偏离项与常规项相当 → 3；
      3 项以上 → 4；所有可见维度方向一致且强烈 → 5。
  (3) 若计数结果与整体印象冲突，以计数为准，并在 notes 写明。
  coding_possible 为 false、subject_appears_female 不为 true、
  或信息不足时，填 null。
  锚点：
  1 = 长发过肩、可见妆容、修身衣着、柔和造型，几乎没有偏离
  2 = 基本常规，一到两处偏离
  3 = 混合，或没有明确方向
  4 = 三处及以上男性化偏离
  5 = 发型、衣着、配饰、姿态方向一致的强烈男性化呈现

two_women_together：两名呈现为女性的人必须同框。交替出镜但从不同框
  填 false 并在 notes 写明。

physical_affection：取最高档。none = 无接触；proximity = 明显贴近
  但不接触；hand_holding = 牵手挽手；embrace = 拥抱搂肩搂腰依靠；
  kiss = 亲吻（含吻脸颊额头）。只有一个人时填 none。

presented_as_couple：以下任一成立即为 true —— 画面内文字写明
  （三周年、我老婆、在一起 N 天）；情侣装或成对饰品；婚礼同居约会
  场景；构图明确是"我们两个"。仅仅两个女性同框（闺蜜合影、舞蹈
  搭档）不算。

onscreen_* 四组：从屏幕文字、贴纸、字幕、画面内文案、聊天记录截图
  中逐字抄录，不翻译不归一化。拆开写的字母标签分别记录：屏幕上是
  #l #e 就记 ["l", "e"]，不要合成 "le"。
  这四组绝不能影响上面任何一个关于外形或姿态的字段。

onscreen_contact：屏幕上出现 QQ 号、微信号、Telegram 账号，或
  "加我"类引导。

confidence：对整条编码的信心。画面糊、时长极短、信息少则低。

notes：一行以内，只在确实异常时写，正常填空字符串。
```

---

## 跑之前还要做的

1. **图文先 OCR。** 图文的文字在图片里，不先 OCR，F 组基本是空的。
2. **先抽 30 条校准。** 看字段是否稳定、`not_visible` 的比例是否
   合理、JSON 是否每次都合法。
3. **手工编 50 条算 κ。** B、C 两组应该很高；`presentation_distance`
   是必须报告的那一个。
4. **限定在"下架前已存档"的子集**做预测分析，否则又是幸存者偏差。
   这个子集多大，跑之前先算。
5. **六个预测变量，看结果之前定死。**
