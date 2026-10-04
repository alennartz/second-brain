#!/usr/bin/env python3
"""
Test scenario: Two independent knowledge domains ingested into the same graph.

Domain A — The Space Age (1903-1969): Theoretical physics → wartime rocketry →
Cold War politics → the Moon landing. Multi-hop chains, heavy aliasing, dense
ingest segments.

Domain B — The Florentine Renaissance (1267-1590): Byzantine art → artistic
revolution → Medici patronage → High Renaissance → St. Peter's. Workshop lineages,
patronage chains, technique transmission, heavy entity aliasing.

The two domains share zero entities. After ingesting both, we evaluate:
  1. Intra-domain graph quality (expected edges, entity resolution)
  2. Inter-domain isolation (no spurious cross-connections)
  3. Recall quality on chain-reasoning questions from each domain
"""

import json
import sys
import time

import httpx

BASE = "http://localhost:8000"

# ══════════════════════════════════════════════════════════════════════════════
# DOMAIN A: THE SPACE AGE
# ══════════════════════════════════════════════════════════════════════════════

SPACE_SNIPPETS = [
    # 1. Tsiolkovsky — theoretical foundations (sets up the deepest chain)
    "Konstantin Tsiolkovsky, a self-taught Russian schoolteacher from Kaluga, published "
    "'The Exploration of Cosmic Space by Means of Reaction Devices' in 1903 — the same "
    "year as the Wright brothers' first flight. His work derived the fundamental rocket "
    "equation relating exhaust velocity to achievable delta-v, and he proposed multi-stage "
    "rockets, liquid hydrogen and oxygen propellant, and even space stations decades before "
    "any of it was technically feasible. Tsiolkovsky never built a rocket himself, but his "
    "theoretical framework directly inspired the next generation: Hermann Oberth in Romania "
    "read his work and built upon it, while in the Soviet Union a young engineering student "
    "named Sergei Korolev devoured Tsiolkovsky's writings and began dreaming of spaceflight.",
    # 2. Oberth and the German rocket society (bridges theory → practice)
    "Hermann Oberth's 1923 book 'Die Rakete zu den Planetenräumen' (The Rocket into "
    "Planetary Space) provided the first rigorous mathematical treatment of rocketry in "
    "Western Europe. It inspired the formation of the Verein für Raumschiffahrt (VfR) — "
    "the German Society for Space Travel — in 1927. Among its youngest members was an "
    "18-year-old aristocrat named Wernher von Braun, who joined in 1930. Oberth personally "
    "mentored von Braun, who later recalled that reading Oberth's book as a teenager was "
    "the moment he decided to devote his life to rocketry. The VfR's amateur experiments "
    "attracted the attention of the German military, and by 1932 the Army had recruited "
    "von Braun to develop rockets as weapons.",
    # 3. Goddard's parallel track (American theoretical chain)
    "Robert Goddard launched the world's first liquid-fueled rocket on March 16, 1926, "
    "from his Aunt Effie's farm in Auburn, Massachusetts. The flight lasted 2.5 seconds "
    "and reached 41 feet. Funded by the Smithsonian Institution and later by Charles "
    "Lindbergh's connections to the Guggenheim family, Goddard worked in near-total secrecy "
    "in Roswell, New Mexico throughout the 1930s, developing gyroscopic stabilization, vane "
    "steering, and turbopump-fed engines. He filed 214 patents. The German rocket engineers "
    "at Peenemünde studied Goddard's published papers closely — after the war, von Braun "
    "reportedly said 'Goddard was ahead of us all.' Goddard died in 1945, never knowing "
    "how directly his work had influenced the V-2.",
    # 4. V-2 development at Peenemünde (dense, many entities, moral complexity)
    "The Army Research Center at Peenemünde on Germany's Baltic coast became the birthplace "
    "of the space age, though it was conceived as a weapons facility. Under military commander "
    "Walter Dornberger and technical director Wernher von Braun, the team developed the A-4 "
    "rocket — later renamed V-2 (Vergeltungswaffe 2, 'Vengeance Weapon 2') by the German "
    "propaganda ministry. The A-4 first reached space on October 3, 1942, crossing the "
    "Kármán line at 100 km altitude. By 1944, thousands were being produced at the "
    "underground Mittelwerk factory in the Harz Mountains using forced labor from the "
    "Mittelbau-Dora camp. The human cost of production was enormous — more workers perished "
    "building the rockets than were harmed by the weapon in deployment. Von Braun held a "
    "military rank and visited Mittelwerk multiple times, though he later minimized his "
    "awareness of the working conditions there.",
    # 5. Operation Paperclip and Soviet parallel (splits the chain)
    "As the war ended, both the United States and Soviet Union raced to capture German "
    "rocket technology and personnel. Operation Paperclip brought approximately 1,600 "
    "German scientists to America, with von Braun's core team of 127 rocket engineers "
    "arriving at Fort Bliss, Texas in September 1945. They spent five years launching "
    "captured V-2s at White Sands Proving Ground in New Mexico. Meanwhile, the Soviets "
    "dismantled what remained at Peenemünde and relocated roughly 2,000 German specialists "
    "— including Helmut Gröttrup, who had been von Braun's guidance expert — to the island "
    "of Gorodomlya. Soviet rocket engineer Sergei Korolev studied the V-2 extensively but "
    "quickly moved beyond it, viewing the German design as a starting point rather than an "
    "end goal. By 1947 the Soviets had produced their own V-2 copy, the R-1, and Korolev "
    "was already planning far more ambitious designs.",
    # 6. Korolev's remarkable life (heavy aliasing — introduces multiple names)
    "The man who would become the most consequential figure in early spaceflight endured "
    "extraordinary hardship before achieving his triumphs. Sergei Pavlovich Korolev "
    "co-founded GIRD (Group for the Study of Reactive Motion) in Moscow in 1931 and "
    "launched the first Soviet liquid-fueled rocket in 1933. Then Stalin's Great Purge "
    "intervened: in 1938, Korolev was arrested on false charges, tortured, and sentenced "
    "to the Kolyma gold mines — among the deadliest of the gulag camps. He nearly died "
    "of scurvy and exhaustion. Intervention by aircraft designer Andrei Tupolev got him "
    "transferred to a sharashka, a prison design bureau, where he worked on aircraft. "
    "After the war, Korolev was rehabilitated and placed in charge of the Soviet ballistic "
    "missile program. His identity was classified as a state secret — he was referred to "
    "publicly only as 'the Chief Designer,' and even his own mother could not speak his "
    "name in connection with the space program.",
    # 7. R-7 and Sputnik (uses aliases — "the anonymous genius", Tyuratam/Baikonur)
    "Korolev's R-7 Semyorka, first successfully tested on August 21, 1957, was originally "
    "designed as the Soviet Union's first intercontinental ballistic missile. But the "
    "anonymous genius behind the project had always intended it for space. The R-7's "
    "massive thrust — necessitated by the Soviets' heavier, less miniaturized nuclear "
    "warheads — turned out to be ideal for orbital launches. On October 4, 1957, a "
    "modified R-7 launched Sputnik 1 from the facility the Soviets called 'NIIP-5' but "
    "which the world would come to know as the Baikonur Cosmodrome — though it was "
    "actually located near Tyuratam, Kazakhstan, hundreds of kilometers from the city "
    "of Baikonur. The misleading name was deliberate misdirection. The 83.6-kilogram "
    "polished sphere, transmitting its distinctive beep-beep-beep signal, could be "
    "tracked by amateur radio operators worldwide. The Chief Designer had beaten the "
    "Americans into orbit.",
    # 8. The Sputnik crisis (cascading political effects — many entities)
    "The launch of Sputnik triggered a crisis of confidence in the United States that "
    "reshaped American science, defense, and education policy. Within months, President "
    "Eisenhower signed two landmark acts: the National Aeronautics and Space Act of July "
    "1958, which dissolved the old National Advisory Committee for Aeronautics (NACA) and "
    "created NASA as a civilian space agency; and the National Defense Education Act, which "
    "poured funding into science and mathematics education. The Advanced Research Projects "
    "Agency (ARPA, later DARPA) was established in February 1958 to prevent future "
    "technological surprises. Meanwhile, the Army Ballistic Missile Agency in Huntsville "
    "— where von Braun's team had been frustrated by interservice rivalry and launch "
    "restrictions — finally got clearance to attempt a satellite launch. Using a Jupiter-C "
    "rocket (a modified Redstone), they launched Explorer 1 on January 31, 1958. Its cosmic "
    "ray detector, built by James Van Allen's team at the University of Iowa, discovered "
    "the radiation belts that now bear Van Allen's name — the first major scientific "
    "discovery of the Space Age.",
    # 9. Human spaceflight begins (Gagarin, Shepard, Kennedy — uses "SP" alias)
    "The race to put humans in space was nearly as lopsided as the satellite race. On "
    "April 12, 1961, Yuri Gagarin launched aboard Vostok 1 from the Tyuratam facility "
    "— which Soviet media continued to call Baikonur. The flight lasted 108 minutes and "
    "completed one orbit. SP Korolev personally monitored from the control bunker, "
    "reportedly chain-smoking the entire time. Twenty-three days later, Alan Shepard "
    "rode Freedom 7 on a suborbital arc lasting just 15 minutes. Then, on May 25, 1961, "
    "President Kennedy addressed a joint session of Congress: 'I believe that this nation "
    "should commit itself to achieving the goal, before this decade is out, of landing a "
    "man on the Moon and returning him safely to the Earth.' The Apollo program now had "
    "its mandate — and a deadline.",
    # 10. Mercury through Gemini (dense astronaut web, Houbolt's LOR)
    "The path to the Moon required systematic capability building. NASA's Mercury program, "
    "with its seven original astronauts — Shepard, Grissom, Glenn, Carpenter, Schirra, "
    "Cooper, and Slayton — proved that humans could survive and function in space. John "
    "Glenn's three-orbit flight on Friendship 7 in February 1962 made him a national hero. "
    "But Mercury capsules couldn't rendezvous, dock, or support spacewalks — all "
    "capabilities needed for a lunar mission. The Gemini program, running from 1965 to "
    "1966 with ten crewed flights, was designed as the bridge. Gemini 4 saw Ed White "
    "perform the first American spacewalk in June 1965. Gemini 6A and 7 achieved the "
    "first space rendezvous. Gemini 8, commanded by a civilian test pilot named Neil "
    "Armstrong, performed the first docking with an unmanned Agena target vehicle — "
    "though a stuck thruster forced an emergency abort, and Armstrong's cool-headed "
    "response to the crisis would later be cited as evidence of the temperament that "
    "made him the right choice for Apollo 11's commander. The Gemini missions also "
    "validated the lunar orbit rendezvous approach championed by NASA engineer John "
    "Houbolt, whose idea — initially dismissed by von Braun himself — would define "
    "Apollo's entire mission architecture.",
    # 11. The Apollo contractor web (dense entity network)
    "Apollo was the largest peacetime engineering project in history, employing over "
    "400,000 people across 20,000 companies. The prime contracts read like a map of "
    "mid-century American aerospace: North American Aviation built the Command and "
    "Service Module; Grumman Aircraft Engineering built the Lunar Module; Boeing "
    "constructed the Saturn V's first stage (the S-IC, powered by five Rocketdyne F-1 "
    "engines, each producing 1.5 million pounds of thrust); North American also built "
    "the S-II second stage; Douglas Aircraft built the S-IVB third stage with its "
    "single restartable J-2 engine. The MIT Instrumentation Laboratory, led by Charles "
    "Stark Draper, developed the Apollo Guidance Computer — a pioneering digital flight "
    "computer that drove early demand for integrated circuits, purchasing so many that "
    "it helped make ICs commercially viable. A young software engineer named Margaret "
    "Hamilton led the onboard flight software team at MIT; she would later be credited "
    "with coining the term 'software engineering' to legitimize the discipline.",
    # 12. Apollo 1 disaster (cascading effects, connects back to Gemini astronauts)
    "On January 27, 1967, what was supposed to be a routine plugs-out test became the "
    "Apollo program's darkest day. A fire erupted inside the Apollo 1 Command Module "
    "during a launch pad rehearsal at Cape Kennedy, killing astronauts Gus Grissom, "
    "Ed White, and Roger Chaffee. Grissom was a veteran of both Mercury and Gemini "
    "missions; White had performed the first American spacewalk just eighteen months "
    "earlier on Gemini 4. The investigation revealed devastating design flaws: a pure "
    "oxygen atmosphere at 16.7 psi, extensive use of flammable Velcro and nylon, wiring "
    "bundles routed under the crew's feet, and an inward-opening hatch that couldn't be "
    "opened against internal pressure. North American Aviation's spacecraft design came "
    "under severe criticism; Harrison Storms, who led North American's Space Division, "
    "was removed from the project. The resulting 21-month stand-down led to over 1,300 "
    "design changes. The tragedy that nearly killed Apollo ultimately produced a far "
    "safer spacecraft — and instilled a culture of rigorous safety review that persists "
    "at NASA to this day.",
    # 13. Korolev's death and Soviet collapse (uses "Sergei Pavlovich" alias)
    "When Sergei Pavlovich Korolev died on January 14, 1966, during what should have "
    "been routine colon surgery, the Soviet space program lost its irreplaceable center "
    "of gravity. Only in death was the Chief Designer's identity finally revealed to the "
    "world — he received a state funeral, and Pravda published his name for the first "
    "time. His successor, Vasily Mishin, inherited an impossible task: the N-1 rocket, "
    "the Soviet answer to Saturn V. Where von Braun's Saturn V used five massive F-1 "
    "engines on its first stage, the N-1 clustered thirty smaller NK-33 engines — a "
    "design forced by the long-running feud between Korolev and engine designer Valentin "
    "Glushko, who had refused to develop large-chamber engines using liquid oxygen. He "
    "preferred toxic hypergolic propellants. The N-1 failed catastrophically on all four "
    "launch attempts between 1969 and 1972 — the second failure producing one of the "
    "largest non-nuclear explosions in history. Without the political skill and technical "
    "vision of the man they'd simply called 'SP,' the Soviet Moon program was doomed.",
    # 14. Apollo 8 — the bold gamble
    "By mid-1968, the Lunar Module was behind schedule, but CIA intelligence suggested "
    "the Soviets were preparing a crewed lunar flyby using a Zond spacecraft. George Low, "
    "manager of the Apollo Spacecraft Program Office, proposed a daring alternative: send "
    "Apollo 8 to lunar orbit without the LM. It was an enormous gamble — no human had "
    "ever left low Earth orbit. On December 21, 1968, Frank Borman, Jim Lovell, and "
    "William Anders launched atop a Saturn V and three days later became the first humans "
    "to orbit the Moon. Anders took the iconic 'Earthrise' photograph — later called "
    "the most influential environmental photograph ever taken. On Christmas Eve, the "
    "crew read from the Book of Genesis in a live broadcast watched by an estimated one "
    "billion people. Apollo 8 transformed the Moon mission from a race into an inevitability.",
    # 15. Apollo 11 — culmination (uses aliases: "the former V-2 engineer", "the Cape")
    "On July 16, 1969, the rocket that the former V-2 engineer had spent two decades "
    "building — mission designation AS-506, known to the world simply as Saturn V — "
    "lifted off from Launch Complex 39A at the Cape, carrying the crew of Apollo 11. "
    "Commander Neil Armstrong was a Korean War veteran, former X-15 test pilot, and "
    "Gemini 8 commander whose calm under pressure was legendary. Lunar Module Pilot "
    "Edwin 'Buzz' Aldrin held a doctorate in orbital mechanics from MIT — his Gemini 12 "
    "spacewalk had finally proven that EVA work was feasible. Command Module Pilot "
    "Michael Collins, a Gemini 10 veteran, would remain alone in lunar orbit aboard "
    "Columbia while his crewmates descended in the Lunar Module Eagle. During the "
    "powered descent, the guidance computer built by Draper's team at the MIT "
    "Instrumentation Lab triggered a 1202 alarm — a processing overflow. Jack Garman, "
    "a 24-year-old engineer in Mission Control, called it safe to continue. At 4:17 PM "
    "EDT on July 20, Eagle touched down in the Sea of Tranquility with roughly 25 "
    "seconds of fuel remaining. Six hours later, Armstrong descended the ladder: "
    "'That's one small step for man, one giant leap for mankind.' The chain from "
    "Tsiolkovsky's equations to bootprints on the Moon had taken sixty-six years.",
    # 16. Hidden contributions (people the narrative usually omits)
    "The Apollo narrative typically centers on astronauts and rocket engineers, but "
    "critical contributions came from people long overlooked. At NASA's Langley Research "
    "Center, mathematician Katherine Johnson calculated the trajectory for Alan Shepard's "
    "Freedom 7 flight and later verified the computer calculations for John Glenn's "
    "orbital mission — Glenn personally requested her sign-off before he would fly. "
    "Johnson went on to calculate trajectories for Apollo 11. At MIT, Margaret Hamilton's "
    "software team wrote the code that saved Apollo 11 when the 1202 alarm fired during "
    "descent — her robust error-handling architecture allowed the computer to shed "
    "lower-priority tasks and keep running. Hamilton's insistence on treating software "
    "development with the same rigor as hardware engineering led her to coin the term "
    "'software engineering,' a concept that would transform the entire technology industry.",
    # 17. Revisionist scholarship (contradicts/complicates earlier snippets)
    "Recent historical scholarship has complicated the heroic narrative of the Space Race. "
    "Von Braun's postwar claims of minimal involvement with Mittelbau-Dora's forced labor "
    "conditions have been challenged by documents showing he personally approved worker "
    "transfers to the factory and visited production lines. Gagarin's Vostok 1 flight, "
    "long presented as flawless, actually experienced several malfunctions: the service "
    "module failed to separate cleanly, sending the spacecraft into an uncontrolled tumble "
    "before atmospheric heating burned through the straps connecting them. The framing of "
    "spaceflight as a bilateral US-Soviet 'race' also obscures the contributions of other "
    "nations — France, Britain, and China all had independent rocket programs by the 1960s, "
    "and the global scientific community shared data more freely than the competition "
    "narrative suggests.",
    # 18. Legacy and forward connections (links to modern technology)
    "The technological legacy of Apollo extends far beyond spaceflight. The Saturn V's "
    "F-1 engine combustion instability problems, solved by trial-and-error injector "
    "modifications at NASA's Marshall Center, informed rocket engine design for decades "
    "— engineers at SpaceX consulted the original F-1 test data when developing the "
    "Merlin engine. The Apollo Guidance Computer's demand for integrated circuits — "
    "MIT's Instrumentation Lab purchased over 60% of all ICs manufactured in the US "
    "during the early 1960s — helped drive down costs and catalyzed the semiconductor "
    "industry that would produce the personal computer revolution. Lunar samples returned "
    "by Apollo missions are still yielding discoveries: a 2024 analysis of Apollo 17 "
    "samples using modern mass spectrometry revealed the Moon is 40 million years older "
    "than previously thought. And the International Space Station, where American "
    "astronauts and Russian cosmonauts live and work together, carries the DNA of both "
    "the Apollo program and the Soviet Salyut stations — a quiet coda to the rivalry "
    "that launched the Space Age.",
]

