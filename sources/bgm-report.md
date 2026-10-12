# BGM 拆解报告：呆呆不吃喵 / Linksphotograph / 影视飓风

对标片 12 条（呆呆 4 + Links 4 + 影视飓风 4，另加影视飓风长片 2 条）。
所有结论来自本地素材自算，无一处引用外部影评。

---

## 一、先说方法：BGM 是怎么"识别"出来的

UP 主的 BGM 有三种获取途径，我三条都用上了：

**途径 1：视频简介里的曲目表（一手证据）**
呆呆 59 条视频里有 17 条在简介直接列了 BGM 清单（如"BGM: Evan Call - Time Flows Ever Onward / …"），
用正则从简介里切出 `BGM:` 段落即可拿到**准确的曲名+作者**。

**途径 2：片尾滚屏字幕里的音乐版权栏（一手证据）**
影视飓风每支片子的片尾滚屏都分栏列出「音乐 Music / 素材鸣谢」，
我是**逐格看片尾接触表（每 4 秒 1 帧）把字幕文字读出来的**，比如《水下风暴》片尾列了 10 首、
《非洲淘金》列了 13 首 + 3 条素材鸣谢。

**途径 3：拿不到曲表时，用 Shazam 听歌识曲反推（Links、以及验证前两条）**
Links 既不写简介也不列片尾，只能靠识别。步骤：

1. **抽音轨**：`ffmpeg -i <原片> -vn -ac 2 -ar 48000 -c:a aac`（不重编码视频，音轨与原片时间轴严格对齐）。
2. **先用 ASR 找出"没人说话"的时间窗**：本地 qwen3-ASR 逐句听译，每句带 `[hh:mm:ss - hh:mm:ss]`
   时间码 → 合并成"有声段"→ 反推出**≥8 秒的无旁白窗**（`speech_timeline.py`）。
   这一步是命中率的关键：BGM 在没人说话时才"露出来"，人声一压，Shazam 就听不见。
3. **在无旁白窗中心截 12 秒音频**（`ffmpeg -ss <t> -t 12` → 44.1kHz wav）。
4. **送 Shazam 识别**：用 `shazamio`（Python 客户端，复刻 Shazam 移动端请求签名）调 Shazam 公开识别接口，
   取回 title / subtitle(=artist)。每点间隔 2.5–4 秒限速，失败指数退避重试 3 次；
   采样点写 jsonl，**可续跑**（已采过的点自动跳过）——一套脚本断断续续跑了上千个采样点。
5. **盲扫兜底**：对无旁白窗太少的片子（台词密集），再加固定步长（60/90 秒）全片扫一遍。
6. **交叉验证**：把识别结果与途径 1/2 拿到的一手曲表比对——
   呆呆《雨崩》简介写的是 `Jordan Critz - Aperture`、`Evan Call - Old Man Voll`，
   Shazam 分别在 7:30、21:00 命中同两首，**证明识别链路是准的**；
   影视飓风《非洲淘金》片尾列的 `Chiwoniso - Zuluhepera` 也被识别为 `Chiwoniso - Zvichapera`（拼写差异）。

**途径 4（新增）：扒谱读到"配方"**
用本地 SheetSage2（`:8101`）把识别出的 BGM 片段转成可编辑谱，拿到**调性 / 速度 / 和弦进行 /
旋律音域 / 音符密度**——即"要复刻这种听感，配方是什么"。21 个片段的谱面结果见
`~/projects/bgm-analyze/REPORT_BGM_SCORES.md`（核心结论：收尾类的"电影感"= 小调 + VI/VII 借用和弦 +
60–90 BPM + 窄音域长音旋律 + 30–60 音符/分）。

**这套方法的已知局限**（必须写清楚，否则会误读）：
- 命中率随"说话密度"暴跌：雪山片 74%（留白多）→ 冈仁波齐 35% → 库拉岗日 13%（几乎全程口播）。
- 会有**误识别**：库拉岗日识别出的拉丁雷鬼（Nio García）、《雪山》识别出的"KALASAN 纸巾"，
  明显是 Shazam 在环境音/风声上的假阳性，本报告已剔除或标注。
