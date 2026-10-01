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

**3. 不判断这个人是谁、是什么身份、什么性别、什么取向。** 只记录
头发多长、衣服什么版型、手在哪里。身份是研究者在分析阶段用这些特征
搭出来的，不是模型给的。

**4. 多张图时，分两类处理 —— 这是最容易弄错的一条。**

一条图文是一叠卡片，同一个人可能换了衣服、做了不同动作。字段分两种，
规则相反：

- **状态类**（`hair_length`、`makeup_visible`、`upper_garment`、
  `skin_exposure`）问的是"**大体上是什么样**"。取**出现次数最多**的
  取值；没有多数取第一张图；字段自己另有规定的（如 `skin_exposure`
  "取最高档"）以字段的规定为准。
- **发生类**（`menswear_items`、`hair_mullet`、`hair_undercut`、
  `hair_dyed`，以及 C 组**全部**行为字段）问的是"**有没有出现过**"。
  **在任意一张图里出现过，就填 true / 记进数组。一次也算。**

> 上一版只写了"按多数"，结果是：领带只在二十六张里的一张出现，就被
> 抹成 `["none"]`；比耶只在一张出现，就被抹成 false。**一条帖子里
> 系过领带，就是系过领带。** 把发生类字段按多数取值，等于要求一个
> 动作在半数以上的卡片里重复出现才承认它发生过，那不是观察。

**5. 跨图默认是同一个人**，除非画面明显是不同的人。判不出就按第一张
图里的人编，并在 `notes` 写明。

**5b. 背景里的路人不是这条帖子在呈现的人。** 街上走过的行人、操场上
的人群、餐厅里的其他客人、被打码的背景人物 —— 这些是场景，和店招
菜单是一类东西。`people_visible`、`primary_subject`、
`two_people_together` 三个字段**只数这条帖子在呈现的人**。
一张夜里操场的照片，背景有几十个人，主体是一个人 —— 填 `"1"`，不是
`"6+"`。

**6. 环境里的字不算这条帖子说的话。** 店招、菜单、横幅、路牌、别人
手机屏幕上的字 —— 这些是场景，不是作者的表达。F 组只收**作者加上去
的文字**：贴纸、字幕、画在图上的文案、以及发帖人自己写在画面里的话。
拿不准就不收，在 `notes` 里提一句。

**7. 这些是静态图片，不是视频。** 凡是需要看到动作过程才能判断的
字段（`hand_gesture_dance`、`full_body_dance`、`lip_sync`），在图文
上一律填 `false`，除非画面本身就是一个明确的舞蹈姿势。

---

## A. 可编码性（gate）

这一组决定后面所有字段是否有意义。

### `people_visible` : "0" | "1" | "2" | "3-5" | "6+"

**定义**：画面里同时出现过的人数，分档。

**为什么是分档不是数字**：原来要求数出精确人数，遇到一张一百多人的
毕业合影，模型给了 140 —— 那个数反映的是"这条帖子里有没有一张大合
影"，和这条帖子在呈现谁毫无关系，而且它只是个估数。分档把这个假精度
去掉了。

**规则**
- 以人最多的那一张图为准。
- **只数这条帖子在呈现的人**（铁律 5b）。背景路人、人群、其他顾客
  一律不算，即使脸很清楚。
- 镜子倒影、照片里的人、海报上的人**算**，并在 `notes` 写明。
- 只有手、只有脚、只有背影 —— 算 1 个人。
- 被打码/模糊处理的人：**是主体就算，是背景就不算。**

**不算**：卡通形象、虚拟人物、动物。

### `primary_subject` : "single" | "pair" | "group" | "none"

**定义**：这条内容在呈现谁。

**规则**
- `single`：一个人占据绝大部分镜头时间 / 画面。
- `pair`：两个人大致同等地被呈现（并排、互动、交替出镜）。
- `group`：三人及以上，没有明确主角。
- `none`：没有人，或人只是背景（街拍里路过的行人）。

**边界**：一个人出镜、另一个人只有手 → `single`。

