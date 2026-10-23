# Ingest Quality Experiments

Systematic evaluation of ingest prompt engineering changes.

**Scoring:**
- Expected edges: how many key relationships were correctly captured
- Anti-patterns: how many known problems are present (lower = better)
- Recall with context: how many questions returned cited nodes

**Note:** Experiments 01–03 used the v1 dataset (12 snippets, ~250 chars each, 14 expected edges).
Future experiments use the v2 dataset (16 dense snippets, ~600 chars each, 25 expected edges,
5 anti-patterns including alias resolution checks). Results are not directly comparable across versions.

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
## 04-post-dream-improvements
**Date:** 2026-04-11 13:59 UTC
**Notes:** Hybrid find_similar, judgment-based dedup, entity-only batches, content-filter-safe snippets
**Data:** 16 space + 14 renaissance snippets, 9 questions, 20 probes

### Scores
| Metric | Value |
|--------|-------|
| Space edges | **10/25** |
| Renaissance edges | **4/19** |
| Combined edges | **14/44** |
| Intra-domain anti-patterns | **1/6** (lower=better) |
| Cross-domain leaks | **0/8** (lower=better) |
| Total graph connections | **176** |
| Recall with context | **9/9** |
| Recall total nodes cited | **38** |

### Space Race Expected Edges
- ✗ Tsiolkovsky --[*influenc|inspir*]--> Oberth
- ✗ Oberth --[*mentor|inspir|taught*]--> Braun
- ✗ Braun --[*develop|led|direct|technical*]--> V-2|A-4
- ✗ Braun --[*recruit|paperclip|brought*]--> Paperclip
- ✗ Braun --[*direct|led|served*]--> Marshall
- ✗ Korolev --[*known|alias|referred|called|publicly*]--> Chief Designer
- ✓ Korolev --[*develop|design|led|creat*]--> R-7
- ✗ Korolev --[*overs|monitor|led|launch*]--> Sputnik
- ✓ Korolev --[*overs|monitor*]--> Vostok
- ✗ Sputnik --[*trigger|led|caus|prompt|creat*]--> NASA|Space Race|ARPA
- ✗ Explorer --[*discover|detect|found|reveal*]--> Van Allen
- ✓ Apollo 11 --[*crew|command|pilot|member*]--> Armstrong
- ✓ Apollo 11 --[*crew|pilot|member*]--> Aldrin
- ✓ Apollo 11 --[*crew|pilot|member*]--> Collins
- ✓ Apollo 11 --[*launch|atop|used|carried*]--> Saturn V
- ✓ Apollo 1 --[*kill|died|casualt|victim|crew|fire*]--> Grissom
- ✓ Apollo 1 --[*kill|died|casualt|victim|crew|fire*]--> White
- ✗ Grumman --[*built|construct|develop|manufactur*]--> Lunar Module|LM
- ✗ North American --[*built|construct|develop|manufactur*]--> Command|CSM|Service Module
- ✓ MIT --[*develop|built|creat|design*]--> Guid|Computer|AGC
- ✗ Katherine Johnson --[*calculat|comput|trajectory|verif*]--> trajectory|Apollo|Glenn|Shepard|Freedom
- ✗ Margaret Hamilton --[*led|develop|wrote|coin|software*]--> software|Apollo|flight
- ✓ Korolev --[*rival|feud|conflict|disagree*]--> Glushko
- ✗ Armstrong --[*command|flew|pilot|crew*]--> Gemini
- ✗ Saturn V --[*design|develop|built|managed*]--> Marshall|Braun

### Renaissance Expected Edges
- ✗ Cimabue --[*taught|mentor|teacher|train|discover*]--> Giotto
- ✗ Cosimo --[*patron|commission|support|fund*]--> Brunelleschi|Donatello|San Lorenzo
- ✗ Lorenzo --[*patron|commission|support|fund|establish*]--> Botticelli|Michelangelo|sculpture garden
- ✗ Lorenzo --[*known|called|nickname|alias*]--> Magnifico|Magnificent
- ✗ Verrocchio --[*taught|train|mentor|workshop|master*]--> Leonardo
- ✗ Verrocchio --[*taught|train|mentor|workshop|master*]--> Botticelli|Perugino
- ✗ Perugino --[*taught|train|mentor*]--> Raphael|Raffaello
- ✗ Brunelleschi --[*discover|invent|demonstrat|pioneer|develop*]--> perspective
- ✗ Alberti --[*codif|wrote|publish|formal|theoriz*]--> perspective|Pictura
- ✓ Brunelleschi --[*design|built|construct|engineer*]--> dome|Florence Cathedral|Santa Maria|Duomo
- ✗ Bramante --[*design|commission|plan|began*]--> St. Peter|Peter's|Basilica
- ✗ Michelangelo --[*design|continu|complet|took over*]--> St. Peter|Peter's|dome
- ✓ Michelangelo --[*paint|creat|commission|fresco*]--> Sistine|ceiling|Genesis
- ✓ Raphael --[*paint|creat*]--> School of Athens|Stanze|Vatican
- ✗ Julius --[*commission*]--> Michelangelo|Sistine|Raphael|Bramante|St. Peter
- ✗ Antonello --[*brought|introduc|transmit|learn*]--> oil|Venice|Bellini
- ✓ Savonarola --[*denounc|oppos|preach|attack|critic*]--> Medici|secular|luxury|pagan
- ✗ Michelangelo --[*known|called|nickname|alias*]--> Divino|Divine
- ✗ Donatello --[*known|called|born|real name*]--> Donato|Bardi

### Intra-Domain Anti-patterns
- ✓ SPACE: Korolev and 'Chief Designer' exist as separate entities with no connecting edge
- ✓ SPACE: Baikonur and Tyuratam exist as separate entities with no connecting edge
- ✓ SPACE: Multiple edges between von Braun and Marshall with synonymous labels
- ✓ RENAISSANCE: Donatello and 'Donato di Niccolò' exist as separate entities with no connecting edge
- ✓ RENAISSANCE: Lorenzo and 'Il Magnifico' exist as separate entities with no connecting edge
- ⚠ RENAISSANCE: Multiple edges between Michelangelo and Sistine Chapel with synonymous labels