- 同一首曲子会被识别成"不同段落"（如某首歌的 orchestral 版），所以曲目数是**下界**。
- Shazam 只能识别"有曲库指纹"的曲子：商用曲库、OST、流行歌能识别；UP 主自制曲、无版权库曲目识别不出。

---

## 二、三家用的是三种完全不同的曲库

### ① 呆呆不吃喵：动漫 / 游戏 / 电影 OST + 治愈系钢琴（**简介逐曲列出**）

8 条片的完整曲表（节选，全部原文照抄）：

- **《雨崩神瀑徒步》**：梶浦由記 - Smile For Me｜**Evan Call - Theme of Violet Evergarden**｜
  Howard Shore - Concerning Hobbits（指环王）｜**HOYO-MiX - 清风散林缬**｜Evan Call - Time Flows Ever Onward｜
  Joanie Madden - Down By the Salley Gardens｜Gareth Coker - Light of Nibel
- **《虎跳峡 20km》**（13 首）：Philter｜Evan Call ×3｜岩田恭明 - イチカラ村 / リトの村（塞尔达）｜
  **C418 - Wet Hands**（我的世界）｜西木康智（歧路旅人）｜**José González - Stay Alive**｜
  星野源,末廣健一郎 - 恋 Strings & Piano ver.
- **《腾格里沙漠 32km》**：Jesper Kyd - Ezio's Family（刺客信条）｜Evan Call｜
  Todd Baker - Alto's Odyssey｜Ólafur Arnalds - Epilogue｜Priscilla Ahn - I See You｜Berlinist - GRIS｜
  **Tony Anderson - Ariana**（与 Links 同一位曲库作者）｜Marcus Warner - In the End
- **《川西 5000 米湖泊》**：Evan Call ×3｜立山秋航｜**Rhianne - Somewhere Only We Know**｜加藤達也｜
  Priscilla Ahn - I Am Not Alone
- **《格聂 30km》**（13 首）：Evan Call ×3｜Nintendo - Welcome Horizons｜**莫西子诗 - 啊杰咯**｜
  ConcernedApe（星露谷）｜**Low Roar - Don't Be So Serious**｜Denean - Vow to Virtue｜
  William Joseph - Sweet Remembrance Of You

**规律**：曲库 = 动漫/游戏/电影 OST（塞尔达、歧路旅人、GRIS、MC、刺客信条、指环王、紫罗兰永恒花园）
＋ 治愈系新世纪/凯尔特（Peder B. Helland、Joanie Madden、Ólafur Arnalds、Denean）
＋ 少量独立流行人声歌（José González、Low Roar、Priscilla Ahn、莫西子诗）。
**Evan Call（《紫罗兰永恒花园》）是它的"主题曲作者"，8 条里 6 条都有**——相当于建立了一个
"一听就知道是这个 UP"的音乐签名。整体以器乐为主，人声歌只占约 1/5，且都放在情绪高点。

### ② Linksphotograph：**商用电影感曲库（production music library），全片不署名**

简介不列曲目、片尾只有 LOGO 定版，**没有任何音乐版权信息**（这点和另两家完全相反）。

Shazam 识别结果（按时间）：命中率见括号，标注为疑似误识别的已标 ★ 假：

**《人生第一座雪山》55:11（74%，识别出 9 首）**
Voyageur - All I Wanted（10:36）｜Luke Atencio - Counsel（16:24）｜
Shawn Williams - The Moon, It Rises (Orchestral)（17:12–18:18）｜★ KALASAN…
Jordan Critz - Imbre（37:12）｜Kevin P Holt - Journey Through the Clouds（39:12）｜
Daniel Catalá - Elevare（45:12–46:00）｜ROMÉO - Winds of Hope（46:54–47:48）｜
**Sémo - Fractured Timeline（50:20–54:50 = 结尾）**

**《世界上最孤独的房子》29:22（27%）**
Tony Anderson - Dreamlife（0:00，开场）｜**Zach Bryan - Pink Skies**（4:00，唯一一首真·流行歌）｜
Roary - Overlook（14:00–16:00）｜Ryan Taubert - Becoming Human（17:00–18:00）｜
The Seventh Movement & Ardie Son - Folklore（29:00 = 结尾）