# ══════════════════════════════════════════════════════════════════════════════
# DOMAIN B: THE FLORENTINE RENAISSANCE
# ══════════════════════════════════════════════════════════════════════════════

RENAISSANCE_SNIPPETS = [
    # 1. Byzantine tradition and Cimabue (artistic lineage start)
    "For centuries, Italian painting followed the Byzantine tradition: solemn, "
    "gold-ground icons with flat, elongated figures staring directly at the viewer, "
    "their spiritual authority conveyed through rigid frontality rather than naturalism. "
    "The style had been transmitted from Constantinople through Venice and Ravenna, and "
    "by the 13th century it dominated altarpieces and church decoration across the "
    "peninsula. Cenni di Pepo — known to history as Cimabue — was the last great master "
    "of this tradition and the first to push beyond it. His Crucifix at Santa Croce in "
    "Florence (c. 1288) introduced an unprecedented emotional expressiveness: Christ's "
    "body curves with the weight of death, his face registers genuine suffering. Cimabue "
    "also painted the monumental Maestà for Santa Trinita, where the Madonna's throne "
    "shows a tentative three-dimensionality absent from earlier work. According to "
    "tradition, Cimabue discovered his greatest pupil while walking in the countryside "
    "near Vespignano — a shepherd boy named Giotto di Bondone, drawing his sheep on a "
    "flat rock with astonishing naturalism.",
    # 2. Giotto's revolution (breaks from Byzantine, starts new chain)
    "Giotto di Bondone transformed Western art more decisively than any single artist "
    "before or since. Where Cimabue had introduced hints of naturalism within the "
    "Byzantine framework, Giotto shattered the framework entirely. His frescoes in the "
    "Arena Chapel (Cappella degli Scrovegni) in Padua, painted around 1305, present "
    "biblical scenes with three-dimensional figures occupying believable architectural "
    "spaces. The figures express genuine human emotion — grief, tenderness, rage, "
    "betrayal — in compositions of revolutionary clarity. The Lamentation, with its "
    "ring of mourners around the dead Christ, achieves a psychological intensity that "
    "painting would not surpass for a century. Even Giotto's contemporaries understood "
    "the magnitude of the shift: Dante Alighieri wrote in the Divine Comedy, 'Cimabue "
    "thought to hold the field in painting, and now Giotto has the cry, so that the "
    "fame of the former is obscured.' Giotto also designed the campanile of Florence "
    "Cathedral and worked in Naples, Rome, and Milan, spreading his innovations across "
    "Italy. His workshop trained a generation of painters who would carry his methods "
    "into the next century.",
    # 3. The Medici banking empire (patronage chain starts)
    "The Medici family's transformation from prosperous merchants to de facto rulers of "
    "Florence began with Giovanni di Bicci de' Medici, who founded the Medici Bank in "
    "1397. By the time his son Cosimo — known as 'il Vecchio,' the Elder — inherited "
    "the enterprise in 1429, it was the most profitable bank in Europe, with branches "
    "in Rome, Venice, Geneva, Bruges, and London. Cosimo understood that in a republic "
    "that formally prohibited dynastic rule, cultural patronage was the most effective "
    "form of political power. He spent lavishly on architecture and art: he commissioned "
    "Filippo Brunelleschi to rebuild the Basilica of San Lorenzo, supported the sculptor "
    "Donato di Niccolò di Betto Bardi — whom everyone called simply Donatello — and "
    "funded Marsilio Ficino's translations of Plato. Cosimo was briefly exiled by rival "
    "families in 1433, but recalled the following year to even greater authority. When he "
    "died in 1464, the Florentine Signoria granted him the posthumous title 'Pater "
    "Patriae' — Father of the Fatherland.",
    # 4. Brunelleschi's dome and the birth of perspective (architecture + technique)
    "Filippo Brunelleschi's dome for the Cathedral of Santa Maria del Fiore — the Duomo "
    "of Florence — remains one of the supreme engineering achievements in history. The "
    "cathedral had stood roofless since 1296 because no one knew how to span its "
    "143-foot octagonal opening without traditional wooden centering, which would have "
    "required more timber than existed in Tuscany. Brunelleschi, who had studied Roman "
    "ruins obsessively (particularly the Pantheon), proposed a revolutionary double-shell "
    "design: an inner and outer dome connected by ribs, with a herringbone brick pattern "
    "that made each course self-supporting during construction. He won the commission in "
    "a famous competition against Lorenzo Ghiberti — the same Ghiberti whose bronze "
    "Baptistery doors Michelangelo would later call the 'Gates of Paradise.' The dome "
    "was completed in 1436 and immediately became the symbol of Florence. But Brunelleschi's "
    "influence extended beyond architecture: around 1420, he conducted his famous "
    "perspective demonstration at the Baptistery, using a painted panel and a mirror to "
    "prove mathematically that parallel lines converge at a vanishing point. This "
    "experiment launched the systematic study of linear perspective that would "
    "revolutionize European painting.",
    # 5. Perspective codified (technique chain: Brunelleschi → Alberti → Masaccio → Piero)
    "Brunelleschi demonstrated perspective empirically, but it was Leon Battista Alberti "
    "who gave it theoretical foundations. In 'De Pictura' (On Painting), written in 1435 "
    "and dedicated to Brunelleschi, Alberti laid out a systematic method for constructing "
    "a perspective grid — the 'costruzione legittima' — that any trained painter could "
    "apply. The young painter Masaccio was the first to absorb the lesson fully: his "
    "Holy Trinity fresco at Santa Maria Novella (c. 1427) creates such a convincing "
    "illusion of depth that viewers feel they are looking through the wall into a real "
    "chapel beyond. Vasari wrote that when it was unveiled, 'it seemed as if a hole had "
    "been bored through the wall.' Masaccio died at just 27, but his Brancacci Chapel "
    "frescoes in Santa Maria del Carmine became a school for every subsequent Florentine "
    "painter — Botticelli, Leonardo, Michelangelo, and Raphael all studied there. Piero "
    "della Francesca took perspective furthest as pure mathematics, writing 'De "
    "Prospectiva Pingendi,' while Paolo Uccello became so obsessed with perspective "
    "that his wife reportedly complained he stayed up all night drawing vanishing "
    "points, murmuring 'What a sweet thing perspective is!'",
    # 6. Lorenzo the Magnificent (heavy aliasing, patronage hub)
    "Lorenzo de' Medici, known as 'Il Magnifico,' inherited the leadership of Florence "
    "in 1469 at age twenty upon the death of his father Piero 'the Gouty.' Though not "
    "a banker of his grandfather Cosimo il Vecchio's caliber — the Medici Bank actually "
    "declined under his stewardship — Lorenzo's true genius was cultural and diplomatic. "
    "He established the sculpture garden near San Marco where a teenage Michelangelo "
    "studied ancient Roman works under the curator Bertoldo di Giovanni, a former pupil "
    "of Donatello. Il Magnifico supported Sandro Botticelli, commissioned works from "
    "Andrea del Verrocchio's workshop, and hosted the Platonic Academy where the "
    "philosopher Marsilio Ficino and the poet Angelo Poliziano shaped Neoplatonic thought. "
    "The Pazzi conspiracy of April 26, 1478 — a plot backed by Pope Sixtus IV in which "
    "Lorenzo's brother Giuliano was stabbed to death during Mass in the Cathedral — only "
    "strengthened Il Magnifico's grip on power. He survived with a neck wound and "
    "personally orchestrated the brutal reprisals. Lorenzo the Magnificent died in 1492; "
    "his son Piero proved incapable of holding Florence, and the Medici were expelled "
    "two years later.",
    # 7. Verrocchio's workshop (training chain: master → Leonardo, Botticelli, Perugino)
    "Andrea del Verrocchio's bottega on the Via de' Agnolo in Florence was the most "
    "important artistic training ground of the fifteenth century. Verrocchio himself was "
    "a goldsmith, sculptor, and painter of considerable talent — his bronze David and "
    "the equestrian monument to Bartolomeo Colleoni in Venice rank among the finest "
    "sculptures of the period. But his greatest legacy was his students. Among the "
    "apprentices who passed through the workshop: Leonardo di ser Piero da Vinci, "
    "Sandro Botticelli, Pietro Perugino, Lorenzo di Credi, and Domenico Ghirlandaio. "
    "When the young Leonardo painted an angel in Verrocchio's 'Baptism of Christ' so "
    "beautifully that, according to Giorgio Vasari, the master put down his brush and "
    "never painted again — a charming story, almost certainly exaggerated, but revealing "
    "of how Leonardo's talent was perceived even in youth. Perugino would later establish "
    "his own workshop in Perugia, where a young Raffaello Sanzio — whom the world would "
    "know as Raphael — began his artistic training around 1494.",
    # 8. Botticelli and the Neoplatonic circle (patronage → philosophy → disruption)
    "Sandro Botticelli, trained in Verrocchio's workshop and deeply embedded in the "
    "Medici circle, produced paintings that embody the Neoplatonic idealism of Lorenzo "
    "the Magnificent's Florence. 'The Birth of Venus' and 'Primavera' — both painted "
    "for Lorenzo di Pierfrancesco de' Medici, a cousin of Il Magnifico — translate "
    "Ficino's philosophical writings into visual poetry: beauty as a path to divine "
    "truth. The mythological subjects were radical for a culture still dominated by "
    "religious commissions. But when the Dominican friar Girolamo Savonarola rose to "
    "power in the 1490s, preaching apocalyptic sermons against luxury, secular art, "
    "and what he called the pagan corruption of Florentine culture, Botticelli was "
    "profoundly shaken. He reportedly contributed some of his own paintings to the "
    "Bonfire of the Vanities in February 1497, when citizens gathered in the Piazza "
    "della Signoria to burn mirrors, cosmetics, books, musical instruments, and artworks. "
    "The Medici had been expelled from Florence in 1494, and the city Botticelli had "
    "known — the golden age of Il Magnifico — seemed to be ending.",
    # 9. Leonardo: the universal man (heavy aliasing, multiple cities)
    "Leonardo di ser Piero da Vinci — the illegitimate son of a Florentine notary and "
    "a peasant woman — entered Verrocchio's workshop around age fourteen and quickly "
    "surpassed every expectation. His genius defied categorization: anatomy, engineering, "
    "optics, geology, botany, hydraulics, and painting were all unified in his relentless "
    "observation of nature. He developed sfumato, a technique of layering translucent "
    "oil glazes to create atmospheric softness without visible brushstrokes — the "
    "technique that gives the Mona Lisa's smile its famous ambiguity. His notebooks, "
    "written in mirror script across thousands of pages, contained designs for flying "
    "machines, armored vehicles, diving apparatus, and hydraulic systems centuries ahead "
    "of their time. Yet Leonardo was notoriously unable to finish projects: the Adoration "
    "of the Magi, the colossal Sforza Horse in Milan, the Battle of Anghiari mural — "
    "all abandoned. He left Florence for Milan in 1482, serving Duke Ludovico Sforza as "
    "engineer and painter (producing The Last Supper). After Milan fell to the French, "
    "Leonardo wandered to Venice, back to Florence, to Rome, and finally to France, "
    "where he died at the Château du Clos Lucé near Amboise in 1519, in the service "
    "of King Francis I.",
    # 10. Michelangelo: sculptor of the divine (aliasing: "Il Divino", full name)
    "Michelangelo di Lodovico Buonarroti Simoni — whom contemporaries called 'Il Divino,' "
    "the Divine One — insisted throughout his life that he was first and foremost a "
    "sculptor, though fate repeatedly pushed him toward painting and architecture. "
    "Trained briefly in Domenico Ghirlandaio's workshop, the teenager caught the eye "
    "of Lorenzo de' Medici at the sculpture garden near San Marco and was essentially "
    "adopted into the Medici household, dining at Lorenzo's table and studying alongside "
    "the Medici children. His Pietà, completed in Rome at age twenty-four, established "
    "him as the greatest sculptor alive — it was the only work he ever signed, carving "
    "'MICHAELA[N]GELUS BONAROTUS FLORENTIN[US] FACIEBA[T]' across the Madonna's sash "
    "after overhearing visitors attribute it to another artist. When Pope Julius II "
    "commissioned him to paint the ceiling of the Sistine Chapel — a project Michelangelo "
    "resisted, suspecting a plot by the architect Donato Bramante to set him up for "
    "failure in an unfamiliar medium — the result was arguably the greatest artistic "
    "achievement in Western history. The 12,000-square-foot vault, painted largely alone "
    "over four years (1508-1512), depicts the Genesis narrative from Creation to the Flood.",
    # 11. The Sistine Chapel and papal patronage (connects many entities)
    "The Sistine Chapel's artistic history spans the ambitions of multiple popes. "
    "Pope Sixtus IV originally commissioned the chapel's side walls in the 1480s from "
    "a team that included Botticelli, Perugino, Ghirlandaio, and Cosimo Rosselli — each "
    "painting scenes from the lives of Moses and Christ in a unified decorative scheme. "
    "Three decades later, Sixtus's nephew Pope Julius II — known as 'il Papa Terribile,' "
    "the Fearsome Pope — ordered the ceiling repainted, choosing Michelangelo for the "
    "task. Julius was simultaneously directing Bramante to demolish the thousand-year-old "
    "St. Peter's Basilica and build a new one, and commissioning the young Raphael to "
    "paint the papal apartments (the Vatican Stanze). The relationship between Julius and "
    "Michelangelo was legendarily stormy: the artist once fled Rome after a quarrel over "
    "payments and had to be persuaded to return by papal emissaries. Twenty years after "
    "the ceiling's completion, Pope Clement VII — born Giulio de' Medici, the illegitimate "
    "nephew of Lorenzo the Magnificent — commissioned Michelangelo to paint 'The Last "
    "Judgment' on the chapel's altar wall, a work of apocalyptic power that would not be "
    "completed until 1541.",
    # 12. Raphael and the School of Athens (lineage endpoint, absorbs two masters)
    "Raffaello Sanzio da Urbino learned the craft of painting in Pietro Perugino's "
    "workshop in Perugia before arriving in Florence around 1504, where he spent four "
    "years absorbing the innovations of the city's two dominant geniuses. From Leonardo "
    "he took sfumato and the art of psychologically complex composition; from "
    "Michelangelo, the muscular dynamism of the human form. In 1508, Pope Julius II "
    "summoned Raphael to Rome to paint the Vatican Stanze — the papal reception rooms "
    "— in direct competition with Michelangelo's work on the Sistine ceiling just down "
    "the corridor. The 'School of Athens' (1509-1511), painted in the Stanza della "
    "Segnatura, is a summit of High Renaissance composition: ancient philosophers "
    "gathered under an architectural setting inspired by Bramante's plans for the new "
    "St. Peter's. In an act of tribute to the two living artists he considered equals "
    "of the ancients, Raphael gave Plato the face of Leonardo and the brooding "
    "Heraclitus the features of Michelangelo. Despite dying at just thirty-seven in "
    "1520, Raphael's enormous workshop — including his chief assistant Giulio Romano "
    "— ensured his style dominated Roman painting for a generation.",
    # 13. Oil painting revolutionizes the craft (technique chain from North to South)
    "The transition from egg tempera to oil painting was as transformative for art as "
    "the printing press was for literature. Netherlandish painters Jan van Eyck and "
    "Robert Campin developed oil techniques in the 1420s and 1430s, building up "
    "translucent layers of pigment suspended in linseed oil that glowed with an inner "
    "luminosity impossible in tempera. The technique reached Italy through Antonello da "
    "Messina, a Sicilian painter who — according to Vasari, though the details are "
    "disputed — learned the method in Bruges and brought it to Venice around 1475. "
    "Giovanni Bellini adopted oil immediately, and through his workshop it spread to "
    "his students Giorgione and Titian, who would push oil's possibilities further "
    "than anyone had imagined. Oil's slow drying time was the key: it allowed blending "
    "on the canvas itself, enabling Leonardo's sfumato, Titian's richly layered color, "
    "and the atmospheric landscapes of the Venetian school. By 1500, egg tempera was "
    "effectively dead for serious panel painting. A material innovation from the Low "
    "Countries had permanently altered the visual language of Mediterranean art.",
    # 14. Bramante and the rebuilding of St. Peter's (architecture chain continues)
    "Donato Bramante, originally from Urbino and trained in the mathematical traditions "
    "of Piero della Francesca and Mantegna, came to Rome around 1499 and won Pope "
    "Julius II's commission to rebuild St. Peter's Basilica — the most ambitious "
    "architectural project since antiquity. His 1506 design called for a Greek cross "
    "plan topped by a massive dome inspired by the Pantheon, larger than anything "
    "attempted since the Roman Empire. But Bramante died in 1514 with only the four "
    "enormous central piers completed. A troubled succession of architects followed: "
    "Raphael (who made limited progress before his early death), Baldassare Peruzzi, "
    "Antonio da Sangallo the Younger (whose elaborate wooden model survives). Finally, "
    "in 1547, Pope Paul III appointed Michelangelo, then seventy-one years old and "
    "reluctant. Il Divino simplified Bramante's design, strengthened the crossing "
    "piers, and designed the soaring dome that would define Rome's skyline for "
    "centuries. Like Brunelleschi's dome in Florence a century earlier, Michelangelo's "
    "design used a double-shell structure — but on a far grander scale. Michelangelo "
    "died in 1564 with the drum completed; Giacomo della Porta finished the dome "
    "in 1590, making it slightly more pointed than Michelangelo had intended.",
    # 15. Savonarola and the Bonfire of the Vanities (disruption of patronage cycle)
    "Girolamo Savonarola, a Dominican friar from Ferrara, arrived in Florence in 1482 "
    "and by the 1490s had become its most powerful voice. His apocalyptic sermons in "
    "the Cathedral denounced the Medici, the papacy, and the secular humanism that had "
    "defined Florentine culture for a century. He called Botticelli's mythological "
    "paintings sinful, condemned Lorenzo the Magnificent's philosophical academy as "
    "pagan, and predicted divine punishment for the city's vanity. After Lorenzo died "
    "in 1492 and his son Piero was expelled in 1494, Savonarola effectively ruled "
    "Florence as a theocratic republic. The Bonfire of the Vanities in February 1497 "
    "saw citizens throw mirrors, cosmetics, fine clothing, books of poetry, musical "
    "instruments, and artworks — including, if Vasari is to be believed, paintings by "
    "Botticelli himself — into an enormous pyre in the Piazza della Signoria. But "
    "Savonarola overreached: he challenged Pope Alexander VI directly, was "
    "excommunicated, arrested, tortured into confession, and hanged and burned in "
    "the same piazza in May 1498. The Medici eventually returned to Florence, and "
    "the cycle of patronage, art, and power resumed — though Florence would never "
    "again be quite the cultural center it had been under Il Magnifico.",
    # 16. Vasari and the invention of art history (meta-narrative, connects all)
    "Giorgio Vasari's 'Lives of the Most Excellent Painters, Sculptors, and Architects' "
    "(first published in 1550, revised and expanded in 1568) essentially invented art "
    "history as a discipline. Vasari structured his biographies as a grand narrative of "
    "progress from the medieval darkness through Cimabue and Giotto, ascending through "
    "Brunelleschi, Masaccio, and Donatello, and culminating in the divine perfection of "
    "Michelangelo — whom Vasari worshipped as the greatest artist who had ever lived. "
    "His three-stage framework of artistic 'rebirth' gave us the very term 'Renaissance.' "
    "While many of Vasari's anecdotes are embellished or invented (the Verrocchio story, "
    "Cimabue discovering Giotto drawing sheep), his model of artistic lineage — master "
    "to pupil, innovation building on innovation — shaped how Western culture understands "
    "creative achievement. Vasari was also a practicing architect: he designed the Uffizi "
    "in Florence as administrative offices for Cosimo I de' Medici, Grand Duke of Tuscany "
    "— a building whose upper corridor, converted to display the Medici art collection, "
    "would become one of the world's first and greatest public art museums.",
    # 17. Donatello and the rebirth of sculpture (aliasing test: full name vs common name)
    "Donato di Niccolò di Betto Bardi — known universally as Donatello — was the most "
    "important sculptor of the early Renaissance and a close collaborator of Brunelleschi. "
    "The two had traveled to Rome together as young men to study ancient ruins, and "
    "their shared passion for classical forms fueled both the architectural and sculptural "
    "revolutions that followed. Donatello's bronze David (c. 1440) was the first "
    "freestanding nude sculpture created since antiquity — a radical act in a culture "
    "still negotiating the boundary between Christian modesty and classical celebration "
    "of the human body. Commissioned by Cosimo de' Medici, it stood in the courtyard "
    "of the Medici palace. In Padua, Donatello created the Gattamelata — a monumental "
    "equestrian bronze of the condottiere Erasmo da Narni — the first large-scale "
    "equestrian statue since the Roman Marcus Aurelius. His late works, like the "
    "harrowing wooden Mary Magdalene for the Florence Baptistery, show an emotional "
    "intensity that anticipates Michelangelo by half a century. Donatello died in 1466 "
    "and was buried in San Lorenzo, near Cosimo de' Medici — patron and artist united "
    "even in death.",
    # 18. The Renaissance spreads (outward connections, shows transmission chains)
    "Florence's artistic innovations did not stay in Florence. Leonardo carried "
    "Florentine techniques to Milan and ultimately to France, where his presence at the "
    "court of Francis I helped ignite the French Renaissance. Bramante and Raphael "
    "transformed Rome from a medieval city into the capital of High Renaissance art "
    "and architecture. Antonello da Messina transmitted Netherlandish oil painting to "
    "Venice, where Giovanni Bellini, Giorgione, and Titian developed their own luminous "
    "school. Albrecht Dürer traveled to Venice twice (1494 and 1505) and carried Italian "
    "perspective techniques back to Northern Europe, publishing his own treatise on "
    "measurement and proportion. The fall of Constantinople to the Ottoman Turks in "
    "1453 had sent Greek scholars westward carrying ancient manuscripts, fueling the "
    "humanist revival that Cosimo de' Medici and Marsilio Ficino championed in Florence. "
    "And Gutenberg's printing press, operational from the 1450s, spread illustrated "
    "editions of Alberti's perspective treatise and Vitruvius's ancient architecture "
    "text across the continent. By 1520, every major European court wanted its own "
    "Leonardo or Raphael — the Florentine Renaissance had become a continental movement.",
]

