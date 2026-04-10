# Ingest Quality Experiments

Systematic evaluation of ingest prompt engineering changes.
Each experiment uses the same 20 Space Race snippets, 10 recall questions, and 5 graph probes.

**Scoring:**
- Expected edges: how many of 15 key relationships were correctly captured
- Anti-patterns: how many of 3 known problems are present (lower = better)
- Recall with context: how many of 10 questions returned cited nodes

## 01-baseline
**Date:** 2026-04-10 19:52 UTC
**Notes:** Original ingest prompt, no changes. Rate limits increased.

### Scores
| Metric | Value |
|--------|-------|
| Expected edges | **8/15** |
| Anti-patterns | **0/3** (lower=better) |
| Total graph connections | **43** |
| Recall with context | **6/6** |
| Recall total nodes cited | **47** |

### Expected Edges
- ✓ von Braun --[*direct*]--> Marshall
- ✓ von Braun --[*develop*]--> V-2
- ✓ von Braun --[*recruit*]--> Paperclip
- ✗ Apollo 11 --[*crew*]--> Armstrong
- ✗ Apollo 11 --[*crew*]--> Aldrin
- ✗ Apollo 11 --[*crew*]--> Collins
- ✗ Apollo 11 --[*part_of*]--> Apollo
- ✓ Apollo 11 --[*launch*]--> Kennedy
- ✓ Sputnik --[*launch*]--> Soviet
- ✓ Sputnik --[*trigger*]--> Space Race
- ✗ Sputnik --[*launch*]--> Baikonur
- ✗ Korolev --[*known*]--> Chief Designer
- ✗ Korolev --[*led*]--> Soviet
- ✓ Saturn V --[*design*]--> von Braun
- ✓ Saturn V --[*launch*]--> Apollo

### Anti-patterns
- ✓ Two edges between von Braun and Marshall with synonymous labels
- ✓ launched_on edge targeting a note instead of entity
- ✓ Artifact with led_by edge (should be person→led→artifact)

### Graph Probes
**Wernher von Braun** (12 connections)
- → [held_role] Marshall Space Flight Center (MSFC) directorship (1960–1970)
- → [led_development_of] V-2 rocket
- → [recruited_via] Operation Paperclip
- → [served_as_first_director_of] Marshall Space Flight Center
- → [worked_on] PGM-19 Jupiter
- → [worked_on] Redstone (rocket)
- ← [about_person] Wernher von Braun served as the first director of 
- ← [about_person] Before joining NASA, Wernher von Braun worked on G
- ← [designed_by] Saturn V
- ← [involves_person] After World War II, the United States recruited Ge
- ← [led_by] During World War II, Wernher von Braun led the dev
- ← [mentions_person] Saturn V was designed by Wernher von Braun’s team 

**Apollo 11** (11 connections)
- → [crewed_by] Buzz Aldrin
- → [crewed_by] Neil Armstrong
- → [crewed_by] Michael Collins
- → [launched_by] Saturn V
- → [launched_from] Kennedy Space Center
- → [launched_on] July 16, 1969
- ← [about_mission] Apollo 11 launched from Kennedy Space Center in Fl
- ← [about_mission] Apollo 11 launched atop a Saturn V rocket on July 
- ← [about_mission] The Lunar Module Eagle separated from the command 
- ← [about_mission] Buzz Aldrin joined Neil Armstrong on the lunar sur
- ← [spoken_during] That's one small step for man, one giant leap for mankind.

**Sputnik** (5 connections)
- → [launched_by] Soviet Union
- → [triggered] Space Race
- ← [about_satellite] On October 4, 1957, the Soviet Union launched Sput
- ← [motivated_by] In response to Sputnik, President Dwight D. Eisenh
- ← [motivated_by] NASA (National Aeronautics and Space Administration)

**Korolev** (7 connections)
- → [masterminded] Soviet space program
- → [oversaw_mission] Vostok 1
- → [publicly_referred_to_as] Chief Designer
- ← [about_person] Sergei Pavlovich Korolev personally oversaw the Vo
- ← [about_person] During his lifetime, Sergei Pavlovich Korolev's id
- ← [about_person] Sergei Pavlovich Korolev was the lead Soviet rocke
- ← [identity_was] Chief Designer

**Saturn V** (8 connections)
- → [designed_by] Wernher von Braun
- → [developed_at] Marshall Space Flight Center
- → [launched_missions_for] Apollo program
- → [launched_payload] Skylab
- → [operated_by] NASA
- ← [about_technology] Saturn V was designed by Wernher von Braun’s team 
- ← [launched_by] Apollo 11
- ← [used_launch_vehicle] Apollo 11 launched atop a Saturn V rocket on July 

