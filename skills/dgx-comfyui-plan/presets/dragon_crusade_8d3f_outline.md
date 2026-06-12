---
id: dragon_crusade_8d3f
title: 討伐火龍遠征 — Fire Dragon Crusade (4 chapters × 6 panels, 悟性結局)
version: 3
created: '2026-06-11T20:30:00+08:00'
updated: '2026-06-12T18:01:27+08:00'
status: ready
workflow: flux_basic
size:
- 1024
- 1024
steps: 25
batch_per_item: 1
seed_strategy:
  type: incremental
  base: 8000
  step: 137
lora: []
face_ref: null
description: 24-panel dark fantasy dragon crusade storyboard (4ch×6) with cast-locked
  characters (hero/mage/guard/dragon), shot-language beats, per-chapter light/terrain
  progression, reconciliation ending. v3 battle-tested on DGX flux_basic.
tags:
- dark-fantasy
- storyboard
- dragon
- cast-locked
- 4-chapters
- redemption-arc
provenance:
  original_id: dragon_crusade_8d3f
promoted: '2026-06-12T18:01:27+08:00'
mode: storyboard
size_aspect: square
character_consistency: prompt_only
---

# Story / Vision
**討伐火龍的遠征** — 24 張連環畫（storyboard）。黑暗壓迫基調的史詩遠征：少年劍士與小隊（銀髮法師 + 塔盾衛）受命討伐肆虐的古老火龍。四章弧線：**召集 → 跨越 → 遭遇 → 決戰**——結局不是屠龍而是**悟性/和解**：少年在龍巢看見龍環抱的碎裂殘巢（幼龍被人類所毀），放下劍，黎明中火龍飛離。

**v2（2026-06-12 診斷後重寫）**，針對 v1 四個實證根因：
1. **cast 機制鎖四角**（protagonist / mage / guard / dragon）——外觀字串單一來源，`cast_in_panel` 控制逐格注入：主角不再亂入純氛圍鏡、配角不再被主角外觀污染、龍跨張同一設計。
2. **全季 molten-orange palette 鎖移除**——章節色彩改由 per-group lighting 字串攜帶，解掉「熔岩提前出現在 ch1/ch2」。
3. **24 beat 全部重寫為分鏡語言**——明確 shot size、人數寫死（exactly N）、行進方向統一向畫面右、火山地理錨點四章遞進（地平線紅光 → 遠方煙柱 → 聳立眼前 → 巢內）、敘事概念翻成畫面物件直給。
4. **配角獲得獨立焦點格**——法師（ch2_03 夜讀、ch3_04 結界）、盾衛（ch3_05 撐盾），減少三人同框（僅 ch1_04 / ch3_06）。

# Design Dimensions

