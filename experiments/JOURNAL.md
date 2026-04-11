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
