---
id: cards_a11c
title: 奇幻冒險卡冊 — Fantasy Adventure Card Set (5 chapters × 12)
version: 1
created: '2026-05-16T18:13:41+08:00'
updated: '2026-05-18T11:27:19+08:00'
status: ready
workflow: flux_pulid
size:
- 512
- 512
steps: 25
batch_per_item: 1
seed_strategy:
  type: incremental
  base: 1000
  step: 137
lora: []
face_ref: <set face_ref locally>
description: 5-chapter Pixar 3D fantasy adventure (60 cards) with PuLID character
  consistency. Set face_ref locally before use.
tags:
- fantasy
- adventure
- pixar
- pulid
- 5-chapters
- card-set
provenance:
  original_id: cards_a11c
promoted: '2026-05-18T11:27:19+08:00'
---

# Story / Vision
5-chapter fantasy adventure card set (60 cards total). A young girl's hero's-journey told in Pixar 3D style:

  Ch1 啟程 — receives a mysterious map, leaves home, enters forest.
  Ch2 森林試煉 — meets forest spirit guide, learns first magic spell.
  Ch3 古城探秘 — solves ancient city puzzle, finds dragon egg.
  Ch4 龍之挑戰 — egg hatches, bonds with dragon, defeats shadow creatures.
  Ch5 歸途 — returns home with dragon, shares wisdom, sets out for next.

Each chapter has 12 cards forming a continuous narrative within. The 60 cards together tell the complete story.

Character: 12-year-old girl with brown braids and freckles, wearing a simple traveler's cloak with leather satchel.

# Style anchor
**Prefix**: (none)
**Suffix**: , Disney Pixar 3D animation style, vibrant cinematic lighting, painterly textures, stylized proportions, family-friendly, high quality 3D render
**Negative**: (none)

# Output
- dir: outputs/ar2-dgx-comfyui-gen/cards_a11c/
- naming: {NN}_{slug}_{n}.png