### Cross-Domain Isolation
- ✓ CROSS: Spurious edge between von Braun and Michelangelo
- ✓ CROSS: Spurious edge between Apollo 11 and Renaissance entity
- ✓ CROSS: Spurious edge between Saturn V and Renaissance entity
- ✓ CROSS: Spurious edge between Korolev and Renaissance artist
- ✓ CROSS: Spurious edge between Sputnik and Renaissance entity
- ✓ CROSS: Spurious edge between Bramante and Space Race entity
- ✓ CROSS: Spurious edge between Verrocchio and Space Race entity
- ✓ CROSS: Spurious edge between Botticelli and Space Race entity

### Graph Probes — Space Race
**Wernher von Braun** (2 connections)
- → [designed] Saturn V
- ← [describes] When Sergei Pavlovich Korolev died on January 14, 

**Korolev** (18 connections)
- → [arrested_in] 1938 arrest of Sergei Korolev
- → [co_founded] GIRD (Group for the Study of Reactive Motion)
- → [designed] R-7 Semyorka
- → [developed] R-1 missile
- → [died_on] When Sergei Pavlovich Korolev died on January 14, 
- → [feuded_with] Valentin Glushko
- → [imprisoned_in] Kolyma
- → [led] Chief Designer (Soviet space program)
- → [led] Soviet missile program (post-WWII)
- → [monitored] Vostok 1
- → [studied] V-2 rocket
- → [transferred_to] Sharashka
- ← [describes] When Sergei Pavlovich Korolev died on January 14, 
- ← [describes] Sergei Pavlovich Korolev co-founded GIRD (Group fo
- ← [describes] As WWII ended, the United States and Soviet Union 
- ← [intervened_to_transfer] Soviet ballistic missile program
- ← [published_name_of] Pravda
- ← [succeeded] Vasily Mishin

**Apollo 11** (10 connections)
- → [crew_included] Edwin "Buzz" Aldrin
- → [crew_included] Neil Armstrong
- → [crew_included] Michael Collins
- → [launched_from] Launch Complex 39A
- → [launched_on] AS-506
- → [used_spacecraft] Columbia (Apollo 11 CSM)
- → [used_spacecraft] Eagle (Apollo 11 LM)
- ← [championed_by] Lunar orbit rendezvous (LOR)
- ← [describes] Apollo 11 launched on 16 Jul 1969 on Saturn V (AS-
- ← [launched] Saturn V

**Saturn V** (9 connections)
- → [has_designation] AS-506
- → [launched] Apollo 11
- ← [culminated_in] Two decades building Saturn V
- ← [describes] Apollo was described as the largest peacetime engi
- ← [describes] Apollo 11 launched on 16 Jul 1969 on Saturn V (AS-
- ← [launched] Apollo 8
- ← [part_of] S-II (Saturn V second stage)
- ← [part_of] S-IVB (Saturn V third stage)
- ← [part_of] S-IC (Saturn V first stage)

**V-2** (7 connections)
- → [launched_at] White Sands Proving Ground
- → [studied] 1945 death of Robert H. Goddard
- ← [copy_of] R-1 missile
- ← [describes] As WWII ended, the United States and Soviet Union 
- ← [developed_at] Goddard published papers
- ← [studied] Sergei Korolev
- ← [tested] Wernher von Braun

**Sputnik** (4 connections)
- → [had_mass_kg] Radio beacon signal (Sputnik 'beep')
- → [transmitted] Radio beacon signal (Sputnik 'beep')
- ← [describes] Korolev's R-7 Semyorka, first successfully tested 
- ← [launched] Sputnik 1 launch (4 Oct 1957)

**MIT Instrumentation Lab** (2 connections)
- → [led_by] Charles Stark Draper
- ← [developed_by] Apollo Guidance Computer (AGC)

**Operation Paperclip** (5 connections)
- → [conducted_by] United States
- → [relocated_personnel_to] United States
- → [relocated_personnel_to] Fort Bliss
- ← [conducted] United States
- ← [describes] As WWII ended, the United States and Soviet Union 

**Apollo 1** (5 connections)
- → [crew_included] Gus Grissom
- → [crew_included] Roger Chaffee
- → [crew_included] Ed White
- → [part_of] Apollo program
- ← [describes] On January 27, 1967, what was supposed to be a rou

**Explorer 1** (4 connections)
- → [carried_instrument] Cosmic ray detector (Explorer 1 instrument)
- ← [describes] The launch of Sputnik triggered a crisis of confid
- ← [launched] Explorer 1 launch (31 Jan 1958)
- ← [modified_from] Redstone (rocket)

### Graph Probes — Renaissance
**Michelangelo** (15 connections)
- → [created] Pope Clement VII
- → [created] The Last Judgment (Sistine Chapel)
- → [created] Sistine Chapel ceiling
- → [created] Sistine Chapel ceiling frescoes
- → [fled_from] Brancacci Chapel
- ← [competed_with] Raphael
- ← [describes] The Sistine Chapel's artistic history spans the am
- ← [describes] Raphael (Raffaello Sanzio da Urbino) trained in Pi
- ← [influenced_by] Raphael
- ← [involved_parties] Pope Clement VII
- ← [paid_tribute_to] Raphael
- ← [persuaded_to_return] Papal emissaries
- ← [persuaded_to_return] The Last Judgment (Sistine Chapel)
- ← [sent_emissaries_to] Pope Julius II
- ← [sent_emissaries_to] Pope Julius II

**Lorenzo de' Medici** (2 connections)
- → [same_as] Giulio de' Medici
- ← [born_as] Giulio de' Medici

**Verrocchio** (2 connections)
- ← [describes] Leonardo di ser Piero da Vinci, illegitimate son o
- ← [led_by] Verrocchio's workshop

**Brunelleschi** (12 connections)
- → [built] Brunelleschi's Dome (Dome of Santa Maria del Fiore)
- → [conducted] Brunelleschi's perspective demonstration (~1420)
- → [influenced] Linear perspective
- → [inspired] De Pictura (On Painting)
- → [rebuilt] Basilica of San Lorenzo
- → [won] Competition for Florence Cathedral dome commission
- ← [commissioned] Cosimo de' Medici (Cosimo il Vecchio)
- ← [dedicated_to] De Pictura (On Painting)
- ← [describes] Brunelleschi demonstrated linear perspective empir
- ← [describes] Brunelleschi demonstrated linear perspective empir
- ← [describes] Filippo Brunelleschi's dome for the Cathedral of S
- ← [lost_to] Lorenzo Ghiberti

**Leonardo** (25 connections)
- → [authored] Leonardo da Vinci notebooks
- → [based_in] Florence
- → [contributed_to] The Baptism of Christ (Verrocchio)
- → [created] Mona Lisa
- → [created] The Last Supper
- → [developed] Sfumato
- → [developed] Sfumato
- → [died_at] Château du Clos Lucé
- → [left_unfinished] Battle of Anghiari
- → [left_unfinished] Sforza Horse
- → [left_unfinished] Adoration of the Magi (Leonardo)
- → [moved_to] Milan
- → [moved_to] France
- → [served] Francis I of France
- → [served] Ludovico Sforza
- → [trained_at] Verrocchio's workshop
- → [trained_at] Verrocchio's workshop
- → [traveled_to] Florence
- → [traveled_to] Rome
- → [traveled_to] Venice
- ← [describes] Leonardo di ser Piero da Vinci, illegitimate son o
- ← [describes] Raphael (Raffaello Sanzio da Urbino) trained in Pi
- ← [describes] Andrea del Verrocchio’s bottega on the Via de' Agn
- ← [influenced_by] Raphael
- ← [paid_tribute_to] Raphael

**Raphael** (17 connections)
- → [competed_with] Michelangelo
- → [influenced_by] Michelangelo
- → [influenced_by] Leonardo di ser Piero da Vinci
- → [led] Raphael's workshop
- → [moved_to] Florence
- → [paid_tribute_to] Michelangelo
- → [paid_tribute_to] Leonardo di ser Piero da Vinci
- → [painted] Vatican Stanze (Raphael Rooms)
- → [painted] The School of Athens
- → [trained_at] Perugino's workshop (Perugia)
- → [used_technique] Sfumato
- ← [commissioned] Pope Julius II
- ← [commissioned] Pope Julius II
- ← [describes] Raphael (Raffaello Sanzio da Urbino) trained in Pi
- ← [describes] The Sistine Chapel's artistic history spans the am
- ← [describes] The Sistine Chapel's artistic history spans the am
- ← [painted] Papal emissaries

**Sistine Chapel** (8 connections)
- → [located_in] Brancacci Chapel
- ← [describes] The Sistine Chapel's artistic history spans the am
- ← [describes] The Sistine Chapel's artistic history spans the am
- ← [located_in] Sistine Chapel ceiling frescoes
- ← [located_in] Sistine Chapel ceiling
- ← [located_in] Sistine Chapel side-wall frescoes
- ← [located_in] Pope Clement VII
- ← [near] Vatican Stanze (Raphael Rooms)

**Bramante** (15 connections)
- → [born_in] Urbino
- → [built] St. Peter's Basilica (New)
- → [completed] Crossing piers (St. Peter's)
- → [demolished] St. Peter's Basilica (Old)
- → [designed] Greek cross plan
- → [designed] Double-shell dome structure
- → [influenced_by] Piero della Francesca
- → [influenced_by] Andrea Mantegna
- → [led] St. Peter's Basilica rebuilding (16th century)
- → [moved_to] Rome
- ← [describes] Donato Bramante, originally from Urbino and traine
- ← [describes] The Sistine Chapel's artistic history spans the am
- ← [directed] Pope Julius II
- ← [simplified_design_of] Drum (dome)
- ← [succeeded] Raphael

**Botticelli** (1 connections)
- → [created] Sistine Chapel side-wall frescoes

**Savonarola** (13 connections)
- → [arrived_in] Florence
- → [born_in] Ferrara
- → [challenged] Pope Alexander VI
- → [denounced] Secular humanism (Florentine Renaissance)
- → [denounced] Medici family
- → [excommunicated_in] Expulsion of the Medici from Florence (1494)
- → [member_of] Dominican Order
- → [preached_at] Florence Cathedral (Santa Maria del Fiore)
- → [rose_to_power_after] Death of Lorenzo de’ Medici (1492)
- ← [describes] Girolamo Savonarola, a Dominican friar from Ferrar
- ← [encouraged_by] Bonfire of the Vanities (Florence, 1497)
- ← [executed] Excommunication of Savonarola
- ← [implemented_by] Theocratic Republic of Florence (Savonarola)

---

## 06-baseline-gemma4
**Date:** 2026-10-13 01:49 UTC
**Notes:** Baseline with current local stack: reasoning=openai:gemma4-26b-a4b @ jetson:8082, embedding=harrier-oss-v1-0.6b @ jetson:8084
**Data:** 16 space + 14 renaissance snippets, 9 questions, 20 probes
**Scoring:** LLM-judged (not pattern-matched)

### Scores
| Metric | Value |
|--------|-------|
| Space relationships | **0/22** |
| Renaissance relationships | **0/19** |
| Combined relationships | **0/41** |
| Cross-domain isolation | **0/1** |
| Total graph connections | **0** |
| Recall with context | **0/9** |
| Recall total nodes cited | **0** |
| Total wall time | **11321s** |

### Latency
| Phase | n | min | median | mean | p95 | max | total |
|-------|---|-----|--------|------|-----|-----|-------|
| ingest | 30 | 2.0s | 110.08s | 354.91s | 1801.2s | 1801.21s | 10647.4s |
| recall | 9 | 23.49s | 23.77s | 23.84s | 24.57s | 24.57s | 214.52s |
| graph | 20 | 19.57s | 20.7s | 20.54s | 20.89s | 21.19s | 410.81s |

### Space Race Relationships
- ✗ Tsiolkovsky's theoretical work inspired or influenced Oberth
  - LLM call failed: Set the `OPENAI_API_KEY` environment variable or pass it via `OpenAIProvider(api_key=...)` to use the OpenAI provider. To try Pydantic AI without an API key, use the built-in test model: `Agent('test')`. See https://pydantic.dev/docs/ai/guides/testing/
- ✗ Oberth mentored or inspired von Braun
  - LLM call failed: Set the `OPENAI_API_KEY` environment variable or pass it via `OpenAIProvider(api_key=...)` to use the OpenAI provider. To try Pydantic AI without an API key, use the built-in test model: `Agent('test')`. See https://pydantic.dev/docs/ai/guides/testing/
- ✗ Von Braun developed or led the development of the V-2 rocket
  - LLM call failed: Set the `OPENAI_API_KEY` environment variable or pass it via `OpenAIProvider(api_key=...)` to use the OpenAI provider. To try Pydantic AI without an API key, use the built-in test model: `Agent('test')`. See https://pydantic.dev/docs/ai/guides/testing/
- ✗ Von Braun was recruited to the US through Operation Paperclip
  - LLM call failed: Set the `OPENAI_API_KEY` environment variable or pass it via `OpenAIProvider(api_key=...)` to use the OpenAI provider. To try Pydantic AI without an API key, use the built-in test model: `Agent('test')`. See https://pydantic.dev/docs/ai/guides/testing/
- ✗ Von Braun directed or led Marshall Space Flight Center
  - LLM call failed: Set the `OPENAI_API_KEY` environment variable or pass it via `OpenAIProvider(api_key=...)` to use the OpenAI provider. To try Pydantic AI without an API key, use the built-in test model: `Agent('test')`. See https://pydantic.dev/docs/ai/guides/testing/
- ✗ Korolev was known as or connected to 'the Chief Designer'
  - LLM call failed: Set the `OPENAI_API_KEY` environment variable or pass it via `OpenAIProvider(api_key=...)` to use the OpenAI provider. To try Pydantic AI without an API key, use the built-in test model: `Agent('test')`. See https://pydantic.dev/docs/ai/guides/testing/
- ✗ Korolev developed or designed the R-7 rocket
  - LLM call failed: Set the `OPENAI_API_KEY` environment variable or pass it via `OpenAIProvider(api_key=...)` to use the OpenAI provider. To try Pydantic AI without an API key, use the built-in test model: `Agent('test')`. See https://pydantic.dev/docs/ai/guides/testing/
- ✗ Korolev oversaw or was involved in the Sputnik launch
  - LLM call failed: Set the `OPENAI_API_KEY` environment variable or pass it via `OpenAIProvider(api_key=...)` to use the OpenAI provider. To try Pydantic AI without an API key, use the built-in test model: `Agent('test')`. See https://pydantic.dev/docs/ai/guides/testing/
- ✗ Korolev oversaw or monitored the Vostok 1 / Gagarin flight
  - LLM call failed: Set the `OPENAI_API_KEY` environment variable or pass it via `OpenAIProvider(api_key=...)` to use the OpenAI provider. To try Pydantic AI without an API key, use the built-in test model: `Agent('test')`. See https://pydantic.dev/docs/ai/guides/testing/
- ✗ Sputnik's launch triggered or led to the creation of NASA
  - LLM call failed: Set the `OPENAI_API_KEY` environment variable or pass it via `OpenAIProvider(api_key=...)` to use the OpenAI provider. To try Pydantic AI without an API key, use the built-in test model: `Agent('test')`. See https://pydantic.dev/docs/ai/guides/testing/
- ✗ Explorer 1 discovered or detected the Van Allen radiation belts
  - LLM call failed: Set the `OPENAI_API_KEY` environment variable or pass it via `OpenAIProvider(api_key=...)` to use the OpenAI provider. To try Pydantic AI without an API key, use the built-in test model: `Agent('test')`. See https://pydantic.dev/docs/ai/guides/testing/
- ✗ Apollo 11's crew included Armstrong, Aldrin, and Collins
  - LLM call failed: Set the `OPENAI_API_KEY` environment variable or pass it via `OpenAIProvider(api_key=...)` to use the OpenAI provider. To try Pydantic AI without an API key, use the built-in test model: `Agent('test')`. See https://pydantic.dev/docs/ai/guides/testing/
- ✗ Apollo 11 was launched on a Saturn V rocket
  - LLM call failed: Set the `OPENAI_API_KEY` environment variable or pass it via `OpenAIProvider(api_key=...)` to use the OpenAI provider. To try Pydantic AI without an API key, use the built-in test model: `Agent('test')`. See https://pydantic.dev/docs/ai/guides/testing/
- ✗ The Apollo 1 fire killed Grissom, White, and Chaffee
  - LLM call failed: Set the `OPENAI_API_KEY` environment variable or pass it via `OpenAIProvider(api_key=...)` to use the OpenAI provider. To try Pydantic AI without an API key, use the built-in test model: `Agent('test')`. See https://pydantic.dev/docs/ai/guides/testing/
- ✗ Grumman built the Lunar Module
  - LLM call failed: Set the `OPENAI_API_KEY` environment variable or pass it via `OpenAIProvider(api_key=...)` to use the OpenAI provider. To try Pydantic AI without an API key, use the built-in test model: `Agent('test')`. See https://pydantic.dev/docs/ai/guides/testing/
- ✗ North American Aviation built the Command/Service Module
  - LLM call failed: Set the `OPENAI_API_KEY` environment variable or pass it via `OpenAIProvider(api_key=...)` to use the OpenAI provider. To try Pydantic AI without an API key, use the built-in test model: `Agent('test')`. See https://pydantic.dev/docs/ai/guides/testing/
- ✗ The MIT Instrumentation Lab developed the Apollo Guidance Computer
  - LLM call failed: Set the `OPENAI_API_KEY` environment variable or pass it via `OpenAIProvider(api_key=...)` to use the OpenAI provider. To try Pydantic AI without an API key, use the built-in test model: `Agent('test')`. See https://pydantic.dev/docs/ai/guides/testing/
- ✗ Katherine Johnson calculated trajectories for Mercury or Apollo
  - LLM call failed: Set the `OPENAI_API_KEY` environment variable or pass it via `OpenAIProvider(api_key=...)` to use the OpenAI provider. To try Pydantic AI without an API key, use the built-in test model: `Agent('test')`. See https://pydantic.dev/docs/ai/guides/testing/
- ✗ Margaret Hamilton led the Apollo software team or coined 'software engineering'
  - LLM call failed: Set the `OPENAI_API_KEY` environment variable or pass it via `OpenAIProvider(api_key=...)` to use the OpenAI provider. To try Pydantic AI without an API key, use the built-in test model: `Agent('test')`. See https://pydantic.dev/docs/ai/guides/testing/
- ✗ Korolev and Glushko had a rivalry or feud over engine design
  - LLM call failed: Set the `OPENAI_API_KEY` environment variable or pass it via `OpenAIProvider(api_key=...)` to use the OpenAI provider. To try Pydantic AI without an API key, use the built-in test model: `Agent('test')`. See https://pydantic.dev/docs/ai/guides/testing/
- ✗ Armstrong commanded Gemini 8 before Apollo 11
  - LLM call failed: Set the `OPENAI_API_KEY` environment variable or pass it via `OpenAIProvider(api_key=...)` to use the OpenAI provider. To try Pydantic AI without an API key, use the built-in test model: `Agent('test')`. See https://pydantic.dev/docs/ai/guides/testing/
- ✗ Saturn V was designed or developed at/by Marshall or von Braun's team
  - LLM call failed: Set the `OPENAI_API_KEY` environment variable or pass it via `OpenAIProvider(api_key=...)` to use the OpenAI provider. To try Pydantic AI without an API key, use the built-in test model: `Agent('test')`. See https://pydantic.dev/docs/ai/guides/testing/

### Renaissance Relationships
- ✗ Cimabue discovered or taught Giotto
  - LLM call failed: Set the `OPENAI_API_KEY` environment variable or pass it via `OpenAIProvider(api_key=...)` to use the OpenAI provider. To try Pydantic AI without an API key, use the built-in test model: `Agent('test')`. See https://pydantic.dev/docs/ai/guides/testing/
- ✗ Cosimo de' Medici patronized or commissioned Brunelleschi or Donatello
  - LLM call failed: Set the `OPENAI_API_KEY` environment variable or pass it via `OpenAIProvider(api_key=...)` to use the OpenAI provider. To try Pydantic AI without an API key, use the built-in test model: `Agent('test')`. See https://pydantic.dev/docs/ai/guides/testing/
- ✗ Lorenzo de' Medici (Il Magnifico) patronized Botticelli or Michelangelo
  - LLM call failed: Set the `OPENAI_API_KEY` environment variable or pass it via `OpenAIProvider(api_key=...)` to use the OpenAI provider. To try Pydantic AI without an API key, use the built-in test model: `Agent('test')`. See https://pydantic.dev/docs/ai/guides/testing/
- ✗ Lorenzo de' Medici was known as 'Il Magnifico'
  - LLM call failed: Set the `OPENAI_API_KEY` environment variable or pass it via `OpenAIProvider(api_key=...)` to use the OpenAI provider. To try Pydantic AI without an API key, use the built-in test model: `Agent('test')`. See https://pydantic.dev/docs/ai/guides/testing/
- ✗ Verrocchio's workshop trained Leonardo
  - LLM call failed: Set the `OPENAI_API_KEY` environment variable or pass it via `OpenAIProvider(api_key=...)` to use the OpenAI provider. To try Pydantic AI without an API key, use the built-in test model: `Agent('test')`. See https://pydantic.dev/docs/ai/guides/testing/
- ✗ Verrocchio's workshop trained Botticelli or Perugino
  - LLM call failed: Set the `OPENAI_API_KEY` environment variable or pass it via `OpenAIProvider(api_key=...)` to use the OpenAI provider. To try Pydantic AI without an API key, use the built-in test model: `Agent('test')`. See https://pydantic.dev/docs/ai/guides/testing/
- ✗ Perugino trained or mentored Raphael
  - LLM call failed: Set the `OPENAI_API_KEY` environment variable or pass it via `OpenAIProvider(api_key=...)` to use the OpenAI provider. To try Pydantic AI without an API key, use the built-in test model: `Agent('test')`. See https://pydantic.dev/docs/ai/guides/testing/
- ✗ Brunelleschi discovered or demonstrated linear perspective
  - LLM call failed: Set the `OPENAI_API_KEY` environment variable or pass it via `OpenAIProvider(api_key=...)` to use the OpenAI provider. To try Pydantic AI without an API key, use the built-in test model: `Agent('test')`. See https://pydantic.dev/docs/ai/guides/testing/
- ✗ Alberti codified or wrote about perspective (De Pictura)
  - LLM call failed: Set the `OPENAI_API_KEY` environment variable or pass it via `OpenAIProvider(api_key=...)` to use the OpenAI provider. To try Pydantic AI without an API key, use the built-in test model: `Agent('test')`. See https://pydantic.dev/docs/ai/guides/testing/
- ✗ Brunelleschi designed or built the dome of Florence Cathedral
  - LLM call failed: Set the `OPENAI_API_KEY` environment variable or pass it via `OpenAIProvider(api_key=...)` to use the OpenAI provider. To try Pydantic AI without an API key, use the built-in test model: `Agent('test')`. See https://pydantic.dev/docs/ai/guides/testing/
- ✗ Bramante designed or began rebuilding St. Peter's Basilica
  - LLM call failed: Set the `OPENAI_API_KEY` environment variable or pass it via `OpenAIProvider(api_key=...)` to use the OpenAI provider. To try Pydantic AI without an API key, use the built-in test model: `Agent('test')`. See https://pydantic.dev/docs/ai/guides/testing/
- ✗ Michelangelo designed or continued the dome of St. Peter's
  - LLM call failed: Set the `OPENAI_API_KEY` environment variable or pass it via `OpenAIProvider(api_key=...)` to use the OpenAI provider. To try Pydantic AI without an API key, use the built-in test model: `Agent('test')`. See https://pydantic.dev/docs/ai/guides/testing/
- ✗ Michelangelo painted the Sistine Chapel ceiling
  - LLM call failed: Set the `OPENAI_API_KEY` environment variable or pass it via `OpenAIProvider(api_key=...)` to use the OpenAI provider. To try Pydantic AI without an API key, use the built-in test model: `Agent('test')`. See https://pydantic.dev/docs/ai/guides/testing/
- ✗ Raphael painted the School of Athens or the Vatican Stanze
  - LLM call failed: Set the `OPENAI_API_KEY` environment variable or pass it via `OpenAIProvider(api_key=...)` to use the OpenAI provider. To try Pydantic AI without an API key, use the built-in test model: `Agent('test')`. See https://pydantic.dev/docs/ai/guides/testing/
- ✗ Pope Julius II commissioned Michelangelo, Raphael, or Bramante
  - LLM call failed: Set the `OPENAI_API_KEY` environment variable or pass it via `OpenAIProvider(api_key=...)` to use the OpenAI provider. To try Pydantic AI without an API key, use the built-in test model: `Agent('test')`. See https://pydantic.dev/docs/ai/guides/testing/
- ✗ Antonello da Messina brought oil painting to Italy or Venice
  - LLM call failed: Set the `OPENAI_API_KEY` environment variable or pass it via `OpenAIProvider(api_key=...)` to use the OpenAI provider. To try Pydantic AI without an API key, use the built-in test model: `Agent('test')`. See https://pydantic.dev/docs/ai/guides/testing/
- ✗ Savonarola denounced or opposed the Medici
  - LLM call failed: Set the `OPENAI_API_KEY` environment variable or pass it via `OpenAIProvider(api_key=...)` to use the OpenAI provider. To try Pydantic AI without an API key, use the built-in test model: `Agent('test')`. See https://pydantic.dev/docs/ai/guides/testing/
- ✗ Michelangelo was known as 'Il Divino'
  - LLM call failed: Set the `OPENAI_API_KEY` environment variable or pass it via `OpenAIProvider(api_key=...)` to use the OpenAI provider. To try Pydantic AI without an API key, use the built-in test model: `Agent('test')`. See https://pydantic.dev/docs/ai/guides/testing/
- ✗ Donatello's real name was Donato di Niccolò di Betto Bardi
  - LLM call failed: Set the `OPENAI_API_KEY` environment variable or pass it via `OpenAIProvider(api_key=...)` to use the OpenAI provider. To try Pydantic AI without an API key, use the built-in test model: `Agent('test')`. See https://pydantic.dev/docs/ai/guides/testing/

### Cross-Domain Isolation
- ✗ There should be NO direct edge between any Space Race entity (von Braun, Korolev, Apollo, Saturn V, Sputnik, NASA) and any Renaissance entity (Michelangelo, Leonardo, Raphael, Bramante, Medici, Brunelleschi, Botticelli, Savonarola)
  - LLM call failed: Set the `OPENAI_API_KEY` environment variable or pass it via `OpenAIProvider(api_key=...)` to use the OpenAI provider. To try Pydantic AI without an API key, use the built-in test model: `Agent('test')`. See https://pydantic.dev/docs/ai/guides/testing/

### Graph Probes — Space Race
**Wernher von Braun** (0 connections)

**Korolev** (0 connections)

**Apollo 11** (0 connections)

**Saturn V** (0 connections)

**V-2** (0 connections)

**Sputnik** (0 connections)

**MIT Instrumentation Lab** (0 connections)

**Operation Paperclip** (0 connections)

**Apollo 1** (0 connections)

**Explorer 1** (0 connections)

### Graph Probes — Renaissance
**Michelangelo** (0 connections)

**Lorenzo de' Medici** (0 connections)

**Verrocchio** (0 connections)

**Brunelleschi** (0 connections)

**Leonardo** (0 connections)

**Raphael** (0 connections)

**Sistine Chapel** (0 connections)

**Bramante** (0 connections)

**Botticelli** (0 connections)

**Savonarola** (0 connections)

---

## 09-baseline-gemma4-plan
**Date:** 2026-10-20 01:39 UTC
**Notes:** Gemma4 clean baseline using validated IngestPlan and one application-controlled write; dream scheduler disabled
**Data:** 16 space + 14 renaissance snippets, 9 questions, 20 probes
**Scoring:** LLM-judged (not pattern-matched)
**Judge model:** Pi tier frontier: `zai/glm-5.3:max`

### Scores
| Metric | Value |
|--------|-------|
| Space relationships | **NOT SCORED** |
| Renaissance relationships | **NOT SCORED** |
| Combined relationships | **NOT SCORED** |
| Cross-domain isolation | **NOT SCORED** |
| Total graph connections | **0** |
| Recall with context | **0/9** |
| Recall errors | **7/9** |
| Recall total nodes cited | **0** |
| Total wall time | **39716s** |

### Latency
| Phase | n | min | median | mean | p95 | max | total |
|-------|---|-----|--------|------|-----|-----|-------|
| ingest_staging | 30 | 0.11s | 0.14s | 0.15s | 0.3s | 0.34s | 4.55s |
| pipeline_drain | 1 | 21457.0s | 21457.0s | 21457.0s | 21457.0s | 21457.0s | 21457.0s |
| ingest_total | 1 | 21461.59s | 21461.59s | 21461.59s | 21461.59s | 21461.59s | 21461.59s |
| recall | 9 | 12.98s | 23.78s | 33.65s | 90.84s | 90.84s | 302.88s |
| graph | 20 | 20.39s | 163.73s | 1076.16s | 2715.27s | 2715.29s | 21523.16s |

### Space Race Relationships
- NOT SCORED: Not scored: Space graph coverage is incomplete (0 lookup errors, 10 probes without node data).

### Renaissance Relationships
- NOT SCORED: Not scored: Renaissance graph coverage is incomplete (0 lookup errors, 10 probes without node data).

### Cross-Domain Isolation
- NOT SCORED: Not scored: cross-domain graph coverage is incomplete.

### Graph Probes — Space Race
**Wernher von Braun** — NO NODE DATA RETURNED BY PROBE

**Korolev** — NO NODE DATA RETURNED BY PROBE

**Apollo 11** — NO NODE DATA RETURNED BY PROBE

**Saturn V** — NO NODE DATA RETURNED BY PROBE

**V-2** — NO NODE DATA RETURNED BY PROBE

**Sputnik** — NO NODE DATA RETURNED BY PROBE

**MIT Instrumentation Lab** — NO NODE DATA RETURNED BY PROBE

**Operation Paperclip** — NO NODE DATA RETURNED BY PROBE

**Apollo 1** — NO NODE DATA RETURNED BY PROBE

**Explorer 1** — NO NODE DATA RETURNED BY PROBE

### Graph Probes — Renaissance
**Michelangelo** — NO NODE DATA RETURNED BY PROBE

**Lorenzo de' Medici** — NO NODE DATA RETURNED BY PROBE

**Verrocchio** — NO NODE DATA RETURNED BY PROBE

**Brunelleschi** — NO NODE DATA RETURNED BY PROBE

**Leonardo** — NO NODE DATA RETURNED BY PROBE

**Raphael** — NO NODE DATA RETURNED BY PROBE

**Sistine Chapel** — NO NODE DATA RETURNED BY PROBE

**Bramante** — NO NODE DATA RETURNED BY PROBE

**Botticelli** — NO NODE DATA RETURNED BY PROBE

**Savonarola** — NO NODE DATA RETURNED BY PROBE

---

## 14-recordref-gemma4-thinking-off
**Date:** 2026-10-22 13:16 UTC
**Notes:** Pydantic RecordRef schema with bounded strings and validation logging
**Data:** 16 space + 14 renaissance snippets, 9 questions, 20 probes
**Scoring:** LLM-judged (not pattern-matched)
**Judge model:** Pi tier cheap: `genetec-openai-responses/gpt-6-luna:medium`

### Scores
| Metric | Value |
|--------|-------|
| Space relationships | **NOT SCORED** |
| Renaissance relationships | **NOT SCORED** |
| Combined relationships | **NOT SCORED** |
| Cross-domain isolation | **NOT SCORED** |
| Total graph connections | **81** |
| Recall with context | **6/9** |
| Recall errors | **2/9** |
| Recall total nodes cited | **16** |
| Total wall time | **2433s** |

### Latency
| Phase | n | min | median | mean | p95 | max | total |
|-------|---|-----|--------|------|-----|-----|-------|
| ingest_staging | 30 | 0.12s | 0.14s | 0.15s | 0.21s | 0.21s | 4.43s |
| pipeline_drain | 1 | 2005.14s | 2005.14s | 2005.14s | 2005.14s | 2005.14s | 2005.14s |
| ingest_total | 1 | 2009.61s | 2009.61s | 2009.61s | 2009.61s | 2009.61s | 2009.61s |
| recall | 9 | 4.28s | 14.21s | 18.88s | 44.84s | 44.84s | 169.93s |
| graph | 20 | 7.76s | 11.17s | 12.51s | 15.9s | 40.93s | 250.15s |

### Space Race Relationships
- NOT SCORED: Not scored: Space graph coverage is incomplete (1 lookup error, 1 probe without node data).

### Renaissance Relationships
- NOT SCORED: Pi judge exited with status 127 using genetec-openai-responses/gpt-6-luna:medium: /usr/bin/env: ‘node’: No such file or directory

### Cross-Domain Isolation
- NOT SCORED: Not scored: cross-domain graph coverage is incomplete.

### Graph Probes — Space Race
**Wernher von Braun** (8 connections)
- → [influenced_by] Robert Goddard
- → [member_of] Verein für Raumschiffahrt
- ← [describes] Hermann Oberth's 1923 book 'Die Rakete zu den Plan
- ← [founded_by] Verein für Raumschiffahrt
- ← [mentored] Hermann Oberth
- ← [part_of] Operation Paperclip
- ← [worked_with] Walter Dornberger
- ← [worked_with] Helmut Gröttrup

**Korolev** (7 connections)
- → [describes] Sergei Korolev co-founded GIRD (Group for the Stud
- → [led] Soviet ballistic missile program
- → [member_of] GIRD
- ← [designed_by] R-7 Semyorka
- ← [feuded_with] Valentin Glushko
- ← [helped] Andrei Tupolev
- ← [successor_of] Vasily Mishin

**Apollo 11** (3 connections)
- → [part_of] Apollo program
- ← [calculated_trajectory_for] Katherine Johnson
- ← [developed_software_for] Margaret Hamilton

**Saturn V** — LOOKUP FAILED: Could not resolve 'Saturn V' after 3 recall attempts: POST /recall returned HTTP 502

**V-2** (2 connections)
- ← [influenced] Robert Goddard
- ← [is_copy_of] R-1 rocket

**Sputnik** (1 connections)
- → [launched_from] Baikonur Cosmodrome

**MIT Instrumentation Lab** (1 connections)
- → [designed_by] Apollo 8

**Operation Paperclip** (2 connections)
- → [part_of] Wernher von Braun
- ← [describes] Following WWII, the US and USSR competed for Germa

**Apollo 1** (4 connections)
- → [part_of] Apollo program
- ← [died_in] Gus Grissom
- ← [died_in] Roger Chaffee
- ← [died_in] Ed White

**Explorer 1** (1 connections)
- → [launched_by] Jupiter-C

### Graph Probes — Renaissance
**Michelangelo** (11 connections)
- → [associated_with] Donato Bramante
- → [created] The Last Judgment
- → [created] Lorenzo de' Medici
- → [created] Pietà
- → [created] Vatican Stanze
- → [created] Sistine Chapel ceiling
- → [describes] Bramante's 1506 design for St. Peter's Basilica fe
- → [designed] St. Peter's Basilica
- → [trained_by] Domenico Ghirlandaio
- ← [influenced_by] Raphael's training and influences: learned in Piet
- ← [painted_by] Lorenzo de' Medici

**Lorenzo de' Medici** (6 connections)
- → [child_of] Cosimo de' Medici
- → [hosted] Angelo Poliziano
- → [sibling_of] Piero de' Medici
- → [supported] Andrea del Verrocchio
- → [supported] Sandro Botticelli
- ← [describes] Angelo Poliziano

**Verrocchio** (7 connections)
- → [trained] Domenico Ghirlandaio
- → [trained] Sandro Botticelli
- → [trained] Verrocchio's Bottega
- → [trained] Leonardo da Vinci
- → [trained] Raphael
- → [trained] Pietro Perugino
- ← [supported] Lorenzo de' Medici

**Brunelleschi** (5 connections)
- → [competed_against] Lorenzo Ghiberti
- → [designed] Cathedral of Santa Maria del Fiore
- → [pioneered] linear perspective
- ← [dedicated_to] Leon Battista Alberti
- ← [describes] Designed the revolutionary double-shell dome for t

**Leonardo** (11 connections)
- → [created] Sforza Horse
- → [created] Adoration of the Magi
- → [created] The Last Supper
- → [created] Mona Lisa
- → [developed] sfumato
- → [died_at] Francis I
- → [served] Battle of Anghiari
- → [served] Ludovico Sforza
- ← [describes] Leonardo's notebooks, written in mirror script, co
- ← [describes] Leonardo developed sfumato, a technique of layerin
- ← [trained] Andrea del Verrocchio

**Raphael** (5 connections)
- ← [assistant_of] Giulio Romano
- ← [created] School of Athens
- ← [influenced_by] Raphael's training and influences: learned in Piet
- ← [trained] Andrea del Verrocchio
- ← [trained] Verrocchio's Bottega

**Sistine Chapel** (2 connections)
- → [commissioned] Pope Sixtus IV
- ← [located_in] The Last Judgment

**Bramante** (2 connections)
- → [designed] St. Peter's Basilica
- ← [associated_with] Michelangelo

**Botticelli** (2 connections)
- ← [supported] Lorenzo de' Medici
- ← [trained] Andrea del Verrocchio

**Savonarola** (1 connections)
- → [ruled] Piero de' Medici

---

## 15-ingest-name-refs-gemma4-thinking-off
**Date:** 2026-10-22 21:29 UTC
**Notes:** Name references and output diagnostics after run 14 failures
**Data:** 16 space + 14 renaissance snippets, 9 questions, 20 probes
**Scoring:** LLM-judged (not pattern-matched)
**Judge model:** Pi tier cheap: `genetec-openai-responses/gpt-6-luna:medium`

### Scores
| Metric | Value |
|--------|-------|
| Space relationships | **NOT SCORED** |
| Renaissance relationships | **NOT SCORED** |
| Combined relationships | **NOT SCORED** |
| Cross-domain isolation | **NOT SCORED** |
| Total graph connections | **2** |
| Recall with context | **2/9** |
| Recall errors | **5/9** |
| Recall total nodes cited | **2** |
| Total wall time | **5227s** |

### Latency
| Phase | n | min | median | mean | p95 | max | total |
|-------|---|-----|--------|------|-----|-----|-------|
| ingest_staging | 30 | 0.13s | 0.14s | 0.15s | 0.19s | 0.21s | 4.49s |
| pipeline_drain | 1 | 4467.39s | 4467.39s | 4467.39s | 4467.39s | 4467.39s | 4467.39s |
| ingest_total | 1 | 4471.91s | 4471.91s | 4471.91s | 4471.91s | 4471.91s | 4471.91s |
| recall | 9 | 4.46s | 41.35s | 32.1s | 58.06s | 58.06s | 288.93s |
| graph | 20 | 9.3s | 40.92s | 39.3s | 46.24s | 51.23s | 786.05s |

### Space Race Relationships
- NOT SCORED: Not scored: Space graph coverage is incomplete (9 lookup errors, 9 probes without node data).

### Renaissance Relationships
- NOT SCORED: Not scored: Renaissance graph coverage is incomplete (10 lookup errors, 10 probes without node data).

### Cross-Domain Isolation
- NOT SCORED: Not scored: cross-domain graph coverage is incomplete.

### Graph Probes — Space Race
**Wernher von Braun** — LOOKUP FAILED: Could not resolve 'Wernher von Braun' after 3 recall attempts: POST /recall returned HTTP 502

**Korolev** — LOOKUP FAILED: Could not resolve 'Korolev' after 3 recall attempts: POST /recall returned HTTP 502

**Apollo 11** — LOOKUP FAILED: Could not resolve 'Apollo 11' after 3 recall attempts: POST /recall returned no cited entity matching 'Apollo 11'

**Saturn V** — LOOKUP FAILED: Could not resolve 'Saturn V' after 3 recall attempts: POST /recall returned HTTP 502

**V-2** — LOOKUP FAILED: Could not resolve 'V-2' after 3 recall attempts: POST /recall returned HTTP 502

**Sputnik** (2 connections)
- → [launched_from] Baikonur Cosmodrome
- ← [launched] R-7 Semyorka

**MIT Instrumentation Lab** — LOOKUP FAILED: Could not resolve 'MIT Instrumentation Lab' after 3 recall attempts: POST /recall returned HTTP 502

**Operation Paperclip** — LOOKUP FAILED: Could not resolve 'Operation Paperclip' after 3 recall attempts: POST /recall returned HTTP 502

**Apollo 1** — LOOKUP FAILED: Could not resolve 'Apollo 1' after 3 recall attempts: POST /recall returned HTTP 502

**Explorer 1** — LOOKUP FAILED: Could not resolve 'Explorer 1' after 3 recall attempts: POST /recall returned HTTP 502

### Graph Probes — Renaissance
**Michelangelo** — LOOKUP FAILED: Could not resolve 'Michelangelo' after 3 recall attempts: POST /recall returned HTTP 502

**Lorenzo de' Medici** — LOOKUP FAILED: Could not resolve "Lorenzo de' Medici" after 3 recall attempts: POST /recall returned HTTP 502

**Verrocchio** — LOOKUP FAILED: Could not resolve 'Verrocchio' after 3 recall attempts: POST /recall returned HTTP 502

**Brunelleschi** — LOOKUP FAILED: Could not resolve 'Brunelleschi' after 3 recall attempts: POST /recall returned HTTP 502

**Leonardo** — LOOKUP FAILED: Could not resolve 'Leonardo' after 3 recall attempts: POST /recall returned HTTP 502

**Raphael** — LOOKUP FAILED: Could not resolve 'Raphael' after 3 recall attempts: POST /recall returned HTTP 502

**Sistine Chapel** — LOOKUP FAILED: Could not resolve 'Sistine Chapel' after 3 recall attempts: POST /recall returned HTTP 502

**Bramante** — LOOKUP FAILED: Could not resolve 'Bramante' after 3 recall attempts: POST /recall returned HTTP 502

**Botticelli** — LOOKUP FAILED: Could not resolve 'Botticelli' after 3 recall attempts: POST /recall returned HTTP 502

**Savonarola** — LOOKUP FAILED: Could not resolve 'Savonarola' after 3 recall attempts: POST /recall returned HTTP 502

---