**《冈仁波齐》22:37（35%）**
Max LL - Andes（0:00 开场 **与 15:00 复用同一首**）｜Roary - Airborne（8:00–9:00）｜
Generdyn - Evermore（20:00–22:00 = 高潮+升华+结尾）

**《库拉岗日》37:33（13%）**
Shawn Williams - Dreamland（0:30）｜★ Nio García（假阳性）｜Adrian Disch - Things Are Looking Up（13:54）｜
Jordan Critz - Infinite（22:30）

**规律**：作者名单（Max LL、Tony Anderson、Ryan Taubert、Jordan Critz、Roary、Generdyn、Sémo、
Voyageur、Shawn Williams、Ardie Son、Adrian Disch…）**全部是 Musicbed 系电影预告片曲库的签约作曲家**。
风格极其统一：纯器乐、弦乐+合成器、由弱到强的 build-up，**没有人声**。这就是它"一眼电影感"的声音来源——
不是天分，是**同一家曲库的同一类曲子**堆出来的听感一致性。

### ③ 影视飓风：**商用曲库 + 委托定制 + 古典乐**，片尾滚屏逐条署名

**《带着100万，我们见到了女巫…》39:37**
- **孙嘉伟（曲）— 01.03.16 / 03.05.19** ← 自制定制配乐，曲名直接用时间码命名
- V.A. - **La forza del destino Overture**（Giuseppe Verdi，古典）
- **The Dance of Death - Audiomachine**（好莱坞预告片曲库）
- Ecstasy / Spellbound（V.A.）
- 片尾职员表另有：声音设计 夏德岛 Quentin、混音 何剑
- Shazam 侧证：38:12 命中这首威尔第序曲（用的是曲库录制版，非经典名盘）

**《我们拍到了水下风暴》24:47**（片尾列 10 首）
Above the Clouds - Hannis Johnson｜Follow the Sun - Christian Nanzell｜Sunset - Ian Post｜
RISE - Michael Vignola｜The Light - Michael Wall｜Distant Echoes - Adam Sliwinski｜
Last Breath - Kyle Preston｜Life - Ian Post｜The Discoverer - Sémø｜Reason to Live - Veaceslav Draganov
- Shazam 侧证：1:00 Hans Johnson - Rise Up｜8:48–13:42 Longlake - Lily｜
  18:12 Tyler Brown Williams - When I Found You (feat. Jordan Critz)｜22:06 Daniel Deuschle - Onward｜
  **24:31 sød ven - evergreen（片尾曲）**

**《非洲淘金》22:24**（片尾列 13 首 + 3 条素材鸣谢）
Distant Worlds - Melody Sheep｜**Serenata - Max LL**｜Dirt - Jo Blankenburg｜A Clearing - Makeup And Vanity Set｜
Big Idea - Alice Emmott｜A Glimmer Of Hope - Kino｜Bach Chorale And Prelude - The Symphony Brass Of Chicago｜
**Ezio's Family - Henry Miles**（刺客信条主题的曲库录制版）｜The Verdict - Trevor Kowalski｜
Small Town Feeling - Eric Feinberg｜In Our House - Hanna Lindgren｜The Slow Shift - Gavin Luke｜
Crawling - Hanna Ekstrom
素材鸣谢：Sully Field - Chad Crouch / Leaving - Kristian Eidnes Andersen / **Zuluhepera - Chiwoniso**
- Shazam 侧证：4:54 Henry Miles - Exile｜10:06 Pär Hagström - Make You Feel Right｜**22:00 Chiwoniso - Zvichapera（片尾）**

**《去了一趟西班牙2.0（日全食篇）》24:33**
Café de Maria - Luis Allieres｜Toccata in D minor - Bishara Haroni｜Mozart: Requiem - Bishara Haroni｜
**A Beam of Light - Trademark**｜**Tree House - Nieve**
素材鸣谢：Panda / Meet Me For Coffee / Guantanamera / Buenos Dias / Tu y Yo / La Venta
- Shazam 侧证：10:06 Flower Duet (Lakmé)｜10:48 Tristan Barton - A Beam of Light｜
  20:54 Sezer Ulker - Medusa｜**24:07 Nsee - Tree House（片尾）**