---
## 02-broad-search-rich-edges
**Date:** 2026-04-10 20:00 UTC
**Notes:** Prompt changes: 1) instruct one broad search instead of per-entity searches, 2) explicit hierarchy edges (part_of, member_of, located_at), 3) expanded entity types, 4) discourage 'about' as edge label

### Scores
| Metric | Value |
|--------|-------|
| Expected edges | **10/14** |
| Anti-patterns | **0/3** (lower=better) |
| Total graph connections | **45** |
| Recall with context | **6/6** |
| Recall total nodes cited | **36** |

### Expected Edges
- ✓ von Braun --[*direct*]--> Marshall
- ✓ von Braun --[*develop|led|V-2|worked*]--> V-2
- ✗ von Braun --[*recruit|paperclip*]--> Paperclip
- ✓ Apollo 11 --[*crew*]--> Armstrong
- ✓ Apollo 11 --[*crew*]--> Aldrin
- ✓ Apollo 11 --[*crew*]--> Collins
- ✗ Apollo 11 --[*part_of|program*]--> Apollo
- ✓ Apollo 11 --[*launch*]--> Kennedy
- ✓ Sputnik --[*launch*]--> Soviet
- ✓ Sputnik --[*trigger*]--> Space Race
- ✓ Korolev --[*known|alias|referred|designer*]--> Chief Designer
- ✓ Korolev --[*led|master|architect|program*]--> Soviet
- ✗ Saturn V --[*design*]--> von Braun|Braun
- ✗ Saturn V --[*launch*]--> Apollo

### Anti-patterns
- ✓ Two edges between von Braun and Marshall with synonymous labels
- ✓ launched_on edge targeting a note instead of entity
- ✓ Artifact with led_by edge (should be person→led→artifact)

### Graph Probes
**Wernher von Braun** (9 connections)
- → [directed] Marshall Space Flight Center
- → [led_development_of] V-2 rocket
- → [surrendered_to] American forces
- → [worked_on] Redstone (rocket)
- → [worked_on] PGM-19 Jupiter
- ← [led_by] Von Braun's rocket team
- ← [mentions] During World War II, Wernher von Braun led the dev
- ← [mentions] Dr. Wernher von Braun served as the first director
- ← [mentions] After World War II, the United States recruited Ge

**Apollo 11** (14 connections)
- → [conducted_by] NASA
- → [launched_from] Kennedy Space Center
- → [launched_on] July 16, 1969
- → [launched_with] Saturn V
- → [moonwalk_date] July 20, 1969
- ← [command_module_of] Columbia (Apollo 11 Command Module)
- ← [crew_member_of] Buzz Aldrin
- ← [crew_member_of] Neil Armstrong
- ← [crew_member_of] Michael Collins
- ← [enabled] Apollo program
- ← [lunar_module_of] Eagle (Apollo 11 Lunar Module)
- ← [mentions] Neil Armstrong became the first person to walk on 
- ← [mentions] Apollo 11 launched atop a Saturn V rocket on July 
- ← [spoken_during] That's one small step for man, one giant leap for mankind.

**Sputnik** (9 connections)
- → [launched_by] Soviet Union
- → [launched_on] October 4, 1957
- → [overseen_by] Sergei Pavlovich Korolev
- → [part_of] Soviet space program
- → [prompted] National Aeronautics and Space Act
- → [triggered] Space Race
- ← [mentions] On October 4, 1957, the Soviet Union launched Sput
- ← [mentions] In response to Sputnik, President Dwight D. Eisenh
- ← [president_of] John F. Kennedy

**Korolev** (8 connections)
- → [led] Soviet space program
- → [mission_overseen] Vostok 1
- → [publicly_known_as] Chief Designer
- ← [mentions] On October 4, 1957, the Soviet Union launched Sput
- ← [mentions] Cosmonaut Yuri Gagarin became the first human in s
- ← [mentions] Sergei Pavlovich Korolev was the lead Soviet rocke
- ← [overseen_by] Vostok 1
- ← [overseen_by] Sputnik 1

**Saturn V** (5 connections)
- → [designed_by] Marshall Space Flight Center
- → [developed_under_leadership_of] Wernher von Braun
- → [enabled] Apollo program
- → [launched] Skylab
- ← [mentions] Saturn V was designed by Wernher von Braun’s team 

---