```yaml
season_structure:
  theme: 討伐火龍的遠征（黑暗壓迫、悟性結局）
  grouping_axis: chapter
  groups:
    ch1:
      count: 6
      label: 召集 — 山村受襲、立誓組隊出發
      label_en: the mustering — village under threat, oath and departure
    ch2:
      count: 6
      label: 跨越 — 灰燼荒原的艱困跋涉
      label_en: the crossing — grim trek through the ash wastes
    ch3:
      count: 6
      label: 遭遇 — 火山麓首戰與碎巢線索
      label_en: the encounter — first clash in the volcanic foothills, the broken
        nest clue
    ch4:
      count: 6
      label: 決戰與悟 — 龍巢對決、放下劍、黎明休戰
      label_en: the reckoning — duel in the lair, the sword lowered, truce at dawn
  cross_group_progression:
    composition:
      ch1: grounded eye-level composition, stable horizon, heavy negative space
      ch2: tilted diagonal composition, figures small against vast terrain
      ch3: extreme low and high angles, claustrophobic tight framing
      ch4: monumental scale-contrast composition, vast cavern dwarfing human figures
    background:
      ch1: mountain village of dark timber and stone palisades in an autumn highland
        valley, bare dry autumn hills, brown dirt ground
      ch2: endless flat grey ash wastes with scattered dead trees, the smoking volcano
        small on the far horizon
      ch3: black volcanic foothills, cooled lava fields veined with glowing fissures,
        the volcano towering close overhead
      ch4: colossal obsidian cavern interior, towering basalt pillars, pools of molten
        rock
    lighting:
      ch1: cold overcast dusk light, desaturated blue-grey tones, warm torchlight
        only in small patches
      ch2: flat ashen grey daylight, washed-out desaturated tones, sun hidden behind
        ash clouds, no warm sunset light
      ch3: deep darkness lit from below by infernal molten orange glow
      ch4: dim cavern shadow lit by molten orange under-light
narrative_direction:
  character_seed: 棕髮少年劍士為主視點，同行：銀髮灰袍女法師（節瘤木杖）與蓄鬚塔盾衛（疤面鐵塔盾）。對手：古老火龍——黑曜石黑鱗、鱗縫熔岩橙光脈、餘燼橙眼，暴怒源於被人類毀去的巢（視覺外觀以
    cast 區塊為唯一來源，此處僅敘事參考）
  group_arc:
    ch1: 召集 — 地平線紅光、軍議、授劍立誓、同伴登場、辭別、啟程
    ch2: 跨越 — 灰燼荒原、焚毀商隊、法師夜讀、索橋渡險、老倖存者指路、山脊初見火山
    ch3: 遭遇 — 熔岩原、碎巢與幼龍骸骨（悟性伏筆）、龍影掠空、法師結界、盾衛撐盾、餘燼中三人喘息
    ch4: 決戰與悟 — 龍巢之門、對峙、死鬥、殘巢揭示（怒即是慟）、放下劍、黎明休戰
visual_lock:
  composition:
    scope: per_group
  background:
    scope: per_group
  lighting:
    scope: per_group
  style_intensity:
    scope: locked
    value: dark fantasy manga style, heavy ink lineart, high contrast shadows, limited
      muted color
    value_zh: 暗黑奇幻漫畫風、重墨線條、高對比陰影、有限低彩度用色
cast:
  protagonist:
    name: the young swordsman
    visual:
      hair: young male swordsman, short messy brown hair
      outfit: worn dark leather armor, tattered dark red cloak, longsword on his back
      features: lean build, determined face
  mage:
    name: the silver-haired mage
    visual:
      features: slender female mage, long pale silver hair under an ash-grey hood,
        grey layered robes, gnarled wooden staff
  guard:
    name: the shield guard
    visual:
      features: burly middle-aged shield guard, full dark beard, scar across his cheek,
        large round iron shield on his left arm
  dragon:
    name: the fire dragon
    type: creature
    visual:
      features: colossal ancient fire dragon, obsidian-black scales cracked with glowing
        molten orange veins, ember-orange eyes, vast ragged dark wings
per_item_beats:
  ch1_01_burning_horizon:
    description: wide establishing shot at eye level — the young swordsman stands
      on a wooden palisade rampart with exactly four villagers, all seen from behind,
      gazing at a faint red glow on the far horizon under heavy grey clouds, dark
      quiet village rooftops below
    description_zh: 平視廣角建立鏡——少年劍士與恰好四名村民立於木柵城牆上、全部背影，凝望厚重灰雲下遠方地平線的一抹微弱紅光，腳下村莊屋頂暗而安靜
    cast_in_panel:
    - protagonist
  ch1_02_war_council:
    description: medium interior shot — a torch-lit timber hall, five grim elders
      seated around a battered map table, the young swordsman standing across the
      table facing them, a single candle on the map, deep shadows on weathered faces
    description_zh: 中景內景——火把照明的木造大廳，五名神情凝重的長老圍坐破舊地圖桌，少年劍士隔桌而立面向他們，地圖上一支孤燭，蒼老面孔覆著深重陰影
    cast_in_panel:
    - protagonist
  ch1_03_oath:
    description: close-up — the young swordsman kneeling on stone, both hands receiving
      an old longsword laid flat across the wrinkled open palms of an elder reaching
      in from frame right, the blade catching cold light, dark hall background
    description_zh: 特寫——少年劍士跪於石地，雙手承接一柄平放在長老皺紋掌心上的古舊長劍、長老雙手自畫面右側伸入，劍身映冷光，暗廳背景
    cast_in_panel:
    - protagonist
  ch1_04_companions:
    description: medium three-shot — the silver-haired mage and the bearded shield
      guard standing on either side of the young swordsman before the hall doors,
      exactly three figures, torchlight from the left, solemn expressions
    description_zh: 中景三人鏡——銀髮法師與蓄鬚盾衛分立少年劍士兩側、立於大廳門前，恰好三人，火把光自左側來，肅穆神情
    cast_in_panel:
    - protagonist
    - mage
    - guard
  ch1_05_farewell:
    description: medium shot at the village gate in grey dawn mist — the young swordsman
      pausing mid-step while walking toward frame right, looking back over his left
      shoulder at two small family silhouettes in a lit doorway behind him, overcast
      autumn morning, bare dry dirt road
    description_zh: 灰色黎明霧中村門中景——少年劍士朝畫面右行進間駐足，回望左肩後方亮燈門口的兩個家人小剪影，陰沉秋晨，乾燥土路
    cast_in_panel:
    - protagonist
  ch1_06_departure:
    description: extreme wide shot — exactly three tiny cloaked travelers walking
      toward frame right along a dirt road leaving the village, the village small
      at frame left, bare autumn hills, a faint red glow on the far right horizon
      under low grey clouds
    description_zh: 大遠景——恰好三名披風旅人沿土路朝畫面右行、離開村莊，村莊縮小於畫面左側，蕭瑟秋丘，低垂灰雲下畫面右側遠地平線一抹微紅光
  ch2_01_ash_wastes:
    description: extreme wide shot — a flat endless plain of grey ash under a white
      overcast sky, exactly three tiny figures walking in single file toward frame
      right, a thin smoke column rising from a small volcano on the far right horizon,
      a footprint trail behind them
    description_zh: 大遠景——白色陰霾天空下平坦無際的灰燼平原，恰好三個小小身影一列縱隊朝畫面右行，畫面右側遠地平線的小火山升起細煙柱，足跡拖在身後
  ch2_02_ruined_caravan:
    description: medium shot — the young swordsman crouched beside the charred skeleton
      of a burnt caravan wagon half buried in ash, lifting a scorched child's doll
      from the ash, dead grey landscape behind, no other people
    description_zh: 中景——少年劍士蹲在半埋灰燼的焦黑商隊馬車殘骸旁，自灰中拾起一只燒焦的孩童布偶，身後死寂灰色地景，無其他人
    cast_in_panel:
    - protagonist
  ch2_03_night_camp:
    description: medium night shot — the silver-haired mage sitting cross-legged by
      a small campfire reading a worn leather journal, the fire the only light in
      total darkness, two bedrolls dimly visible at frame edge, sparks drifting upward
    description_zh: 夜間中景——銀髮法師盤坐小營火旁翻閱破舊皮革手札，營火是全黑中唯一光源，畫面邊緣隱約可見兩個鋪蓋卷，火星上飄
    cast_in_panel:
    - mage
  ch2_04_storm_crossing:
    description: wide action shot — the young swordsman leading the way across a narrow
      rope bridge over a deep grey ravine toward frame right, two cloaked figures
      following behind him on the bridge, an ash storm blowing all cloaks hard toward
      the left, grey rock walls, no lava
    description_zh: 廣角動作鏡——少年劍士領頭走過深灰峽谷上的窄索橋、朝畫面右行，兩名披風身影跟在橋上，灰燼風暴把所有披風猛吹向左，灰色岩壁，無熔岩
    cast_in_panel:
    - protagonist
  ch2_05_survivor:
    description: medium two-shot — the young swordsman kneeling to speak with a gaunt
      bald elderly survivor wrapped in scorched rags sitting against a dead tree,
      the old man's bony hand pointing toward frame right, flat grey daylight, the
      smoking volcano small in the far background
    description_zh: 中景雙人鏡——少年劍士單膝跪地，與倚枯樹而坐、裹著燒焦破布的瘦削禿頂老倖存者交談，老人枯瘦的手指向畫面右方，平灰日光，遠景小小冒煙火山
    cast_in_panel:
    - protagonist
  ch2_06_first_sight:
    description: extreme wide shot from behind — exactly three small silhouettes standing
      on a ridge crest at frame left, looking across a vast grey valley toward the
      volcano at far right, now larger, wreathed in smoke with a faint red glow at
      its peak, overcast sky
    description_zh: 背後大遠景——恰好三個小剪影立於畫面左側山脊頂，越過遼闊灰谷望向畫面右側遠方的火山——比先前更大、被煙環繞、峰頂泛微紅光，陰霾天空
  ch3_01_scorched_land:
    description: extreme wide high-angle shot — black cooled lava fields veined with
      glowing orange fissures stretching toward the volcano now towering at frame
      right, exactly three tiny figures picking their way toward it, ash drifting
      like dark snow
    description_zh: 俯角大遠景——黑色冷卻熔岩原、裂縫透出橙光，一路延伸至此刻聳立於畫面右側的火山，恰好三個渺小身影朝它擇路前行，灰燼如黑雪飄落
  ch3_02_broken_nest:
    description: low close-up — the young swordsman kneeling beside a ruined dragon
      nest, the foreground filled with large broken dragon eggs with pale blue-white
      shell fragments, small charred dragon hatchling bones, and three burnt human
      spear shafts stuck in the ground, his gloved hand hovering over a tiny skull,
      molten light from a fissure lighting his face from below
    description_zh: 低位特寫——少年劍士跪於被毀的龍巢旁，前景滿是碎裂的大型龍蛋、淺藍白色蛋殼碎片、焦黑的幼龍小骸骨、三根插在地上的燒焦人類矛桿，他戴手套的手懸在一個小小頭骨上方，下方裂縫熔光自下照亮他的臉
    cast_in_panel:
    - protagonist
  ch3_03_ambush:
    description: wide low-angle shot — the colossal dragon sweeping low overhead as
      a dark winged shape against the grey sky, wings blotting out the light, exactly
      three small figures below diving for cover behind black rocks, ash whirling
    description_zh: 仰視廣角——巨龍貼低掠過頭頂、襯著灰天成黑色有翼暗影，雙翼蔽光，下方恰好三個小身影撲向黑岩後掩蔽，灰燼旋捲
    cast_in_panel:
    - dragon
  ch3_04_flame_torrent:
    description: wide shot — the silver-haired mage standing firm at frame left with
      staff raised, projecting a translucent dome of blue-white runic light over two
      crouching silhouettes, the dragon's torrent of orange flame crashing against
      the dome from frame right, black rock landscape
    description_zh: 廣角——銀髮法師立定於畫面左側、高舉法杖，撐起藍白符文半透明光罩護住兩個蹲伏剪影，龍的橙色烈焰洪流自畫面右側撞擊罩面，黑岩地景
    cast_in_panel:
    - mage
    - dragon
  ch3_05_shieldwall:
    description: close-up — the bearded shield guard braced low behind his large round
      iron shield, the shield edge glowing red-hot, sparks streaming past on both
      sides, teeth gritted, one knee on black rock
    description_zh: 特寫——蓄鬚盾衛壓低身軀撐住巨大鐵圓盾，盾緣燒得通紅，火星自兩側流瀉而過，咬緊牙關，單膝抵著黑岩
    cast_in_panel:
    - guard
  ch3_06_ember_refuge:
    description: medium wide shot inside a rock crevice — the young swordsman, the
      silver-haired mage and the bearded shield guard sitting battered around a single
      ember glow, bandaged arms, soot-streaked faces, the swordsman staring down at
      his sheathed sword, exactly three figures
    description_zh: 岩縫內中廣景——少年劍士、銀髮法師、蓄鬚盾衛三人傷痕累累圍著一點餘燼微光而坐，手臂纏著繃帶、滿面煙灰，劍士低頭凝視入鞘的劍，恰好三人
    cast_in_panel:
    - protagonist
    - mage
    - guard
  ch4_01_lair_gate:
    description: extreme wide shot — the mouth of a colossal obsidian cavern like
      a cathedral of black glass, towering basalt pillars, molten light glowing from
      deep within, exactly three tiny figures standing at the threshold at frame bottom,
      utterly dwarfed
    description_zh: 大遠景——巨大黑曜石洞窟之口如黑玻璃大教堂，玄武岩柱聳立，深處透出熔光，恰好三個渺小身影立於畫面下緣門檻、被徹底矮化
  ch4_02_confrontation:
    description: extreme low-angle shot — the colossal dragon rearing to full height
      inside the molten-lit cavern, half-spread wings touching the pillars, the young
      swordsman tiny at frame bottom facing it with sword drawn, embers floating
    description_zh: 極端仰角——巨龍在熔光洞窟中昂起全身，半展之翼觸及岩柱，少年劍士渺小立於畫面下緣、拔劍面對，餘燼飄浮
    cast_in_panel:
    - protagonist
    - dragon
  ch4_03_duel:
    description: dynamic wide action shot — the young swordsman mid-leap toward frame
      right dodging a sweep of the dragon's tail, the edge of his cloak on fire, sword
      arcing upward, the dragon's head lunging in from frame left, molten splashes
      and flying debris
    description_zh: 動態廣角動作鏡——少年劍士向畫面右躍起、閃過龍尾橫掃，披風邊緣著火，長劍向上劃弧，龍首自畫面左側撲入，熔岩飛濺與碎石橫飛
    cast_in_panel:
    - protagonist
    - dragon
  ch4_04_revelation:
    description: medium shot — the dragon's huge head lowered to the ground at frame
      right with its molten eye half closed, its coiled tail at frame left cradling
      a ruined nest of shattered pale eggshells, the young swordsman standing small
      between them, his sword arm sinking, quiet stillness
    description_zh: 中景——龍的巨首垂至地面、位於畫面右側，熔岩色眼半闔，蜷起的尾於畫面左側環抱著滿是蒼白碎蛋殼的殘巢，少年劍士小小立於兩者之間、持劍的手臂垂落，靜默無聲
    cast_in_panel:
    - protagonist
    - dragon
  ch4_05_sword_lowered:
    description: wide shot — the young swordsman standing before the towering dragon,
      his longsword lowered with its tip touching the ground, the dragon's head bowed
      level with him, embers settling between them, both utterly still, facing each
      other in profile
    description_zh: 廣角——少年劍士立於巍峨之龍前，長劍垂下、劍尖觸地，龍首低垂與他同高，餘燼在兩者之間緩緩落定，雙方全然靜止、側面相對
    cast_in_panel:
    - protagonist
    - dragon
  ch4_06_dawn_truce:
    description: extreme wide shot at the cave mouth — the dragon flying away through
      thinning smoke toward pale golden dawn light at frame right, exactly three small
      figures standing at frame bottom left watching it go, the first warm light falling
      on them
    description_zh: 洞口大遠景——巨龍穿過漸散的濃煙、朝畫面右側蒼白金色曙光飛離，恰好三個小身影立於畫面左下目送，旅程的第一道暖光落在他們身上
    cast_in_panel:
    - dragon
```