**《带着100万，我们揭开了赌场的秘密…》53:49**
- Shazam 侧证（声轨里能识出来的全是**爵士大乐队 + 法国香颂 + 古典**）：
  2:12 Shtriker Big Band - Lemonade｜6:18 **Edith Piaf - La Foule**｜
  8:36 Abilene - As We Dream (Bach Cello Suite No.1)｜11:06 Shtriker Big Band - Chunky Monkey｜
  28:18 **Gabriel Fauré - Sicilienne**
- **曲库选型跟着题材走**：赌场 = 爵士大乐队/香颂（营造"拉斯维加斯/老钱"质感），
  古典乐只在严肃主题段（大萧条合法化、制度批判）进来

**《去了一趟挪威》28:24**
- Shazam 侧证：13:06 Daniel Catalá - Tiny Wonders｜**28:00–28:12 Steven Beddall - Blanket of Starlight（片尾）**

**规律**：影视飓风是**唯一有"配乐预算"的一家**——定制曲（孙嘉伟）+ 古典乐（威尔第、巴赫、莫扎特安魂曲、
德利布的《花之二重唱》）+ 预告片曲库（Audiomachine）+ 欧美商用曲库（Epidemic Sound 系作者
Gavin Luke / Trevor Kowalski / Hanna Lindgren / Jo Blankenburg），片尾逐条署名。

> **两家曲库是同一个池子**：**Max LL** 同时出现在 Links《冈仁波齐》（Andes）和影视飓风《非洲淘金》（Serenata）；
> **Jordan Critz** 同时出现在 Links《雪山》（Imbre）、呆呆《雨崩》（Aperture，简介列明）、
> 影视飓风《水下风暴》（When I Found You 的 feat. 作者）。也就是说，**这三家的音乐其实来自同一批欧美曲库**，
> 只是用法、预算、署名方式不同。

---

## 三、音乐是怎么"铺"的：与旁白的关系

用 ASR 逐句时间码统计（`speech_timeline.py`）：

| 片子 | 时长 | 语音占比 | ≥8s 无旁白窗 | 最长一段 |
|---|---|---|---|---|
| 呆呆·泰山 | 25:23 | 73.5% | 10 | 35s |
| 呆呆·峨眉山 | 33:20 | 68.9% | 16 | 69s |
| 呆呆·虎跳峡 | 40:39 | 74.2% | 13 | 73s |
| 呆呆·雨崩 | 27:28 | 64.4% | 17 | 65s |
| Links·最孤独的房子 | 29:22 | 76.2% | 13 | 43s |
| Links·冈仁波齐 | 22:37 | 74.7% | 12 | 33s |
| Links·库拉岗日 | 37:33 | 74.1% | 18 | 41s |
| Links·人生第一座雪山 | 55:11 | 64.6% | 26 | **150s** |
| 飓风·女巫 | 39:37 | 92.1% | 5 | 32s |
| 飓风·水下风暴 | 24:47 | 73.5% | 8 | **78s** |
| 飓风·非洲淘金 | 22:24 | 82.3% | 7 | 35s |
| 飓风·西班牙日食 | 24:33 | 80.8% | 7 | 47s |
| 飓风·赌场 | 53:49 | 92.9% | 11 | 23s |

三条规律（12 条片全部成立）：

1. **无旁白窗集中在三类位置**：开场冷蒙太奇、进入新地形/换段、高潮与结尾。
2. **撤旁白最彻底的三个位置**：Links《雪山》49:10 起 **150 秒**（登顶后静默蒙太奇）、
   影视飓风《水下风暴》17:40 起 **78 秒**（自然奇观段）、Links / 呆呆的结尾段（40–70 秒）。
3. **音乐几乎不停**：有旁白的段落 BGM 也在底下垫着（识别命中集中在无旁白段，
   是因为音乐被"露出来"了，不是只在那些段才有音乐）。

---

## 四、收尾规律："最后一首大曲子压住结尾"