# ── Combined snippets ────────────────────────────────────────────────────────
SNIPPETS = SPACE_SNIPPETS + RENAISSANCE_SNIPPETS

# ── Recall questions ─────────────────────────────────────────────────────────
# Multi-hop chain reasoning questions for each domain, plus cross-domain
# isolation checks.

SPACE_RECALL = [
    # 6-hop: Tsiolkovsky → Oberth → von Braun → V-2 → Paperclip → Saturn V → Apollo 11
    "How did a 19th-century Russian schoolteacher's theoretical work contribute to "
    "Americans walking on the Moon?",
    # 5-hop: Mittelbau-Dora → V-2 → von Braun → Paperclip → Saturn V → Apollo 11
    "What connects the Mittelbau-Dora forced labor camp to the Sea of Tranquility?",
    # 4-hop: Korolev death → Mishin → N-1 (Glushko feud) → failures
    "How did one Soviet engineer's death in 1966 contribute to America winning the Moon race?",
    # 3-hop: Gemini 8 → stuck thruster → Armstrong's calm → Apollo 11 commander
    "What role did a stuck thruster on Gemini 8 play in the selection of Apollo 11's commander?",
    # Entity resolution: 5 aliases
    "Who was 'the Chief Designer,' and why was his identity kept secret even from his own family?",
    # MIT IL → guidance computer → IC demand → semiconductor industry
    "What connects the MIT Instrumentation Laboratory to both the Moon landing and the "
    "personal computer revolution?",
]