### 谁进 `subject`，谁进 `second_person`

原来没写，而 D 组只看 `subject`，所以这个顺序直接决定了 D 有没有值 ——
不能留给随意。

- `single`：那个人进 `subject`，`second_person` 填 `null`。
- `pair`：**出现在更多张图里的那位进 `subject`**；张数相同时，**第一张
  图里靠左的那位**进 `subject`。另一位进 `second_person`。
- `group`：**出现在最多张图里的那位进 `subject`**。如果没有任何人反复
  出现（例如一组互不相关的合影），`subject` 和 `second_person` 都填
  `null`，`presentation_distance` 也填 `null`，并在 `notes` 写明。
- `none`：两者都 `null`。

### `face_visible` : bool

**定义**：是否有至少一帧能看清一张脸的大部分（眼、鼻、嘴）。

**规则**
- 判据是**眼、鼻、嘴三者都能看见**。四分之三侧面通常满足，正侧面
  （只看得到一只眼）不满足。
- 戴口罩、马赛克、打码 → `false`。
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

**规则**
- 滤镜不等于化妆。全脸美颜但看不出具体妆容 → `none`，并在 `notes`
  写 "heavy filter"。
- **修图重到分不清是妆还是磨皮/液化时，填 `not_visible`**，不要填
  `heavy`。"看不清"是数据，"大概是浓妆"是噪声。
- **部分能分清的，按能分清的那部分填。** 整张脸磨得很平，但眼线的
  轮廓清楚 —— 那是修图造不出来的，填 `heavy` 或 `light`，不要因为
  别的部分看不清就整项作废。`not_visible` 留给"什么都读不出来"。

### `upper_garment` : "fitted" | "loose_or_boxy" | "not_visible"

**定义**：上半身衣着是否贴合身体轮廓。

**规则**
- `fitted`：能看出腰线 / 身体曲线，紧身、修身、短款。
- `loose_or_boxy`：宽松、廓形、oversize，看不出身体轮廓。
- 外套敞开时按**里层**判。
- 只有大头照 → `not_visible`。

**多张图衣着不同时**：按通用铁律第 4 条，取出现最多的那一种；没有
多数取第一张。

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
**定义**：**朝向镜头**的那个姿势 —— 头向一侧倾斜、或下巴内收略低头
**向上看镜头**。短视频里常见的"可爱"取角。

**规则**
- 必须是朝向镜头的。**低头看别处、侧身望向画面外，都不算** —— 那是
  另一种姿态，不是这个字段要抓的东西。
- 判不出朝向就填 `false`。

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

### `presentation_distance` : 1 | 2 | 3 | 4 | 5 | null

**定义**：主要对象的呈现方式，离**中国主流短视频中"常规女性化"的
那一套**有多远。

> **参照系是平台主流的那一个固定端点，不是女同亚文化，也不是编码者
> 自己对性别的感觉。**
>
> 上一版在这里设了一道 `subject_appears_female` 的门：判不出性别就
> 把 D 填 null。试跑第一轮就证明那是错的 —— 一位短发的人，模型判不出
> 性别呈现，D 直接变空。**最该被这个量表测到的人，恰恰最容易被这道门
> 挡在外面。**
>
> 现在没有门。量表不问"这个女性有多男性化"，只问"**离常规女性化那一端
> 有多远**"。这是一个对任何人都适用的距离，不需要先判断对方是谁。
>
> **抽样框已经做掉了性别这件事。** 这批语料是按女同社群标签采集并过滤
> 过的，画面里出现男性的情况很少；一个"看不出是男是女"的人，在这个
> 语料里几乎总是偏中性/T 的呈现 —— 也就是说，**那个"看不出"本身就是
> 这个量表要测的偏离**。所以不设 male 这一类，也不要求编码者去判断
> 性别。

**判定程序**（按顺序，不要凭印象）

