---
id: dragon_hunt_ensemble
title: 獵龍冒險 manga panels — Multi-character ensemble (22 panels)
version: 2
created: '2026-05-21T16:00:00+08:00'
updated: '2026-05-22T10:00:00+08:00'
status: ready
mode: storyboard
size_aspect: landscape_16_9
workflow: flux_basic
character_consistency: prompt_only
size:
- 1280
- 720
steps: 25
batch_per_item: 1
seed_strategy:
  type: incremental
  base: 5000
  step: 137
lora: []
face_ref: null
---

# Story / Vision

獵龍冒險 hero's journey **42 卡 final** 的 **Ensemble plan (22 panels)**。對應**多角色含主角**的場景：群像 / 對話 / 隊伍協作 / 主角與他人並列動作 / 招募事件 / 戰鬥共同奮戰 / 勝利合影。

**v2 redesign (5/22)**：原本 dragon_hunt_solo (11 panels) 概念失敗 — solo 主角獨照無 context、跟劇情無連結。重新審視 48 slugs 後刪 6（純氛圍/過場），11 panels 從 solo / 2 panels 從 atmosphere 移入 ensemble 重寫為多角色。

**Why flux_basic without PuLID**：PuLID 設計為 single-subject consistency、會強制主角為唯一視覺主體、把法師/武者/治療師 face-swap 全變主角臉。flux_basic + prompt-described hero 接受「主角臉每張略有變化」的代價、換取 ensemble 敘事完整保留。

**Hero consistency strategy**：visual_lock hair + outfit locked → 每張 prompt 含「中長棕髮、金胸甲帶龍紋章、深藍披風」、模型在臉部變化下仍保留可辨識外觀。

配對 plan：dragon_hunt_atmosphere (20) = 完整 42。

# Style anchor
**Prefix**: (none)
**Suffix**: , manga panel illustration, atmospheric ink and color, dynamic dramatic framing
**Negative**: (none)

# Output
- dir: outputs/ar2-dgx-comfyui-gen/dragon_hunt_ensemble/
- naming: {NN}_{slug}_{n}.png

# Items
| # | slug | prompt | full? |
|---|------|--------|-------|
| 1 | ch1_03_recruit_mage | <derived> |  |
| 2 | ch1_04_recruit_warrior | <derived> |  |
| 3 | ch1_05_recruit_healer | <derived> |  |
| 4 | ch1_06_team_briefing | <derived> |  |
| 5 | ch1_09_farewell | <derived> |  |
| 6 | ch1_11_first_camp | <derived> |  |
| 7 | ch2_02_old_marker | <derived> |  |
| 8 | ch2_04_river_crossing | <derived> |  |
| 9 | ch2_05_bandit_ambush | <derived> |  |
| 10 | ch2_08_high_ridge | <derived> |  |
| 11 | ch2_09_storm_shelter | <derived> |  |
| 12 | ch3_02_distant_roar | <derived> |  |
| 13 | ch3_05_dragon_breath | <derived> |  |
| 14 | ch3_07_retreat_strategy | <derived> |  |
| 15 | ch3_09_studying_lair | <derived> |  |
| 16 | ch3_10_setting_trap | <derived> |  |
| 17 | ch3_11_calling_out | <derived> |  |
| 18 | ch4_03_first_clash | <derived> |  |
| 19 | ch4_08_team_split | <derived> |  |
| 20 | ch4_09_critical_moment | <derived> |  |
| 21 | ch4_10_final_strike | <derived> |  |
| 22 | ch4_11_dragon_falls | <derived> |  |

# Design Dimensions