RENAISSANCE_RECALL = [
    # 5-hop: Cimabue → Giotto → artistic revolution → ... → Michelangelo → Sistine
    "How did a shepherd boy drawing on rocks lead to the greatest painting on the "
    "Sistine Chapel ceiling?",
    # Patronage chain: Medici bank → Cosimo → Lorenzo → sculpture garden → Michelangelo
    "What connects a 15th-century banking fortune to the ceiling of the Sistine Chapel?",
    # Technique chain: Brunelleschi experiment → Alberti → Masaccio → School of Athens
    "Trace the path from Brunelleschi's mirror experiment to Raphael's School of Athens.",
    # Workshop lineage: Verrocchio → Leonardo + Perugino → Raphael
    "How did one Florentine workshop produce the artists who defined the High Renaissance?",
    # Oil painting chain: Van Eyck → Antonello → Venice → Bellini → Titian
    "How did a technique developed in Bruges transform painting in Venice?",
    # Entity resolution: Lorenzo aliases
    "Who was 'Il Magnifico' and what happened to his family after his death?",
    # Architecture chain: Brunelleschi dome → Michelangelo dome
    "What connects the dome of Florence Cathedral to the dome of St. Peter's in Rome?",
    # Disruption: Savonarola → Bonfire → Botticelli → Medici expelled → returned
    "How did a Dominican friar's sermons lead to the destruction of Renaissance masterpieces?",
]