1. 把 B 组已填好的字段列出来。
2. 数四项，每项符合记一分：
   - 头发短于下颌线（`shaved` / `cropped_above_ear` / `ear_to_jaw`）
   - 无可见妆容（`makeup_visible` 为 `none`）
   - 上衣宽松廓形（`upper_garment` 为 `loose_or_boxy`）
   - 出现**明确的男装单品**：`necktie`、`suit_jacket`、`sports_jersey`
     中的任意一个。**`cap` 和 `chain` 不计分** —— 鸭舌帽和链条在平台
     主流女性穿搭里本来就很常见，拿它们当"男装"计分，等于又一次把
     风格读成性别。两者照常记录在 `menswear_items` 里，只是不进 D 的
     计数。
3. 按分数填：**0 分 → 1，1 分 → 2，2 分 → 3，3 分 → 4，4 分 → 5。**
4. `not_visible` 的项不计分，但如果四项里有两项以上是 `not_visible`，
   填 `null` —— 看不见的东西不能算作"没有偏离"。

**`null` 只给"看不见"，不给"说不清"。**
画面模糊、戴帽子、只有背影 —— 这些是看不见，填 `null`。
"看得见，但说不清这个人是男是女" —— **这不是 null**。性别判断不参与
这个量表的任何一步；中性化的呈现就是偏离本身，照常按四项计分。
把"分不清性别"当成"判不了"，正是上一版那道门的毛病换了个地方复发。

**和前两版的区别**：第一版有"3 项以上 → 4"和"偏离与常规相当 → 3"
两条同时成立的规则，编码者只能自己选；第二版改成一一对应的映射，但
"按多数"把只出现过一次的领带抹掉了，D 跟着从 5 掉到 4。现在计分用的
是**发生类**口径（铁律 4）：出现过就算。

**`notes` 里写冲突**：如果计数结果和你的整体印象不一致，**以计数为准**，
并在 `notes` 写一句差在哪。那句话本身就是数据 —— 它告诉我们这个量表
在哪里和人的直觉分家。

**必须报告 κ。** κ < 0.6 说明锚点没起作用 —— **改锚点，不改数据。**

## E. 关系内容

### `two_people_together` : bool

**定义**：画面中**同时出现两个人**。

> 原来这一项问的是"两名**女性**"，那是一个错误。一对情侣在接吻，
> 因为其中短发那位的性别"判不出"，整条记录就被填成 `false` ——
> **越偏男性化呈现的人，越容易被这条规则从数据里剔出去，而那正是
> 本研究最关心的那批人。** 现在只问有没有两个人，性别不进入判断。
> 这批语料本来就是按女同社群标签采集的，是不是女性由抽样框保证，
> 不该由画面推断。

**规则**
- 必须**同框**。交替出镜但从不同框 → `false`，在 `notes` 写明。
- **背景路人不算**（铁律 5b）。一个人在人群前自拍，填 `false`。
  这一条和 `people_visible` 用同一个口径 —— 上一版两边口径不一致，
  同一条记录里出现过"有 2 人"和"没有两人同框"并存。

### `physical_affection` : 枚举
取**最高**的那一档。

| 取值 | 判定 |
|---|---|
| `none` | 无身体接触 |
| `proximity` | 明显贴近但不接触（贴脸合影、依偎而不触碰） |
| `hand_holding` | 牵手、挽手、手搭手 |
| `embrace` | 拥抱、搂肩、搂腰、靠在对方身上 |
| `kiss` | 亲吻**身体任何部位**：嘴、脸颊、额头、手背、头发 |

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

### `apparent_minors` : "none" | "possible" | "clear"

**定义**：画面里是否可能有未成年人。

> 试跑四条里有两条是校园场景：校服、军训、教室、横幅。这不影响编码
> 本身，但它决定这些帖子**能不能进访谈框、能不能出现在论文的任何
> 一张配图里**。
>
> **这一项只用于保护和排除，永远不进入任何预测模型。** 把"是不是
> 未成年"当成下架的预测变量，既不是你的研究问题，也不该是任何人的。