# Items
| # | slug | prompt | full? |
|---|------|--------|-------|
| 1 | ch1_01_home_morning | a 12-year-old girl with brown braids and freckles, wearing a simple traveler's cloak with leather satchel, waking up in a cozy cottage bedroom at sunrise, soft golden light through wooden window |  |
| 2 | ch1_02_breakfast_family | the girl having porridge with her warm-faced grandmother at a wooden kitchen table, freckles visible, soft camera angle |  |
| 3 | ch1_03_letter_arrival | a small messenger bird dropping a sealed parchment letter on the windowsill, the girl reaches out with curious eyes |  |
| 4 | ch1_04_secret_map | the girl unfolding an ancient hand-drawn map on the wooden floor by candlelight, mysterious symbols glowing faintly |  |
| 5 | ch1_05_packing_satchel | the girl carefully packing a loaf of bread, a small compass, and a wooden charm into her leather satchel |  |
| 6 | ch1_06_grandmother_blessing | the grandmother hugging the girl by the cottage door, both tearful but smiling, soft sunset light |  |
| 7 | ch1_07_leaving_village | the girl walking down a cobblestone path leaving her thatched-roof village, villagers waving in the background |  |
| 8 | ch1_08_first_step_road | wide cinematic shot of the girl on a winding country road, distant mountains, hopeful determined expression |  |
| 9 | ch1_09_first_night_camp | the girl sitting by a small crackling campfire under a sky full of stars, opening the map to study it, owl perched on nearby branch |  |
| 10 | ch1_10_crossing_stream | the girl carefully hopping across smooth stones in a small forest stream, sunlight filtering through trees, butterflies |  |
| 11 | ch1_11_forest_entrance | the girl pausing at the edge of a dark mysterious forest, mossy ancient tree archway, soft swirling fog |  |
| 12 | ch1_12_glance_back | the girl looking back one last time toward her distant village before stepping into the forest, dramatic golden hour |  |
| 13 | ch2_01_entering_deeper | a 12-year-old girl with brown braids and freckles, wearing a simple traveler's cloak with leather satchel, stepping deeper into a magical forest, glowing mushrooms scatter the ground, dappled shafts of light |  |
| 14 | ch2_02_lost_path | the girl looking confused at a fork in the forest path, an ancient broken wooden signpost covered in moss |  |
| 15 | ch2_03_strange_sounds | the girl startled, looking sideways at pairs of glowing eyes peeking from dark bushes, defensive but curious stance |  |
| 16 | ch2_04_small_critter | a friendly small forest creature (squirrel-fairy with leaf wings) peeking shyly from behind leaves |  |
| 17 | ch2_05_critter_guide | the small fairy creature beckoning the girl with tiny paws to follow, leading deeper into a magical part of the woods |  |
| 18 | ch2_06_mossy_clearing | the girl reaching a sunlit clearing with floating spirit lights and dancing will-o-wisps, ancient stones in a circle |  |
| 19 | ch2_07_spirit_appears | a tall majestic forest spirit (deer-like with antlers made of glowing leaves) emerges from mist, awe-inspiring scale |  |
| 20 | ch2_08_silent_dialogue | the girl kneeling and offering an open palm to the towering forest spirit, gentle wordless moment of trust |  |
| 21 | ch2_09_first_lesson | the spirit's antler-light guiding the girl's hand to summon a small orb of warm light, intense focused expression |  |
| 22 | ch2_10_practicing_spell | the girl alone in moonlit clearing practicing the light spell, the orb wobbling and flickering, frustrated determination |  |
| 23 | ch2_11_mastery_moment | the girl finally producing a stable bright glowing orb in her palm, joyful triumphant expression, magic sparkles |  |
| 24 | ch2_12_departure_gift | the forest spirit handing the girl a glowing leaf-charm pendant, she ties it to her satchel with reverence |  |
| 25 | ch3_01_descending_stairs | a 12-year-old girl with brown braids and freckles, wearing a simple traveler's cloak with leather satchel, walking down ancient stone stairs heavily overgrown with vines and flowers, sunlight breaking through |  |
| 26 | ch3_02_first_glimpse | wide cinematic shot of the girl gazing at a vast vine-covered crumbling ancient city below, golden hour, scale and wonder |  |
| 27 | ch3_03_through_arch | the girl passing under a massive crumbling stone archway, her tiny figure dwarfed by the architecture |  |
| 28 | ch3_04_market_square_ruins | the girl exploring an overgrown market square in the ancient city, broken pottery, mysterious carved pillars |  |
| 29 | ch3_05_strange_symbols | the girl examining glowing intricate symbols carved on a moss-covered wall, fascinated lit-from-below face |  |
| 30 | ch3_06_temple_entrance | the girl at a grand temple entrance, her light-orb spell illuminating the dark doorway ahead |  |
| 31 | ch3_07_puzzle_room | the girl standing in a circular puzzle room with rotating concentric stone disc patterns on the floor |  |
| 32 | ch3_08_solving_puzzle | the girl pushing and turning a heavy carved stone disc, intense concentration, dust motes in shaft of light |  |
| 33 | ch3_09_hidden_passage | a hidden passage suddenly opens in the wall, warm golden light spilling out, the girl wide-eyed |  |
| 34 | ch3_10_treasure_chamber | the girl entering an ornate chamber with a stone pedestal at center, a beautiful egg-shaped object resting on top |  |
| 35 | ch3_11_dragon_egg_close | close-up of the girl carefully cradling a glowing dragon egg in both hands, awe and reverence on her face |  |
| 36 | ch3_12_leaving_with_egg | the girl walking out of the ruined city at sunset, the dragon egg glowing softly in her arms, silhouette shot |  |
| 37 | ch4_01_egg_hatching | a 12-year-old girl with brown braids and freckles, wearing a simple traveler's cloak with leather satchel, at night camp by firelight, the dragon egg cracking open with magical golden light, wide-eyed amazement |  |
| 38 | ch4_02_baby_dragon | a small adorable cat-sized baby dragon with iridescent scales emerging from the eggshell, looking up curiously |  |
| 39 | ch4_03_first_bond | the girl gently offering berries to the baby dragon from her palm, a careful tender moment of trust |  |
| 40 | ch4_04_growing_friendship | the dragon now medium-sized, riding on the girl's shoulder as they hike along a mountain ridge in daylight |  |
| 41 | ch4_05_shadow_appears | the sky suddenly darkening with swirling sinister shadow creatures circling above, girl and dragon look up alarmed |  |
| 42 | ch4_06_first_attack | shadows diving down to attack, the dragon protectively shielding the girl with its wings, dramatic action shot |  |
| 43 | ch4_07_calling_back_dragon | the dragon now grown to adult size, standing beside the girl, both ready for battle, fierce determined poses |  |
| 44 | ch4_08_taking_flight | the girl climbing onto the now-adult dragon's back, gripping the saddle horn, hopeful courageous expression |  |
| 45 | ch4_09_aerial_battle | the dragon swooping dynamically through the cloudy sky dodging shadow creatures, cinematic action |  |
| 46 | ch4_10_using_light_magic | the girl on dragonback summoning a brilliant light-orb spell to dispel the shadows, dramatic light burst |  |
| 47 | ch4_11_shadow_dispersed | final confrontation: the shadows banished and the sky clearing, golden sunlight breaking through clouds |  |
| 48 | ch4_12_resting_together | the girl and her dragon resting on a mountaintop at dawn, exhausted but deeply bonded, warm sunrise |  |
| 49 | ch5_01_homecoming_view | a 12-year-old girl with brown braids and freckles, wearing a simple traveler's cloak with leather satchel, on dragonback flying back toward her home village in the distance, dawn light, hopeful tearful smile |  |
| 50 | ch5_02_landing | the dragon landing gently in a field outside the village, villagers gasping in awe at the dragon, the girl waving |  |
| 51 | ch5_03_grandmother_reunion | the grandmother running, hugging the girl tightly with tears of joy, the dragon watching warmly nearby |  |
| 52 | ch5_04_introducing_dragon | the girl introducing the friendly dragon to surprised but smiling villagers, the dragon lowering its head shyly |  |
| 53 | ch5_05_children_playing | village children initially cautious then enthusiastically playing with the gentle dragon in the meadow |  |
| 54 | ch5_06_teaching_magic | the girl teaching the small forest light-charm to a circle of younger village kids, all wide-eyed with wonder |  |
| 55 | ch5_07_village_evening | an evening celebration in the village square with hanging paper lanterns, music, dance, joyful atmosphere |  |
| 56 | ch5_08_telling_story | the girl sitting around a campfire telling her adventure stories to gathered children, the dragon curled and listening |  |
| 57 | ch5_09_quiet_morning | quiet morning back in her old bedroom, sunlight streaming in, but now her dragon is visible outside the window |  |
| 58 | ch5_10_packing_again | the girl looking at her map again on the floor, marking new unexplored lands with a quill pen, smiling |  |
| 59 | ch5_11_friend_join | a brave village friend asks to come along on the next adventure, packing eagerly with their own satchel |  |
| 60 | ch5_12_new_horizon | the girl, her dragon, and her friend setting out toward a new horizon at sunrise, wide cinematic hopeful shot |  |

# Open notes
60 items, 5 chapters (ch1-ch5) × 12 cards each. Slug encoding: ch{N}_{NN}_{name}. Run with: gen --plan cards_a11c