CROSS_DOMAIN_RECALL = [
    # These should return answers clearly noting no connection exists
    "Are there any connections between the Apollo space program and the Florentine Renaissance?",
    "Did any of the same people or organizations appear in both the Space Race and the "
    "Renaissance?",
]

RECALL_QUESTIONS = SPACE_RECALL + RENAISSANCE_RECALL + CROSS_DOMAIN_RECALL

# ── Graph probes ─────────────────────────────────────────────────────────────

SPACE_PROBES = [
    "Wernher von Braun",
    "Korolev",
    "Apollo 11",
    "Saturn V",
    "V-2",
    "Sputnik",
    "MIT Instrumentation Lab",
    "Operation Paperclip",
    "Apollo 1",
    "Explorer 1",
]

RENAISSANCE_PROBES = [
    "Michelangelo",
    "Lorenzo de' Medici",
    "Verrocchio",
    "Brunelleschi",
    "Leonardo",
    "Raphael",
    "Sistine Chapel",
    "Bramante",
    "Botticelli",
    "Savonarola",
]

GRAPH_PROBES = SPACE_PROBES + RENAISSANCE_PROBES


# ══════════════════════════════════════════════════════════════════════════════
# RUNNER
# ══════════════════════════════════════════════════════════════════════════════


def ingest_all(client: httpx.Client) -> list[dict]:
    """Ingest all snippets via async job API and poll for completion."""
    results = []
    for i, snippet in enumerate(SNIPPETS, 1):
        domain = "SPACE" if i <= len(SPACE_SNIPPETS) else "RENAISSANCE"
        domain_idx = i if i <= len(SPACE_SNIPPETS) else i - len(SPACE_SNIPPETS)
        print(f"\n{'=' * 60}")
        print(f"INGEST {i}/{len(SNIPPETS)} [{domain} #{domain_idx}]")
        print(f"{'=' * 60}")
        print(f"Text: {snippet[:120]}...")
        resp = client.post(f"{BASE}/ingest", json={"text": snippet}, timeout=10)
        if resp.status_code != 202:
            print(f"  ⚠ Unexpected status: {resp.status_code}")
            continue
        job = resp.json()
        job_id = job["job_id"]
        print(f"  Job: {job_id}")

        # Poll for completion
        while True:
            time.sleep(2)
            poll = client.get(f"{BASE}/ingest/jobs/{job_id}", timeout=10)
            status = poll.json()["status"]
            if status in ("complete", "failed"):
                data = poll.json()
                results.append(data)
                if data.get("summary"):
                    print(f"  Summary: {data['summary'][:200]}...")
                elif data.get("error"):
                    print(f"  ⚠ Failed: {data['error'][:200]}")
                break
        time.sleep(1)
    return results