# Style anchor
**Prefix**: masterpiece, ultra detailed, intricate
**Suffix**: (none)
**Negative**: (none)

# Output
- dir: outputs/ar2-dgx-comfyui-gen/dragon_crusade_8d3f/
- naming: {NN}_{slug}_{n}.png

# Items
| # | slug | prompt | full? |
|---|------|--------|-------|
| 1 | ch1_01_burning_horizon | <derived> |  |
| 2 | ch1_02_war_council | <derived> |  |
| 3 | ch1_03_oath | <derived> |  |
| 4 | ch1_04_companions | <derived> |  |
| 5 | ch1_05_farewell | <derived> |  |
| 6 | ch1_06_departure | <derived> |  |
| 7 | ch2_01_ash_wastes | <derived> |  |
| 8 | ch2_02_ruined_caravan | <derived> |  |
| 9 | ch2_03_night_camp | <derived> |  |
| 10 | ch2_04_storm_crossing | <derived> |  |
| 11 | ch2_05_survivor | <derived> |  |
| 12 | ch2_06_first_sight | <derived> |  |
| 13 | ch3_01_scorched_land | <derived> |  |
| 14 | ch3_02_broken_nest | <derived> |  |
| 15 | ch3_03_ambush | <derived> |  |
| 16 | ch3_04_flame_torrent | <derived> |  |
| 17 | ch3_05_shieldwall | <derived> |  |
| 18 | ch3_06_ember_refuge | <derived> |  |
| 19 | ch4_01_lair_gate | <derived> |  |
| 20 | ch4_02_confrontation | <derived> |  |
| 21 | ch4_03_duel | <derived> |  |
| 22 | ch4_04_revelation | <derived> |  |
| 23 | ch4_05_sword_lowered | <derived> |  |
| 24 | ch4_06_dawn_truce | <derived> |  |