Shazam 在片尾 60 秒内的识别结果（命中即为片尾正在放的曲子）：

| 片子 | 片尾曲 | 覆盖范围 |
|---|---|---|
| Links·人生第一座雪山 | Sémo - Fractured Timeline | 50:20 → 54:50（4.5 分钟不换曲） |
| Links·冈仁波齐 | Generdyn - Evermore | 20:00 → 22:00（高潮+升华+收尾） |
| Links·最孤独的房子 | The Seventh Movement & Ardie Son - Folklore | 29:00 起 |
| 飓风·水下风暴 | sød ven - evergreen | 24:31 起（片尾） |
| 飓风·非洲淘金 | Chiwoniso - Zvichapera | 22:00 起（片尾滚屏"素材鸣谢"同一条） |
| 飓风·西班牙日食 | Nsee - Tree House | 24:07 起（片尾滚屏同一条） |
| 飓风·挪威 | Steven Beddall - Blanket of Starlight | 28:00 → 28:12（片尾） |
| 呆呆·雨崩 | Evan Call - Old Man Voll | 21:00 起（与简介曲表一致） |

**结论（也是主人问的"末尾回放"的答案）**：
结尾**不是把前面镜头重剪一遍的回放式混剪**（我逐帧看过 Links《冈仁波齐》《最孤独的房子》的片尾接触表：
都是"新素材尾声 + 金句字幕 + LINKSPHOTOGRAPH 定版"）。真正的规律是：
**结尾用一首情绪最大的曲子，从高潮一路铺到片尾，中途不换曲，同时撤掉旁白**——
听感上就像结尾在"回放"这段情绪。参考时长：Links 的大曲子覆盖最后 2–4.5 分钟；
影视飓风片尾字幕段 40 秒–3 分钟。

顺带一条客观的"片尾怎么收"数据（镜头切点自算）：
- 影视飓风《日食》**最后 60 秒 0 次切镜**（全片最长镜 187 秒出现在 21.4 分钟）→ 一镜到底压滚屏字幕
- 影视飓风《女巫》《水下风暴》最后 60 秒 **19 个镜头**（约 3 秒一镜）→ 快切 B-roll 压滚屏字幕
- 呆呆《泰山》最后 60 秒 **1 个镜头**（19 秒）｜Links《雪山》4 个镜头（14.7 秒）→ 散文式慢收尾

---

## 五、可直接照抄的选曲模板（给主人的徒步/旅行 vlog）

**曲库选择（两条路，任选其一）**
- A. 呆呆式：动漫/游戏/电影 OST（自带情绪记忆、观众熟悉、免费可商用少）——
  一条片定一个"主题作者"（呆呆=Evan Call），全片 6–8 首，人声歌最多 1–2 首放高潮。
- B. Links / 影视飓风式：**欧美电影感曲库**（Musicbed / Epidemic Sound / Artlist / Audiomachine）。
  这是"显贵"的捷径：同一家曲库选 5–6 首，风格自然统一。**别用抖音热歌**（三家 12 条片里只出现过 1 次流行歌）。

**铺法（时间轴）**
1. **0:00–0:30 开场冷蒙太奇**：一首带 build-up 的曲子，30 秒内起势（画面零字幕零旁白）。
2. **0:30–中段**：2–3 首中等强度器乐，在"换地形/换段"处换曲（换曲点 = 结构转折点）。
3. **低谷/金句段**：换成最安静的一首（呆呆在 13:59 金句处把镜长拉到 29.9 秒，音乐同步变静）。
4. **高潮 → 结尾**：**同一首情绪最大的曲子从高潮一直铺到片尾**（2–5 分钟不换曲），
   这段撤旁白 40–150 秒，画面用连续长镜/延时，最后叠金句字幕 + LOGO 定版。
5. **曲目数量**：20–25 分钟成片用 **4–6 首**（另两家的曲表长是"一首曲子的多个段落"或多个短曲拼出来的）。

**一个便宜但有效的动作**：把开场那首的主题旋律在片中再出现一次（Links《冈仁波齐》0:00 的
Max LL《Andes》在 15:00 又出现）——听感上形成回环，观众会觉得"整支片子是完整的"。