def recall_all(client: httpx.Client) -> list[dict]:
    """Run all recall questions and return results."""
    results = []
    for i, question in enumerate(RECALL_QUESTIONS, 1):
        print(f"\n{'=' * 60}")
        print(f"RECALL {i}/{len(RECALL_QUESTIONS)}")
        print(f"{'=' * 60}")
        print(f"Q: {question}")
        resp = client.post(f"{BASE}/recall", json={"question": question}, timeout=180)
        resp.raise_for_status()
        data = resp.json()
        results.append({"question": question, **data})
        print(f"A: {data['answer'][:300]}...")
        ctx = data.get("context") or {}
        node_count = len(ctx.get("nodes", []))
        edge_count = len(ctx.get("edges", []))
        print(f"Context: {node_count} nodes, {edge_count} edges")
    return results


def find_entity(client: httpx.Client, name: str) -> str | None:
    """Search for an entity by name using recall, return its ID if found."""
    resp: httpx.Response | None = None
    for attempt in range(3):
        resp = client.post(
            f"{BASE}/recall",
            json={"question": f"Find the entity: {name}"},
            timeout=180,
        )
        if resp.status_code == 200:
            break
        print(
            f"  ⚠ Recall attempt {attempt + 1} failed ({resp.status_code}), retrying..."
        )
        time.sleep(3)
    if resp is None:
        raise RuntimeError(f"recall never attempted for {name!r}")
    resp.raise_for_status()
    data = resp.json()
    nodes = data.get("context", {}).get("nodes", [])
    for node in nodes:
        if (
            node.get("table") == "entity"
            and name.lower() in node.get("name", "").lower()
        ):
            return node["id"]
    for node in nodes:
        if node.get("table") == "entity":
            return node["id"]
    return None