**规则**
- `clear`：有明确的校服、校徽、小学/初中教室、"XX 中学"字样等。
- `possible`：场景像校园或画面中人看起来很年轻，但没有确证。
- `none`：没有任何这类线索。
- 拿不准填 `possible`，不要填 `none`。**这一项宁可过报。**

## F. 帖子的自述（证词，不是推断）

从**作者加上去的文字**读取：贴纸、字幕、画在图上的文案、聊天记录
截图，以及图文的图内文字。

**环境里的字不收**（通用铁律第 6 条）：店招、菜单、横幅、路牌、别人
屏幕上的字。试跑第 3 条里有一块酒吧菜单板写着"我第1次对一个人这样"，
那是场景不是自述 —— 收进来会把店家的文案记成作者的话。

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

**emoji 当名字用的，也照抄。** 作者用 `💅`、`🐷`、`🍙` 之类代指一个
人（"给 💅 的惊喜"），那就是一个称呼，逐字记进来。只记录被当作称呼
使用的，句尾装饰性的 emoji 不记。

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
做画面编码。你会看到一条抖音帖子的图片（一条帖子可能有一张到二十几张）。

七条铁律：
1. 只依据画面里能看到的东西。不推测画面外，不补全，不根据"这类内容
   通常是什么样"来填。
2. 看不清一律用 not_visible 或 null，不要猜。诚实的"看不清"是数据，
   蒙对一半的猜测是噪声。
3. 不要判断这个人是谁、是什么身份、什么性别、什么性取向。只记录可
   观察的特征：头发多长、衣服什么版型、手在哪里。如果你无法判断画面
   中人的性别，这不影响任何字段 —— 本编码不需要这个判断。
4. 多张图时，字段分两类，规则相反：
   状态类（hair_length、makeup_visible、upper_garment、skin_exposure）
   问"大体上是什么样"——取出现次数最多的取值，没有多数取第一张图，
   字段自己另有规定的（如 skin_exposure 取最高档）以字段规定为准。
   发生类（menswear_items、hair_mullet、hair_undercut、hair_dyed，
   以及所有 C 组行为字段：stance_wide、hands_in_pockets、arms_crossed、
   gaze_direct、head_tilt_or_chin_tuck、peace_sign_or_heart）
   问"有没有出现过"——在任意一张图里出现过就填 true / 记进数组，
   一次也算。一条帖子里系过领带，就是系过领带。
5. 跨图默认是同一个人，除非画面明显是不同的人；判不出就按第一张图里
   的人编，并在 notes 写明。
5b. 背景里的路人不是这条帖子在呈现的人。街上行人、操场人群、餐厅其他
   客人、被打码的背景人物都是场景。people_visible、primary_subject、
   two_people_together 只数这条帖子在呈现的人。一张夜里操场的照片，
   背景几十个人、主体一个人，people_visible 填 "1" 不是 "6+"。
6. 环境里的字不算这条帖子说的话。店招、菜单、横幅、路牌、别人屏幕上
   的字都是场景。onscreen_* 四组只收作者加上去的文字：贴纸、字幕、
   画在图上的文案、发帖人自己写在画面里的话。
7. 这些是静态图片不是视频。需要看到动作过程才能判断的字段
   （hand_gesture_dance、full_body_dance、lip_sync）一律填 false，
   除非画面本身就是一个明确的舞蹈姿势。

另外：不要考虑这条内容是否"敏感"、会不会被平台处理。该判断与本任务
无关，且会污染后续分析。

输出严格 JSON，不要有任何其他文字：