```yaml
season_structure:
  theme: 獵龍冒險 manga panels (Ensemble v2)
  theme_en: dragon hunt manga panels (Ensemble v2)
  grouping_axis: custom
  groups:
    ensemble_panels:
      count: 22
      label: 多角色含主角場景
      label_en: multi-character with hero panels
  cross_group_progression: {}

narrative_direction:
  character_seed: 4 人隊伍 — 主角（年輕男魔法劍士、中長棕髮綁短馬尾、金胸甲帶龍紋章、深藍披風）+ 法師（年輕女性、藍紫長髮、執精雕木製法杖）+ 武者（紅短髮男性、雙手大劍、皮甲）+ 治療師（金髮白袍女性、聖徽項鍊）
  character_seed_en: "four-person party — protagonist (young male mage swordsman, medium-length brown hair with short ponytail, golden breastplate with dragon emblem, dark blue cape), mage (young female, long indigo-purple hair, ornate wooden staff), warrior (red short-hair male, two-handed great sword, leather armor), healer (blonde female in white robes with sacred pendant)"
  group_arc:
    ensemble_panels: 隊伍互動 / 群體決策 / 共同經歷 — 主角為隊伍一員、其他角色同等可見
  mood: 隊伍羈絆 + 共同奮戰 + 角色互動張力
  mood_en: party bonds + shared struggle + character interaction tension

visual_lock:
  hair:
    value: medium-length brown hair with short ponytail at the back (for the male protagonist)
    value_zh: 中長棕髮後方綁短馬尾（男主角）
    scope: locked
  outfit:
    value: golden breastplate with dragon emblem and dark blue cape (for the male protagonist)
    value_zh: 金胸甲帶龍紋章與深藍披風（男主角）
    scope: locked
  composition:
    value: null
    scope: unspecified
  background:
    value: null
    scope: unspecified
  lighting:
    value: null
    scope: unspecified
  expression:
    value: null
    scope: unspecified
  style_intensity:
    value: manga panel illustration, detailed inked lineart, atmospheric color, dramatic dynamic framing, multi-character clarity
    value_zh: 漫畫分鏡插畫、細緻墨線、氛圍色彩、戲劇動態構圖、多角色清晰
    scope: locked
  view_angle:
    value: null
    scope: unspecified
  color_palette:
    value: muted earth tones with dramatic accent colors, gold for hero, indigo for mage, red for warrior, white for healer, scarlet for dragon
    value_zh: 沉穩大地色調、戲劇性點綴色、主角金、法師藍紫、武者紅、治療師白、龍鮮紅
    scope: locked

per_item_beats:
  ch1_03_recruit_mage:
    description: manga panel two-shot of the protagonist meeting a young female mage with long indigo-purple hair holding an ornate wooden staff in a tower study, both at eye-level, mage gesturing while explaining, shelves of glowing tomes behind, warm interior light, both characters clearly distinct with different hair colors and outfits
    description_zh: 漫畫分鏡主角在魔法塔書齋遇見年輕女法師（藍紫長髮、執精雕木製法杖）雙人鏡、平視、法師手勢解說、後方發光書架、暖色內景光、兩角色髮色與服裝清晰可辨
  ch1_04_recruit_warrior:
    description: manga panel scene of the protagonist entering a blacksmith forge to recruit a red-haired warrior man, the warrior pausing his polishing of a great two-handed sword to look up at the visitor, glowing forge embers, protagonist presenting a written quest scroll, three-quarter angle interior, both characters clearly distinct
    description_zh: 漫畫分鏡主角進入鐵匠鋪招募紅短髮男武者、武者停下打磨大劍抬頭看訪客、熔爐餘燼、主角遞出任務卷軸、四分之三角內景、兩角色清晰可辨
  ch1_05_recruit_healer:
    description: manga panel scene of the protagonist entering a sunlit temple to meet a blonde female healer in white robes praying at an altar, protagonist standing in the aisle of stained-glass beams holding his helmet respectfully, healer looking over her shoulder, eye-level intimate framing, both characters clearly distinct
    description_zh: 漫畫分鏡主角進入陽光透窗聖殿尋金髮白袍女治療師、治療師在祭壇前祈禱、主角立於彩光長廊恭敬持頭盔、治療師回頭一望、平視親密構圖、兩角色清晰可辨
  ch1_06_team_briefing:
    description: manga panel ensemble shot of four party members around a wooden table with a spread parchment map, protagonist leaning forward pointing at a route, indigo-haired mage holding her staff listening, red-haired warrior with great sword crossed-arms, blonde healer in white robes standing beside, overhead three-quarter angle, candlelit war-room atmosphere, all four characters clearly visible
    description_zh: 漫畫分鏡 4 人圍坐木桌與羊皮紙地圖、主角前傾指路線、藍紫髮法師執杖聆聽、紅髮武者持大劍抱胸、金髮白袍治療師立旁、俯視四分之三角、燭光作戰室氣氛、4 角色清晰可見
  ch1_09_farewell:
    description: manga panel group shot at the village gate, protagonist clasping an elderly grey-bearded village elder's shoulder while three party members (indigo-haired mage, red-haired warrior, blonde healer) stand behind ready to depart, villagers waving in the background, warm sunset light, emotional intimate tone, eye-level
    description_zh: 漫畫分鏡村門口群像、主角握住灰鬍長老肩膀、3 名隊員（藍紫髮法師、紅髮武者、金髮治療師）立後待發、村民後方揮手、暖色夕陽、情感親密、平視
  ch1_11_first_camp:
    description: manga panel ensemble of four party members around a crackling campfire at night, protagonist sharpening his sword, indigo-haired mage reading by firelight, red-haired warrior whittling a stick, blonde healer mending a cloak, intimate eye-level circle, starry night background, all four characters clearly visible
    description_zh: 漫畫分鏡 4 人圍夜晚篝火群像、主角磨劍、藍紫髮法師借火光閱讀、紅髮武者削木枝、金髮治療師補披風、親密平視圍坐、星夜背景、4 角色清晰可見
  ch2_02_old_marker:
    description: manga panel group shot of four party members gathered around a weathered stone marker, protagonist kneeling and brushing moss off ancient runes while indigo-haired mage leans in to read, red-haired warrior keeping watch, blonde healer touching the stone reverently, three-quarter angle, soft diffused mountain light
    description_zh: 漫畫分鏡 4 人圍古石碑群像、主角單膝跪下撥開苔蘚露出古老符文、藍紫髮法師傾身閱讀、紅髮武者警戒、金髮治療師恭敬撫石、四分之三角、柔和漫射山光
  ch2_04_river_crossing:
    description: manga panel dynamic action shot of four party members wading through a rushing icy river holding hands for stability, protagonist leading in front, indigo-haired mage holding her staff overhead behind him, red-haired warrior in the middle, blonde healer at the back, water spraying around their legs, motion blur on water, dramatic side angle
    description_zh: 漫畫分鏡 4 人手拉手涉湍急冰冷河流動態動作、主角帶頭前行、藍紫髮法師執杖高舉於其後、紅髮武者中間、金髮治療師殿後、水花濺腿、水面動感模糊、戲劇性側角
  ch2_05_bandit_ambush:
    description: manga panel intense action shot of the protagonist parrying a curved bandit blade with his sword, sparks at the impact, the red-haired warrior charging in from frame-right swinging his great two-handed sword at a second bandit, the indigo-haired mage in the background readying a spell, dust and motion lines, dynamic diagonal composition
    description_zh: 漫畫分鏡主角持劍擋山賊彎刀激烈動作、撞擊處火花、紅髮武者從畫面右側衝入揮雙手大劍砍向第二山賊、藍紫髮法師在後方準備施法、塵土與動線、對角線動態構圖
  ch2_08_high_ridge:
    description: manga panel low-angle action shot of the protagonist gripping a rock outcrop with one hand and reaching down with the other to pull the blonde healer in white robes up a sheer ridge, the indigo-haired mage already on top extending her staff for support, red-haired warrior climbing behind the healer, cold blue overcast light, vertiginous depth below
    description_zh: 漫畫分鏡主角單手抓凸岩單手下伸拉金髮白袍治療師上陡峻山脊低角度動作、藍紫髮法師已在上伸法杖協助、紅髮武者在治療師後攀爬、冷藍陰天光、下方眩暈感深度
  ch2_09_storm_shelter:
    description: manga panel ensemble of four party members huddled under a rocky overhang during a thunderstorm, protagonist with golden breastplate, indigo-haired mage clutching her staff, red-haired warrior with sword across knees, blonde healer pressed close, cold rain pouring beyond, lightning flash illuminating their tense faces, claustrophobic close framing
    description_zh: 漫畫分鏡 4 人雷雨中擠岩壁突岩下群像、金胸甲主角、執杖藍紫髮法師、劍橫膝紅髮武者、緊靠的金髮治療師、冷雨傾盆於外、閃電照亮緊張臉孔、壓迫近景構圖
  ch3_02_distant_roar:
    description: manga panel ensemble shot of four party members frozen mid-walk on a mountain trail, all turning toward an off-frame dragon roar, protagonist gripping his sword hilt, indigo-haired mage clutching her staff, red-haired warrior crouching defensively, blonde healer wide-eyed and clutching her pendant, tension-thick atmosphere, eye-level group shot
    description_zh: 漫畫分鏡 4 人在山道行進中凍住群像、全轉向畫外龍吼、主角緊握劍柄、藍紫髮法師抓住法杖、紅髮武者蹲伏防禦、金髮治療師睜大眼握聖徽、緊張氛圍、平視群像
  ch3_05_dragon_breath:
    description: manga panel action shot of four party members diving for cover behind boulders as orange dragon flame washes overhead, protagonist shielding himself with his cape, indigo-haired mage raising a partial barrier with her staff, red-haired warrior tackling the blonde healer behind a rock, embers swirling, dynamic group composition
    description_zh: 漫畫分鏡 4 人散開躲巨石後動作鏡、橙色龍焰掠過頭頂、主角以披風遮身、藍紫髮法師舉杖部分結界、紅髮武者撲倒金髮治療師於岩後、餘燼飛舞、動態群體構圖
  ch3_07_retreat_strategy:
    description: manga panel intimate group close-up of four party members huddled in a small ravine, protagonist crouched drawing a tactical map with a stick on the dirt, indigo-haired mage pointing at a section, red-haired warrior frowning at the layout, blonde healer holding a torch for light, low-key lighting with focused attention
    description_zh: 漫畫分鏡 4 人小峽谷中親密群像、主角蹲下用樹枝在地上畫戰術圖、藍紫髮法師指向一處、紅髮武者皺眉看格局、金髮治療師持火把照明、低調光線聚焦
  ch3_09_studying_lair:
    description: manga panel group of four party members concealed behind brush observing a dragon lair entrance from a distance, indigo-haired mage sketching in a journal, protagonist with hand on his sword grimacing, red-haired warrior pointing at a feature, blonde healer whispering, three-quarter quiet tension
    description_zh: 漫畫分鏡 4 人藏灌木後遠觀龍巢洞口、藍紫髮法師在日誌中描繪、主角按劍皺眉、紅髮武者指向一處、金髮治療師低語、四分之三靜謐張力
  ch3_10_setting_trap:
    description: manga panel group action shot of four party members rigging a heavy net trap with ropes and stakes across a gorge approach, protagonist hammering an iron stake into stone, red-haired warrior pulling a thick rope taut, indigo-haired mage securing a knot with her staff, blonde healer holding the net's edge, mid-action side angle
    description_zh: 漫畫分鏡 4 人狹窄峽谷入口架設重網陷阱動作鏡、主角錘擊鐵樁入石、紅髮武者拉緊粗繩、藍紫髮法師持杖固定結、金髮治療師扶網邊、動態中側角
  ch3_11_calling_out:
    description: manga panel scene of the protagonist standing alone in the open at a gorge mouth shouting up at a cave, while three party members crouch hidden behind boulders to the side ready to spring a trap, indigo-haired mage gripping her staff, red-haired warrior on the rope, blonde healer signaling readiness, dramatic wide composition
    description_zh: 漫畫分鏡主角獨立峽谷口空地向洞穴大喊、3 名隊員蹲伏側旁巨石後準備啟動陷阱、藍紫髮法師握杖、紅髮武者握繩、金髮治療師打信號、戲劇性廣構圖
  ch4_03_first_clash:
    description: manga panel kinetic action shot of the protagonist charging forward and striking the dragon's scaled flank with his sword, the red-haired warrior right behind him swinging his great two-handed sword at the dragon's leg, the indigo-haired mage casting a spell in the background, sparks flying, dynamic side composition
    description_zh: 漫畫分鏡主角衝鋒持劍擊龍鱗側動態動作、紅髮武者緊隨其後揮雙手大劍砍龍腿、藍紫髮法師在後方施法、火花飛濺、動態側面構圖
  ch4_08_team_split:
    description: manga panel wide environmental shot of a vast lair after a blast, four party members scattered across the floor recovering — protagonist crawling toward his fallen sword, red-haired warrior limping behind a pillar, indigo-haired mage propping herself up with her staff, blonde healer ministering to a wounded shoulder, broken pillars and debris everywhere, somber wide angle
    description_zh: 漫畫分鏡爆炸後廣闊龍巢廣景、4 人散落地面恢復 — 主角爬向墜地的劍、紅髮武者跛行躲斷柱、藍紫髮法師執杖撐起身、金髮治療師療傷肩膀、斷柱與碎片遍地、沉鬱廣角
  ch4_09_critical_moment:
    description: manga panel dramatic shot of the dragon's massive jaws looming open above the pinned protagonist, his sword raised in defensive cross-guard, the red-haired warrior rushing in from the side with his great sword raised to intercept, the indigo-haired mage in the background casting a desperate spell, extreme low angle
    description_zh: 漫畫分鏡龍張開大口逼近被壓制的主角戲劇鏡、主角以劍交叉防禦、紅髮武者從側衝來高舉大劍阻擋、藍紫髮法師在後方絕望施法、極低角度
  ch4_10_final_strike:
    description: manga panel mid-air slow-motion action shot of the protagonist leaping high to plunge his sword into the dragon's exposed throat with both hands, the blade glowing brilliantly with magic from the indigo-haired mage's spell visible at the base, the red-haired warrior holding the dragon's other side in place, dramatic vertical composition
    description_zh: 漫畫分鏡主角高躍雙手將劍插入龍喉半空慢動作、劍身因藍紫髮法師施法閃耀魔法光、紅髮武者於另側固定龍身、戲劇性垂直構圖
  ch4_11_dragon_falls:
    description: manga panel wide shot of four heroes standing together at the foot of the fallen scarlet dragon, protagonist still gripping his sword stained with blood, indigo-haired mage leaning on her staff, red-haired warrior with his great sword resting on his shoulder, blonde healer reaching toward a wounded teammate, dust settling, victorious yet exhausted, eye-level wide composition
    description_zh: 漫畫分鏡 4 人並立於倒地鮮紅龍腳下廣景、主角仍持染血之劍、藍紫髮法師倚法杖、紅髮武者大劍扛肩、金髮治療師伸手向傷隊員、塵霧落定、勝利但疲憊、平視廣構圖
```

# Open notes

- **Plan 1 of 2 (final v2)**: 22 panels、配對 atmosphere plan 20 panels = 42 完整 storyboard
- **v2 redesign (5/22)**：原 solo plan 概念失敗、11 panels 從 solo 移入（其中 8 改寫為多角色 + 3 純刪：ch1_01/07/12）、2 panels 從 atmosphere 移入（ch1_04/05 改寫成招募事件）
- **判定標準**：「每張獨立呈現能看出事件 ✓」、純氛圍/過場 ✗
- **Workflow trade-off**：flux_basic 接受主角臉每張略有變化、換取 ensemble 敘事完整保留
- **跑命令**：`python3 ~/.claude/skills/ar2:dgx-comfyui-gen/scripts/generate.py --plan dragon_hunt_ensemble`
- **重跑提醒**：本 plan 已從 12 → 22 panels，需重新 gen 全 22 張（既有 12 張被新 base seed 5000 取代）