def graph_probes_all(client: httpx.Client) -> list[dict]:
    """Explore graph around key entities from both domains."""
    results = []
    for name in GRAPH_PROBES:
        domain = "SPACE" if name in SPACE_PROBES else "RENAISSANCE"
        print(f"\n{'=' * 60}")
        print(f"GRAPH PROBE [{domain}]: {name}")
        print(f"{'=' * 60}")
        entity_id = find_entity(client, name)
        if not entity_id:
            print(f"  ⚠ Could not find entity for '{name}'")
            results.append({"name": name, "domain": domain, "error": "not found"})
            continue
        print(f"  Found: {entity_id}")
        resp = client.get(f"{BASE}/graph/{entity_id}", timeout=30)
        if resp.status_code == 404:
            print("  ⚠ Node not found in graph")
            results.append({"name": name, "domain": domain, "error": "404"})
            continue
        resp.raise_for_status()
        data = resp.json()
        data["domain"] = domain
        print(
            f"  Node: {data['node'].get('name', data['node'].get('content', '?')[:60])}"
        )
        print(f"  Connections: {len(data['connections'])}")
        for conn in data["connections"]:
            edge = conn["edge"]
            node = conn["node"]
            direction = "→" if edge.get("from") == entity_id else "←"
            node_label = node.get("name", node.get("content", "?")[:50])
            print(f"    {direction} [{edge['table']}] {node_label}")
        results.append(data)
    return results