{
  "people_visible": "0" | "1" | "2" | "3-5" | "6+",
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
  "second_person": <同上结构；primary_subject 为 pair 时填，否则 null>,

  "presentation_distance": 1 | 2 | 3 | 4 | 5 | null,
  "apparent_minors": "none" | "possible" | "clear",

  "two_people_together": <true/false>,
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

people_visible：人最多的那一张图里同时出现的人数，分档填。只数这条
  帖子在呈现的人（铁律 5b），背景路人和人群一律不算，即使脸很清楚。
  镜子倒影、照片里的人、海报上的人算，并在 notes 写明；只有手/脚/
  背影算 1 个人；被打码的人是主体就算、是背景就不算。卡通、虚拟
  人物、动物不算。不要数精确人数。

primary_subject：single = 一人占据绝大部分画面；pair = 两人大致同等
  被呈现；group = 三人以上无明确主角；none = 无人或人仅为背景。
  一人出镜、另一人只有手，算 single。

谁进 subject、谁进 second_person：
  single → 那个人进 subject，second_person 填 null。
  pair → 出现在更多张图里的那位进 subject；张数相同时，第一张图里
         靠左的那位进 subject。另一位进 second_person。
  group → 出现在最多张图里的那位进 subject。如果没有任何人反复出现，
         subject 和 second_person 都填 null，presentation_distance
         也填 null，并在 notes 写明。
  none → 两者都 null。

face_visible：眼、鼻、嘴三者都能看见即为 true。四分之三侧面通常满足，
  正侧面（只看得到一只眼）不满足。口罩、马赛克、打码为 false；戴墨镜
  但其余清晰为 true。

coding_possible：以下任一成立即为 false —— 没有人；纯文字卡/截图/
  聊天记录；只有风景、食物、宠物、物品；人太小太暗太糊看不出发型和
  衣着。为 false 时 subject、second_person、presentation_distance
  全部填 null，但屏幕文字字段照常填。

hair_length：以最长的一缕为准，不是平均。
  shaved = 光头或寸头，看不出发型结构
  cropped_above_ear = 最长处不过耳垂
  ear_to_jaw = 过耳垂但不过下颌线
  jaw_to_shoulder = 过下颌线但不过肩线
  below_shoulder = 过肩
  not_visible = 戴帽/被遮挡/光线不足
  头发扎起时按放下来的估计长度判，判不出填 not_visible。假发接发照记。

hair_mullet：鲻鱼头 —— 顶部与两侧短，颈后留明显长出一截，长短之间有
  清晰层次界线。必须同时满足"上短侧短"和"后长"。只是后面稍长的层次感
  不算。看不到后脑填 false。

hair_undercut：两侧或后颈被剃/推到明显短于顶部，有可见分界线。仅
  "两边比较短"不算。

hair_dyed：非自然生长的发色。红蓝绿紫粉银白挑染为 true；棕色栗色浅褐
  为 false；光线偏色不算；拿不准填 false。

makeup_visible：none = 看不出化妆痕迹；light = 能看出但不醒目；
  heavy = 醒目（明显眼妆眼线睫毛、明显唇色、修容、亮片）；
  not_visible = 脸看不清/口罩/距离远。
  滤镜不等于化妆：全脸美颜但看不出具体妆容填 none，notes 写
  "heavy filter"。修图重到分不清是妆还是磨皮液化时填 not_visible，
  不要填 heavy。但部分能分清的按能分清的那部分填——整张脸磨得很平、
  眼线轮廓却清楚，那是修图造不出来的，填 heavy 或 light；
  not_visible 留给什么都读不出来的情况。

upper_garment：fitted = 能看出腰线或身体曲线（紧身、修身、短款）；
  loose_or_boxy = 宽松、廓形、oversize，看不出身体轮廓；
  not_visible = 只有大头照。外套敞开时按里层判。多张图衣着不同时取
  出现最多的那一种，没有多数取第一张。只判版型，不判好不好看或是否
  "男性化"。

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
hands_in_pockets：至少一只手插进裤袋或外套口袋。
arms_crossed：双臂在胸前交叉抱起。
gaze_direct：直视镜头（而非看向别处、低头、闭眼）。
head_tilt_or_chin_tuck：朝向镜头的那个姿势 —— 头向一侧倾斜，或下巴
  内收略低头向上看镜头。低头看别处、侧身望向画面外都不算。判不出朝向
  填 false。
peace_sign_or_heart：比耶（V 字）、比心（手指心或双手心）。
hand_gesture_dance / full_body_dance / lip_sync：静态图片一律 false，
  除非画面本身就是一个明确的舞蹈姿势。

presentation_distance：主要对象的呈现方式，离【中国主流短视频中
  "常规女性化"的那一套】有多远。参照系是平台主流这一个固定端点，
  不是女同亚文化，也不是你自己对性别的感觉。不要先判断对方的性别。
  判定程序：
  (1) 数下面四项，每项符合记一分：
      - 头发短于下颌线（shaved / cropped_above_ear / ear_to_jaw）
      - 无可见妆容（makeup_visible 为 none）
      - 上衣宽松廓形（upper_garment 为 loose_or_boxy）
      - 出现明确的男装单品：necktie、suit_jacket、sports_jersey 之一。
        cap 和 chain 不计分——鸭舌帽和链条在平台主流女性穿搭里很常见，
        拿它们当"男装"计分又是把风格读成性别。两者照常记录在
        menswear_items 里，只是不进这个计数。
  (2) 0 分 → 1，1 分 → 2，2 分 → 3，3 分 → 4，4 分 → 5。
  (3) not_visible 的项不计分；若四项中有两项以上是 not_visible，
      填 null —— 看不见的东西不能算作"没有偏离"。
      null 只给"看不见"（模糊、戴帽、只有背影），不给"说不清这人是
      男是女"。性别判断不参与这个量表的任何一步；中性化的呈现本身
      就是偏离，照常计分。
  (4) 若计数结果与你的整体印象不一致，以计数为准，并在 notes 写一句
      差在哪。
  coding_possible 为 false、或 subject 为 null 时填 null。

apparent_minors：画面里是否可能有未成年人。
  clear = 有明确的校服、校徽、中小学教室、"XX 中学"字样等；
  possible = 场景像校园或画面中人看起来很年轻，但没有确证；
  none = 没有任何这类线索。
  拿不准填 possible，不要填 none。这一项宁可过报。

two_people_together：画面中是否同时出现两个"这条帖子在呈现的人"。
  必须同框；交替出镜但从不同框填 false 并在 notes 写明。背景路人不算
  （铁律 5b）——一个人在人群前自拍填 false。不要判断他们的性别。

physical_affection：取最高档。none = 无接触；proximity = 明显贴近但
  不接触；hand_holding = 牵手挽手；embrace = 拥抱搂肩搂腰依靠；
  kiss = 亲吻身体任何部位（嘴、脸颊、额头、手背、头发）。
  只有一个人时填 none。

presented_as_couple：以下任一成立即为 true —— 画面内文字写明（三周年、
  我老婆、在一起 N 天）；情侣装或成对饰品；婚礼同居约会场景；构图明确
  是"我们两个"。仅仅两个人同框（合影、舞蹈搭档）不算。

onscreen_* 四组：从作者加上去的文字中逐字抄录，不翻译不归一化。拆开
  写的字母标签分别记录：屏幕上是 #l #e 就记 ["l", "e"]，不要合成
  "le"。环境里的字（店招、菜单、横幅、路牌）不收。
  emoji 被当作一个人的称呼使用时（"给 💅 的惊喜"），照抄进
  onscreen_relationship_terms；句尾装饰性的 emoji 不记。
  这四组绝不能影响上面任何一个关于外形、姿态或距离的字段。

onscreen_contact：屏幕上出现 QQ 号、微信号、Telegram 账号，或"加我"
  类引导。

confidence：对整条编码的信心。画面糊、信息少、多数字段 not_visible
  则低。

notes：一行以内，只在确实异常时写，正常填空字符串。
```

## 跑之前还要做的

1. **图文先 OCR。** 图文的文字在图片里，不先 OCR，F 组基本是空的。
2. **先抽 30 条校准。** 看字段是否稳定、`not_visible` 的比例是否
   合理、JSON 是否每次都合法。
3. **手工编 50 条算 κ。** B、C 两组应该很高；`presentation_distance`
   是必须报告的那一个。
4. **限定在"下架前已存档"的子集**做预测分析，否则又是幸存者偏差。
   这个子集多大，跑之前先算。
5. **六个预测变量，看结果之前定死。**