# Open notes
- **v3 微修（2026-06-12）**：① 移除 ch1 的「no snow」否定句（negation 陷阱實證：T5 看到 snow 就畫雪，v2 ch1 三格中雪）→ 改正面描述 bare dry autumn；② 盾衛塔盾改圓盾（模型兩格都自發畫圓盾且內部一致，順勢採納）；③ ch3_02 蛋殼加重加色（large broken dragon eggs, pale blue-white）。v2 已驗證有效的否定句（ch2 `no warm sunset light`、ch2_04 `no lava`）不動。
- **v2 重寫（2026-06-12）**：根據 v1 全 24 張逐格診斷。v1 四根因 → 四修法對照見 Story / Vision。v1 圖檔保留在 `outputs/ar2-dgx-comfyui-gen/2026-06-11/dragon_crusade_8d3f/`，v2 同 seed（base 8000）重跑、可逐格對照。
- **cast_in_panel 注入統計**：protagonist 12 格 / mage 3 / guard 3 / dragon 7 / 純氛圍鏡 5 格（ch1_06、ch2_01、ch2_06、ch3_01、ch4_01）完全不注入角色外觀——遠景的「exactly three tiny figures」靠 beat 文字own。
- **悟性結局線（v2 強化）**：ch3_02 碎巢改為前景物件清單直給（蛋殼/幼龍骸骨/燒焦矛桿）→ ch4_04 龍尾環抱殘巢 + 熔眼半闔 → ch4_05 劍尖觸地 → ch4_06 黎明飛離。認知動詞（sees/realizes）全部移除。
- **倖存者防污染**：ch2_05 明寫 gaunt bald elderly（禿頂老者）與主角棕短髮少年硬區隔，防 v1 的「縮小版主角」復發。
- **已知殘餘風險**：cast 是 prompt 層鎖、非 PuLID 級——配角臉部細節仍可能殘餘漂移；Flux 暖光偏置用 ch2「no warm sunset light」等否定字串對抗、不保證全壓住；ch4_06 曙光與 ch4 cgp 洞窟暗光並存、靠 beat 權重蓋過。
- **Negative (none)**：flux_basic 單 CLIPTextEncode，非空 negative 會整批 inject raise。
- **跑命令**：`python3 ~/.claude/skills/ar2:dgx-comfyui-gen/scripts/generate.py --plan dragon_crusade_8d3f`