def trigger_dream(client: httpx.Client):
    """Trigger a dream cycle and wait for it to complete."""
    print(f"\n{'=' * 60}")
    print("TRIGGERING DREAM CYCLE")
    print(f"{'=' * 60}")
    resp = client.post(f"{BASE}/dream", timeout=10)
    resp.raise_for_status()
    print(f"Dream status: {resp.json()}")
    print("Waiting 180s for dream cycle to complete...")
    time.sleep(180)
    print("Dream wait complete.")


def main():
    phase = sys.argv[1] if len(sys.argv) > 1 else "all"
    client = httpx.Client()

    resp = client.get(f"{BASE}/health")
    resp.raise_for_status()
    print("Server healthy ✓")

    if phase in ("all", "ingest"):
        print("\n" + "█" * 60)
        print("PHASE: INGEST")
        print("█" * 60)
        ingest_results = ingest_all(client)
        with open("test_ingest_results.json", "w") as f:
            json.dump(ingest_results, f, indent=2)
        print(f"\nIngested {len(ingest_results)} snippets.")

    if phase in ("all", "recall"):
        print("\n" + "█" * 60)
        print("PHASE: RECALL (pre-dream)")
        print("█" * 60)
        recall_results = recall_all(client)
        with open("test_recall_pre_dream.json", "w") as f:
            json.dump(recall_results, f, indent=2)

    if phase in ("all", "graph"):
        print("\n" + "█" * 60)
        print("PHASE: GRAPH PROBES (pre-dream)")
        print("█" * 60)
        graph_results = graph_probes_all(client)
        with open("test_graph_pre_dream.json", "w") as f:
            json.dump(graph_results, f, indent=2, default=str)

    if phase in ("all", "dream"):
        trigger_dream(client)

    if phase in ("all", "recall-post"):
        print("\n" + "█" * 60)
        print("PHASE: RECALL (post-dream)")
        print("█" * 60)
        recall_results = recall_all(client)
        with open("test_recall_post_dream.json", "w") as f:
            json.dump(recall_results, f, indent=2)

    if phase in ("all", "graph-post"):
        print("\n" + "█" * 60)
        print("PHASE: GRAPH PROBES (post-dream)")
        print("█" * 60)
        graph_results = graph_probes_all(client)
        with open("test_graph_post_dream.json", "w") as f:
            json.dump(graph_results, f, indent=2, default=str)

    print("\n✓ Done.")


if __name__ == "__main__":
    main()
