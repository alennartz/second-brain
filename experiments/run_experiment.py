#!/usr/bin/env python3
"""
Automated experiment runner for ingest quality evaluation.

Usage:
    experiments/benchctl.sh start <experiment_name> [notes]
    experiments/benchctl.sh status <experiment_name>
    experiments/benchctl.sh stop <experiment_name>
    experiments/benchctl.sh resume <experiment_name>

Runs resumably against an isolated scratch DB. It ingests Space Race and
Florentine Renaissance snippets, runs recall and graph probes, and uses an LLM
judge to score quality. State and timing data persist after each operation.
"""

import contextlib
import json
import os
import shutil
import signal
import statistics
import subprocess
import sys
import time
from datetime import UTC, datetime

import httpx

DEFAULT_PORT = int(os.environ.get("EXPERIMENT_PORT", "8000"))
EXPERIMENTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(EXPERIMENTS_DIR)

# ══════════════════════════════════════════════════════════════════════════════
# DOMAIN A: THE SPACE AGE (16 snippets)
# ══════════════════════════════════════════════════════════════════════════════

SPACE_SNIPPETS = [
    # 1. Tsiolkovsky — theoretical foundations (deepest chain start)
    "Konstantin Tsiolkovsky, a self-taught Russian schoolteacher from Kaluga, published "
    "'The Exploration of Cosmic Space by Means of Reaction Devices' in 1903 — the same "
    "year as the Wright brothers' first flight. His work derived the fundamental rocket "
    "equation relating exhaust velocity to achievable delta-v, and he proposed multi-stage "
    "rockets, liquid hydrogen and oxygen propellant, and even space stations decades before "
    "any of it was technically feasible. Tsiolkovsky never built a rocket himself, but his "
    "theoretical framework directly inspired the next generation: Hermann Oberth in Romania "
    "read his work and built upon it, while in the Soviet Union a young engineering student "
    "named Sergei Korolev devoured Tsiolkovsky's writings and began dreaming of spaceflight.",
    # 2. Oberth and the VfR (theory → practice bridge)
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
    # 4. V-2 at Peenemünde (dense, moral complexity)
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
    # 5. Operation Paperclip and Soviet parallel (chain splits)
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
    # 6. Korolev's life (heavy aliasing: "Sergei Pavlovich", "Chief Designer")
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
    # 7. R-7 and Sputnik (aliases: "anonymous genius", "NIIP-5", "Tyuratam", "Baikonur")
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
    # 8. Sputnik crisis (many political entities, cascading effects)
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
    # 9. Human spaceflight begins (alias: "SP Korolev", "Tyuratam"/"Baikonur")
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
    # 10. Mercury through Gemini (dense astronaut web, Armstrong's Gemini 8 crisis)
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
    # 11. Apollo contractor web (dense entity network)
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
    # 12. Apollo 1 disaster (cascading effects, Gemini astronaut connections)
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
    # 13. Korolev's death and Soviet collapse (aliases: "Sergei Pavlovich", "SP")
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
    # 14. Apollo 8 — bold gamble
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
    # 15. Apollo 11 — culmination (aliases: "the former V-2 engineer", "the Cape")
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
    # 16. Hidden contributions
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
]

# ══════════════════════════════════════════════════════════════════════════════
# DOMAIN B: THE FLORENTINE RENAISSANCE (14 snippets)
# ══════════════════════════════════════════════════════════════════════════════

RENAISSANCE_SNIPPETS = [
    # 1. Byzantine tradition and Cimabue (lineage start)
    "For centuries, Italian painting followed the Byzantine tradition: solemn, "
    "gold-ground icons with flat, elongated figures staring directly at the viewer, "
    "their spiritual authority conveyed through rigid frontality rather than naturalism. "
    "The style had been transmitted from Constantinople through Venice and Ravenna, and "
    "by the 13th century it dominated altarpieces and church decoration across the "
    "peninsula. Cenni di Pepo — known to history as Cimabue — was the last great master "
    "of this tradition and the first to push beyond it. His Crucifix at Santa Croce in "
    "Florence (c. 1288) introduced an unprecedented emotional expressiveness: Christ's "
    "body curves with the weight of death, his face registers genuine suffering. According "
    "to tradition, Cimabue discovered his greatest pupil while walking in the countryside "
    "near Vespignano — a shepherd boy named Giotto di Bondone, drawing his sheep on a "
    "flat rock with astonishing naturalism.",
    # 2. Giotto's revolution (breaks from Byzantine)
    "Giotto di Bondone transformed Western art more decisively than any single artist "
    "before or since. Where Cimabue had introduced hints of naturalism within the "
    "Byzantine framework, Giotto shattered the framework entirely. His frescoes in the "
    "Arena Chapel (Cappella degli Scrovegni) in Padua, painted around 1305, present "
    "biblical scenes with three-dimensional figures occupying believable architectural "
    "spaces. The figures express genuine human emotion — grief, tenderness, rage, "
    "betrayal — in compositions of revolutionary clarity. Even Giotto's contemporaries "
    "understood the magnitude of the shift: Dante Alighieri wrote in the Divine Comedy, "
    "'Cimabue thought to hold the field in painting, and now Giotto has the cry, so that "
    "the fame of the former is obscured.' Giotto also designed the campanile of Florence "
    "Cathedral and worked in Naples, Rome, and Milan, spreading his innovations across "
    "Italy. His workshop trained a generation of painters who would carry his methods "
    "into the next century.",
    # 3. Medici banking empire (patronage chain start)
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
    # 4. Brunelleschi's dome and perspective (architecture + technique chain)
    "Filippo Brunelleschi's dome for the Cathedral of Santa Maria del Fiore — the Duomo "
    "of Florence — remains one of the supreme engineering achievements in history. The "
    "cathedral had stood roofless since 1296 because no one knew how to span its "
    "143-foot octagonal opening without traditional wooden centering, which would have "
    "required more timber than existed in Tuscany. Brunelleschi proposed a revolutionary "
    "double-shell design: an inner and outer dome connected by ribs, with a herringbone "
    "brick pattern that made each course self-supporting. He won the commission in "
    "a famous competition against Lorenzo Ghiberti — the same Ghiberti whose bronze "
    "Baptistery doors Michelangelo would later call the 'Gates of Paradise.' The dome "
    "was completed in 1436 and immediately became the symbol of Florence. But Brunelleschi's "
    "influence extended beyond architecture: around 1420, he conducted his famous "
    "perspective demonstration at the Baptistery, using a painted panel and a mirror to "
    "prove mathematically that parallel lines converge at a vanishing point. This "
    "experiment launched the systematic study of linear perspective that would "
    "revolutionize European painting.",
    # 5. Perspective codified (technique chain continues)
    "Brunelleschi demonstrated perspective empirically, but it was Leon Battista Alberti "
    "who gave it theoretical foundations. In 'De Pictura' (On Painting), written in 1435 "
    "and dedicated to Brunelleschi, Alberti laid out a systematic method for constructing "
    "a perspective grid — the 'costruzione legittima' — that any trained painter could "
    "apply. The young painter Masaccio was the first to absorb the lesson fully: his "
    "Holy Trinity fresco at Santa Maria Novella (c. 1427) creates such a convincing "
    "illusion of depth that viewers feel they are looking through the wall into a real "
    "chapel beyond. Masaccio died at just 27, but his Brancacci Chapel frescoes in "
    "Santa Maria del Carmine became a school for every subsequent Florentine painter — "
    "Botticelli, Leonardo, Michelangelo, and Raphael all studied there. Piero della "
    "Francesca took perspective furthest as pure mathematics, while Paolo Uccello became "
    "so obsessed with it that his wife reportedly complained he stayed up all night "
    "drawing vanishing points, murmuring 'What a sweet thing perspective is!'",
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
    "strengthened Il Magnifico's grip on power. Lorenzo the Magnificent died in 1492; "
    "his son Piero proved incapable of holding Florence, and the Medici were expelled "
    "two years later.",
    # 7. Verrocchio's workshop (training chain hub)
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
    # 8. Leonardo: the universal man (aliasing, multiple cities)
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
    # 9. Michelangelo: sculptor of the divine (aliasing: "Il Divino", full name)
    "Michelangelo di Lodovico Buonarroti Simoni — whom contemporaries called 'Il Divino,' "
    "the Divine One — insisted throughout his life that he was first and foremost a "
    "sculptor, though fate repeatedly pushed him toward painting and architecture. "
    "Trained briefly in Domenico Ghirlandaio's workshop, the teenager caught the eye "
    "of Lorenzo de' Medici at the sculpture garden near San Marco and was essentially "
    "adopted into the Medici household, dining at Lorenzo's table and studying alongside "
    "the Medici children. His Pietà, completed in Rome at age twenty-four, established "
    "him as the greatest sculptor alive. When Pope Julius II commissioned him to paint "
    "the ceiling of the Sistine Chapel — a project Michelangelo resisted, suspecting a "
    "plot by the architect Donato Bramante to set him up for failure in an unfamiliar "
    "medium — the result was arguably the greatest artistic achievement in Western history. "
    "The 12,000-square-foot vault, painted largely alone over four years (1508-1512), "
    "depicts the Genesis narrative from Creation to the Flood.",
    # 10. Sistine Chapel and papal patronage (connects many entities)
    "The Sistine Chapel's artistic history spans the ambitions of multiple popes. "
    "Pope Sixtus IV originally commissioned the chapel's side walls in the 1480s from "
    "a team that included Botticelli, Perugino, Ghirlandaio, and Cosimo Rosselli. "
    "Three decades later, his nephew Pope Julius II — known as 'il Papa Terribile,' "
    "the Fearsome Pope — ordered the ceiling repainted, choosing Michelangelo for the "
    "task. Julius was simultaneously directing Bramante to demolish the thousand-year-old "
    "St. Peter's Basilica and build a new one, and commissioning the young Raphael to "
    "paint the papal apartments (the Vatican Stanze). The relationship between Julius and "
    "Michelangelo was legendarily stormy: the artist once fled Rome after a quarrel over "
    "payments and had to be persuaded to return by papal emissaries. Twenty years after "
    "the ceiling's completion, Pope Clement VII — born Giulio de' Medici, the illegitimate "
    "nephew of Lorenzo the Magnificent — commissioned Michelangelo to paint 'The Last "
    "Judgment' on the chapel's altar wall.",
    # 11. Raphael and the School of Athens (lineage endpoint)
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
    "St. Peter's. In an act of tribute, Raphael gave Plato the face of Leonardo and "
    "the brooding Heraclitus the features of Michelangelo. Despite dying at just "
    "thirty-seven in 1520, Raphael's enormous workshop — including his chief assistant "
    "Giulio Romano — ensured his style dominated Roman painting for a generation.",
    # 12. Oil painting transforms the craft (technique chain)
    "The transition from egg tempera to oil painting was as transformative for art as "
    "the printing press was for literature. Netherlandish painters Jan van Eyck and "
    "Robert Campin developed oil techniques in the 1420s and 1430s, building up "
    "translucent layers of pigment suspended in linseed oil that glowed with an inner "
    "luminosity impossible in tempera. The technique reached Italy through Antonello da "
    "Messina, a Sicilian painter who — according to Vasari, though the details are "
    "disputed — learned the method in Bruges and brought it to Venice around 1475. "
    "Giovanni Bellini adopted oil immediately, and through his workshop it spread to "
    "his students Giorgione and Titian, who would push oil's possibilities further "
    "than anyone had imagined. Oil's slow drying time allowed blending on the canvas, "
    "enabling Leonardo's sfumato and Titian's richly layered color. By 1500, egg tempera "
    "was effectively dead for serious panel painting.",
    # 13. Bramante and St. Peter's (architecture chain)
    "Donato Bramante, originally from Urbino and trained in the mathematical traditions "
    "of Piero della Francesca and Mantegna, came to Rome around 1499 and won Pope "
    "Julius II's commission to rebuild St. Peter's Basilica — the most ambitious "
    "architectural project since antiquity. His 1506 design called for a Greek cross "
    "plan topped by a massive dome inspired by the Pantheon. But Bramante died in 1514 "
    "with only the four enormous central piers completed. A troubled succession of "
    "architects followed: Raphael, Baldassare Peruzzi, Antonio da Sangallo the Younger. "
    "Finally, in 1547, Pope Paul III appointed Michelangelo, then seventy-one. Il Divino "
    "simplified Bramante's design, strengthened the crossing piers, and designed the "
    "soaring dome that would define Rome's skyline. Like Brunelleschi's dome in Florence "
    "a century earlier, Michelangelo's design used a double-shell structure — but on a "
    "far grander scale. Michelangelo died in 1564 with the drum completed; Giacomo "
    "della Porta finished the dome in 1590.",
    # 14. Savonarola and the Bonfire of the Vanities (patronage disruption)
    "Girolamo Savonarola, a Dominican friar from Ferrara, arrived in Florence in 1482 "
    "and by the 1490s had become its most powerful voice. His apocalyptic sermons in "
    "the Cathedral denounced the Medici, the papacy, and the secular humanism that had "
    "defined Florentine culture for a century. After Lorenzo the Magnificent died in "
    "1492 and his son Piero was expelled in 1494, Savonarola effectively ruled Florence "
    "as a theocratic republic. The Bonfire of the Vanities in February 1497 saw citizens "
    "throw mirrors, cosmetics, fine clothing, books, musical instruments, and artworks "
    "— including, if Vasari is to be believed, paintings by Botticelli — into an "
    "enormous pyre in the Piazza della Signoria. But Savonarola overreached: he "
    "challenged Pope Alexander VI directly, was excommunicated, arrested, tortured, "
    "and hanged and burned in the same piazza in May 1498. The Medici eventually "
    "returned, and the cycle of patronage and power resumed.",
]

# ── Combined snippets ────────────────────────────────────────────────────────
SNIPPETS = SPACE_SNIPPETS + RENAISSANCE_SNIPPETS

RECALL_QUESTIONS = [
    # Space Race chain questions
    "How did a 19th-century Russian schoolteacher's theoretical work contribute to "
    "Americans walking on the Moon?",
    "What connects the Mittelbau-Dora forced labor camp to the Sea of Tranquility?",
    "How did one Soviet engineer's death in 1966 contribute to America winning the Moon race?",
    "Who was 'the Chief Designer,' and why was his identity kept secret even from his own family?",
    # Renaissance chain questions
    "How did a shepherd boy drawing on rocks lead to the greatest painting on the "
    "Sistine Chapel ceiling?",
    "What connects a 15th-century banking fortune to the ceiling of the Sistine Chapel?",
    "How did one Florentine workshop produce the artists who defined the High Renaissance?",
    "Who was 'Il Magnifico' and what happened to his family after his death?",
    # Cross-domain isolation check
    "Are there any connections between the Apollo space program and the Florentine Renaissance?",
]

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

# ── Relationship Assertions (judged by LLM, not pattern-matched) ─────────────
# Each is a plain-English statement about a relationship the graph should capture.

SPACE_ASSERTIONS = [
    "Tsiolkovsky's theoretical work inspired or influenced Oberth",
    "Oberth mentored or inspired von Braun",
    "Von Braun developed or led the development of the V-2 rocket",
    "Von Braun was recruited to the US through Operation Paperclip",
    "Von Braun directed or led Marshall Space Flight Center",
    "Korolev was known as or connected to 'the Chief Designer'",
    "Korolev developed or designed the R-7 rocket",
    "Korolev oversaw or was involved in the Sputnik launch",
    "Korolev oversaw or monitored the Vostok 1 / Gagarin flight",
    "Sputnik's launch triggered or led to the creation of NASA",
    "Explorer 1 discovered or detected the Van Allen radiation belts",
    "Apollo 11's crew included Armstrong, Aldrin, and Collins",
    "Apollo 11 was launched on a Saturn V rocket",
    "The Apollo 1 fire killed Grissom, White, and Chaffee",
    "Grumman built the Lunar Module",
    "North American Aviation built the Command/Service Module",
    "The MIT Instrumentation Lab developed the Apollo Guidance Computer",
    "Katherine Johnson calculated trajectories for Mercury or Apollo",
    "Margaret Hamilton led the Apollo software team or coined 'software engineering'",
    "Korolev and Glushko had a rivalry or feud over engine design",
    "Armstrong commanded Gemini 8 before Apollo 11",
    "Saturn V was designed or developed at/by Marshall or von Braun's team",
]

RENAISSANCE_ASSERTIONS = [
    "Cimabue discovered or taught Giotto",
    "Cosimo de' Medici patronized or commissioned Brunelleschi or Donatello",
    "Lorenzo de' Medici (Il Magnifico) patronized Botticelli or Michelangelo",
    "Lorenzo de' Medici was known as 'Il Magnifico'",
    "Verrocchio's workshop trained Leonardo",
    "Verrocchio's workshop trained Botticelli or Perugino",
    "Perugino trained or mentored Raphael",
    "Brunelleschi discovered or demonstrated linear perspective",
    "Alberti codified or wrote about perspective (De Pictura)",
    "Brunelleschi designed or built the dome of Florence Cathedral",
    "Bramante designed or began rebuilding St. Peter's Basilica",
    "Michelangelo designed or continued the dome of St. Peter's",
    "Michelangelo painted the Sistine Chapel ceiling",
    "Raphael painted the School of Athens or the Vatican Stanze",
    "Pope Julius II commissioned Michelangelo, Raphael, or Bramante",
    "Antonello da Messina brought oil painting to Italy or Venice",
    "Savonarola denounced or opposed the Medici",
    "Michelangelo was known as 'Il Divino'",
    "Donatello's real name was Donato di Niccolò di Betto Bardi",
]

CROSS_DOMAIN_ASSERTIONS = [
    "There should be NO direct edge between any Space Race entity (von Braun, Korolev, "
    "Apollo, Saturn V, Sputnik, NASA) and any Renaissance entity (Michelangelo, Leonardo, "
    "Raphael, Bramante, Medici, Brunelleschi, Botticelli, Savonarola)",
]


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════


# ════════════════════════════════════════════════════════════════════════════
# RESUMABLE RUNTIME
#
# Properties:
#   - resumable: state.json persists after EVERY operation; rerun skips done work
#   - interruptible: SIGINT/SIGTERM finish the current op, save state, stop server
#   - monitorable: state.json is a live view (phase, counts, last op, elapsed);
#     run log is unbuffered and append-only
#   - resilient: per-op deadline + one retry; server restarts if it dies
# ════════════════════════════════════════════════════════════════════════════

OP_TIMEOUT_S = float(os.environ.get("BENCH_OP_TIMEOUT", "900"))


class BenchInterrupt(Exception):
    """Raised on SIGINT/SIGTERM to exit cleanly with saved state."""


class BenchState:
    """Durable run state. Saved after every completed operation."""

    def __init__(self, path: str, name: str, notes: str):
        self.path = path
        if os.path.exists(path):
            with open(path) as f:
                self.data = json.load(f)
        else:
            self.data = {
                "name": name,
                "notes": notes,
                "started_utc": datetime.now(UTC).isoformat(),
                "phase": "ingest",
                "ingest": [],  # one record per completed snippet
                "recall": [],  # one record per answered question
                "graph": [],  # one record per probed entity
                "judge": {},  # section name -> results
                "current": None,
                "interrupted": False,
            }
            self.save()
        self.data.pop("inflight_ingest", None)
        self.data.setdefault("current", None)
        self.data.setdefault("interrupted", False)
        self.data["interrupted"] = False

    @property
    def fresh(self) -> bool:
        return not (
            self.data["ingest"]
            or self.data["recall"]
            or self.data["graph"]
            or self.data.get("current")
        )

    def save(self) -> None:
        tmp = self.path + ".tmp"
        self.data["updated_utc"] = datetime.now(UTC).isoformat()
        with open(tmp, "w") as f:
            json.dump(self.data, f, indent=2)
        os.replace(tmp, self.path)
        # Keep phase artifacts current during the run, not only at the end.
        for phase in ("ingest", "recall", "graph"):
            artifact_tmp = os.path.join(os.path.dirname(self.path), f"{phase}.json.tmp")
            with open(artifact_tmp, "w") as f:
                json.dump(self.data[phase], f, indent=2, default=str)
            os.replace(
                artifact_tmp, os.path.join(os.path.dirname(self.path), f"{phase}.json")
            )
        if self.data["judge"]:
            artifact_tmp = os.path.join(
                os.path.dirname(self.path), "llm_scores.json.tmp"
            )
            with open(artifact_tmp, "w") as f:
                json.dump(self.data["judge"], f, indent=2)
            os.replace(
                artifact_tmp,
                os.path.join(os.path.dirname(self.path), "llm_scores.json"),
            )

    def monitor_line(self) -> str:
        d = self.data
        current = d.get("current") or {}
        elapsed = None
        if current.get("started_epoch"):
            elapsed = round(time.time() - current["started_epoch"], 1)
        active = (
            f" current={current.get('label')} elapsed_s={elapsed}" if current else ""
        )
        return (
            f"phase={d['phase']} ingest={len(d['ingest'])}/{len(SNIPPETS)} "
            f"recall={len(d['recall'])}/{len(RECALL_QUESTIONS)} "
            f"graph={len(d['graph'])}/{len(GRAPH_PROBES)}{active}"
        )


def make_client():
    return httpx.Client(timeout=180)


def wait_for_server(port, max_wait=60):
    client = httpx.Client(timeout=5)
    for _ in range(max_wait):
        try:
            r = client.get(f"http://localhost:{port}/health")
            if r.status_code == 200:
                return True
        except BenchInterrupt:
            raise
        except Exception:
            pass
        time.sleep(1)
    return False


def server_healthy(port) -> bool:
    try:
        r = httpx.get(f"http://localhost:{port}/health", timeout=5)
        return r.status_code == 200
    except BenchInterrupt:
        raise
    except Exception:
        return False


class ServerSupervisor:
    """Owns the experiment server process. Restarts it if it dies.

    Wipes the DB only on a FRESH run (no resume state) — a resumed run
    keeps the DB written by prior snippets.
    """

    def __init__(self, name: str, port: int, db_suffix: str, wipe: bool, log_path: str):
        self.name = name
        self.port = port
        self.db_suffix = db_suffix
        self.wipe = wipe
        self.log_path = log_path
        self.unit = f"brain-benchmark-api-{port}.service"
        self.owner_path = os.path.join(
            PROJECT_DIR, "data", f"brain-experiment-{port}.owner"
        )

    def start(self):
        healthy = server_healthy(self.port)
        owner = None
        if os.path.exists(self.owner_path):
            with open(self.owner_path) as f:
                owner = f.read().strip()
        if owner is not None and owner != self.name:
            raise RuntimeError(
                f"port {self.port} is already used by benchmark {owner or 'an unmanaged server'}"
            )
        if healthy and not self.wipe:
            print(f"server: reusing healthy server on :{self.port}")
            return
        if healthy and self.wipe:
            self.stop_proc()

        db_name = f"brain{self.db_suffix}.db" if self.db_suffix else "brain.db"
        db_path = os.path.join(PROJECT_DIR, "data", db_name)
        if self.wipe and os.path.exists(db_path):
            shutil.rmtree(db_path)
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)

        subprocess.run(
            ["systemctl", "--user", "reset-failed", self.unit],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        command = [
            "systemd-run",
            "--user",
            f"--unit={self.unit.removesuffix('.service')}",
            "--property=Restart=on-failure",
            "--property=RestartSec=10s",
            f"--property=WorkingDirectory={PROJECT_DIR}",
            f"--property=StandardOutput=append:{self.log_path}",
            f"--property=StandardError=append:{self.log_path}",
            "--collect",
            "--",
            "/usr/bin/env",
            f"BRAIN_DB_PATH=data/{db_name}",
        ]
        for key in (
            "BRAIN_TEST_MODE",
            "BRAIN_REASONING_MODEL",
            "BRAIN_EMBEDDING_MODEL",
            "BRAIN_REASONING_BASE_URL",
            "BRAIN_EMBEDDING_BASE_URL",
        ):
            if key in os.environ:
                command.append(f"{key}={os.environ[key]}")
        command.extend(
            [
                os.path.join(PROJECT_DIR, ".venv", "bin", "uvicorn"),
                "second_brain.app:app",
                "--host",
                "0.0.0.0",
                "--port",
                str(self.port),
            ]
        )
        with open(self.owner_path, "w") as f:
            f.write(self.name + "\n")
        subprocess.run(command, cwd=PROJECT_DIR, check=True)
        if not wait_for_server(self.port):
            raise RuntimeError(f"server on port {self.port} failed to start")

    def ensure(self):
        if not server_healthy(self.port):
            print("server: unhealthy — restarting")
            self.stop_proc()
            self.wipe = False  # keep DB on restart
            self.start()

    def stop_proc(self):
        subprocess.run(
            ["systemctl", "--user", "stop", self.unit],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        with contextlib.suppress(FileNotFoundError):
            os.remove(self.owner_path)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.stop_proc()
        # On pause/failure, leave the separate API unit running.
        # Resume reattaches to the same server and preserves staged intake.


# --- Phase runners (resumable: skip work already in state) ---


def _ingest_one(client, base, snippet, deadline, state: BenchState, index: int) -> dict:
    """Stage one snippet through the synchronous intake endpoint."""
    if time.time() >= deadline:
        raise TimeoutError(f"ingest for snippet {index + 1} exceeded op deadline")
    started_epoch = time.time()
    key = f"{state.data['name']}:{index}"
    resp = client.post(
        f"{base}/ingest",
        json={"text": snippet},
        headers={"Idempotency-Key": key},
        timeout=min(30, max(1, int(deadline - started_epoch))),
    )
    resp.raise_for_status()
    payload = resp.json()
    chunks_stored = payload.get("chunks_stored")
    if not isinstance(chunks_stored, int) or chunks_stored < 0:
        raise RuntimeError("ingest response omitted a valid chunks_stored count")
    return {
        "status": "complete",
        "chunks_stored": chunks_stored,
        "elapsed_s": round(time.time() - started_epoch, 2),
    }


def ingest_phase(client, sup: ServerSupervisor, base, state: BenchState):
    done = {
        r["snippet_index"]
        for r in state.data["ingest"]
        if r.get("status") == "complete"
    }
    results = state.data["ingest"]
    for i, snippet in enumerate(SNIPPETS):
        if i in done:
            continue
        domain = "SPACE" if i < len(SPACE_SNIPPETS) else "RENAISSANCE"
        t0 = time.time()
        state.data["current"] = {
            "phase": "ingest",
            "index": i,
            "label": f"snippet {i + 1}/{len(SNIPPETS)} ({domain})",
            "started_epoch": t0,
        }
        state.save()
        record = None
        for attempt in (1, 2):
            try:
                sup.ensure()
                deadline = time.time() + OP_TIMEOUT_S
                record = _ingest_one(client, base, snippet, deadline, state, i)
                if record.get("status") == "failed":
                    raise RuntimeError(record.get("error") or "intake staging failed")
                record["elapsed_s"] = round(time.time() - t0, 2)
                break
            except BenchInterrupt:
                raise
            except Exception as e:
                print(
                    f"  [{i + 1}/{len(SNIPPETS)} {domain}] attempt {attempt} failed: {e}"
                )
        if record is None:
            record = {"status": "failed", "elapsed_s": round(time.time() - t0, 2)}
        record["snippet_index"] = i
        record["domain"] = domain
        old_record = next((r for r in results if r["snippet_index"] == i), None)
        if old_record:
            old_record.update(record)
        else:
            results.append(record)
        state.data["current"] = None
        state.save()
        icon = "✓" if record.get("status") == "complete" else "✗"
        print(f"  [{i + 1}/{len(SNIPPETS)} {domain}] {record['elapsed_s']}s {icon}")
    state.data["phase"] = "recall"
    state.save()


def recall_phase(client, sup: ServerSupervisor, base, state: BenchState):
    done = {
        r["question_index"]
        for r in state.data["recall"]
        if not str(r.get("answer", "")).startswith("ERROR:")
    }
    results = state.data["recall"]
    for i, question in enumerate(RECALL_QUESTIONS):
        if i in done:
            continue
        t0 = time.time()
        state.data["current"] = {
            "phase": "recall",
            "index": i,
            "label": f"question {i + 1}/{len(RECALL_QUESTIONS)}",
            "started_epoch": t0,
        }
        state.save()
        record = None
        for attempt in (1, 2):
            try:
                sup.ensure()
                resp = client.post(
                    f"{base}/recall", json={"question": question}, timeout=OP_TIMEOUT_S
                )
                resp.raise_for_status()
                record = resp.json()
                break
            except BenchInterrupt:
                raise
            except Exception as e:
                print(f"  recall {i + 1} attempt {attempt} failed: {e}")
                time.sleep(10)
        if record is None:
            record = {"answer": "ERROR: exhausted retries", "context": None}
        record["question"] = question
        record["question_index"] = i
        record["elapsed_s"] = round(time.time() - t0, 2)
        results.append(record)
        state.data["current"] = None
        state.save()
        print(f"  [{i + 1}/{len(RECALL_QUESTIONS)}] {record['elapsed_s']}s")
    state.data["phase"] = "graph"
    state.save()


def find_entity_id(client, base, name):
    for _attempt in range(3):
        try:
            resp = client.post(
                f"{base}/recall",
                json={"question": f"Find the entity: {name}"},
                timeout=OP_TIMEOUT_S,
            )
            if resp.status_code != 200:
                time.sleep(5)
                continue
            data = resp.json()
            nodes = (data.get("context") or {}).get("nodes", [])
            for node in nodes:
                if (
                    node.get("table") == "entity"
                    and name.lower() in node.get("name", "").lower()
                ):
                    return node["id"]
            for node in nodes:
                if node.get("table") == "entity":
                    return node["id"]
        except BenchInterrupt:
            raise
        except Exception:
            time.sleep(5)
    return None


def graph_phase(client, sup: ServerSupervisor, base, state: BenchState):
    done = {r["name"] for r in state.data["graph"]}
    results = state.data["graph"]
    for name in GRAPH_PROBES:
        if name in done:
            continue
        domain = "SPACE" if name in SPACE_PROBES else "RENAISSANCE"
        t0 = time.time()
        state.data["current"] = {
            "phase": "graph",
            "label": name,
            "started_epoch": t0,
        }
        state.save()
        sup.ensure()
        entity_id = find_entity_id(client, base, name)
        record = {
            "name": name,
            "domain": domain,
            "id": entity_id,
            "node": None,
            "connections": [],
        }
        if entity_id:
            try:
                resp = client.get(f"{base}/graph/{entity_id}", timeout=60)
                resp.raise_for_status()
                data = resp.json()
                data["name"] = name
                data["domain"] = domain
                data["id"] = entity_id
                record = data
            except BenchInterrupt:
                raise
            except Exception as e:
                print(f"  ⚠ {name} [{domain}]: error {e}")
        else:
            print(f"  ⚠ {name} [{domain}]: not found")
        record["elapsed_s"] = round(time.time() - t0, 2)
        results.append(record)
        state.data["current"] = None
        state.save()
        n = len(record.get("connections", []))
        print(f"  {name} [{domain}]: {n} connections ({record['elapsed_s']}s)")
    state.data["phase"] = "judge"
    state.save()


def judge_phase(state: BenchState, graph_results) -> dict:
    """LLM-judged scoring, resumable per section."""
    import sys as _sys

    _sys.path.insert(0, os.path.join(PROJECT_DIR, "src"))
    from pydantic_ai import Agent

    model = _create_judge_model()

    def judge_call(graph_text, assertions, section):
        numbered = "\n".join(f"{i + 1}. {a}" for i, a in enumerate(assertions))
        prompt = (
            f"You are evaluating a knowledge graph. Below is the graph neighborhood data "
            f"for key entities, followed by a list of assertions about relationships that "
            f"should exist in the graph.\n\n## Graph Data\n\n{graph_text}\n\n"
            f"## {section} — Assertions to evaluate\n\n{numbered}\n\n## Instructions\n\n"
            f"For each numbered assertion, determine whether the graph data supports it. "
            f"A relationship counts as captured if there is a DIRECT edge between the "
            f"relevant entities (in either direction, with any reasonable edge name) OR if "
            f"the entities are clearly connected through a short path (1-2 hops).\n\n"
            f"Respond with a JSON array. Each element must have:\n"
            f'- "n": the assertion number (integer)\n'
            f'- "pass": true if the relationship is captured, false if not\n'
            f'- "reason": brief explanation (what edge or path you found, or what is missing)\n\n'
            f"Respond ONLY with the JSON array, no other text."
        )
        judge = Agent(output_type=str)
        answer = judge.run_sync(prompt, model=model).output
        json_start = answer.find("[")
        json_end = answer.rfind("]") + 1
        parsed = json.loads(answer[json_start:json_end])
        result_map = {r.get("n", 0): r for r in parsed}
        return [
            {
                "assertion": a,
                "pass": bool(result_map.get(i + 1, {}).get("pass", False)),
                "reason": result_map.get(i + 1, {}).get(
                    "reason", "No judgment returned"
                ),
            }
            for i, a in enumerate(assertions)
        ]

    graph_text = _format_graph_neighborhood(graph_results)
    stored = state.data["judge"]
    sections = {
        "space": ("Space Race Relationships", SPACE_ASSERTIONS),
        "renaissance": ("Renaissance Relationships", RENAISSANCE_ASSERTIONS),
        "cross_domain": ("Cross-Domain Isolation", CROSS_DOMAIN_ASSERTIONS),
    }
    for key, (label, assertions) in sections.items():
        if key in stored and not any(
            "LLM call failed" in str(r.get("reason", "")) for r in stored[key]
        ):
            continue
        print(f"  Judging {label}...")
        try:
            stored[key] = judge_call(graph_text, assertions, label)
        except BenchInterrupt:
            raise
        except Exception as e:
            print(f"    ⚠ judge call failed: {e}")
            stored[key] = [
                {"assertion": a, "pass": False, "reason": f"LLM call failed: {e}"}
                for a in assertions
            ]
        state.save()
    return stored


# ══════════════════════════════════════════════════════════════════════════════
# LLM-JUDGED SCORING
# ══════════════════════════════════════════════════════════════════════════════


def _format_graph_neighborhood(graph_results: list[dict]) -> str:
    """Format all graph probe results into a readable text block for the LLM judge."""
    lines = []
    for g in graph_results:
        name = g.get("name", "?")
        domain = g.get("domain", "?")
        node = g.get("node")
        conns = g.get("connections", [])
        eid = g.get("id", "")

        if not node:
            lines.append(f"**{name}** [{domain}] — NOT FOUND IN GRAPH")
            lines.append("")
            continue

        node_type = node.get("type", "")
        node_desc = node.get("description", "")
        lines.append(f"**{name}** [{domain}] (type: {node_type})")
        if node_desc:
            lines.append(f"  Description: {node_desc}")
        lines.append(f"  Connections ({len(conns)}):")
        for conn in conns:
            edge = conn["edge"]
            other = conn["node"]
            direction = "→" if edge.get("from") == eid else "←"
            other_name = other.get("name", other.get("content", "?")[:60])
            other_table = other.get("table", "?")
            lines.append(
                f"    {direction} [{edge['table']}] {other_name} ({other_table})"
            )
        lines.append("")
    return "\n".join(lines)


def _create_judge_model():
    """Create a PydanticAI model from project settings for direct LLM calls."""
    sys.path.insert(0, os.path.join(PROJECT_DIR, "src"))
    from second_brain.config import settings
    from second_brain.providers import create_model

    return create_model(
        settings.reasoning_model,
        settings.reasoning_foundry_url,
        settings.reasoning_auth,
        settings.reasoning_key,
    )


def latency_stats(values: list[float]) -> dict:
    """Summary statistics over per-operation durations in seconds."""
    if not values:
        return {"count": 0}
    ordered = sorted(values)
    n = len(ordered)
    p95_idx = min(n - 1, max(0, round(0.95 * (n - 1))))
    return {
        "count": n,
        "min_s": round(ordered[0], 2),
        "mean_s": round(sum(values) / n, 2),
        "median_s": round(statistics.median(ordered), 2),
        "p95_s": round(ordered[p95_idx], 2),
        "max_s": round(ordered[-1], 2),
        "total_s": round(sum(values), 2),
    }


def collect_latency(ingest_results, recall_results, graph_results) -> dict:
    """Extract per-phase latency stats from result dicts (elapsed_s fields)."""
    return {
        "ingest": latency_stats(
            [r["elapsed_s"] for r in ingest_results if "elapsed_s" in r]
        ),
        "recall": latency_stats(
            [r["elapsed_s"] for r in recall_results if "elapsed_s" in r]
        ),
        "graph": latency_stats(
            [r["elapsed_s"] for r in graph_results if "elapsed_s" in r]
        ),
    }


def format_latency_section(latency: dict) -> list[str]:
    """Journal markdown table for the latency summary."""
    lines = [
        "### Latency",
        "| Phase | n | min | median | mean | p95 | max | total |",
        "|-------|---|-----|--------|------|-----|-----|-------|",
    ]
    for phase in ("ingest", "recall", "graph"):
        s = latency.get(phase, {})
        if not s.get("count"):
            lines.append(f"| {phase} | 0 | — | — | — | — | — | — |")
        else:
            lines.append(
                f"| {phase} | {s['count']} | {s['min_s']}s | {s['median_s']}s "
                f"| {s['mean_s']}s | {s['p95_s']}s | {s['max_s']}s | {s['total_s']}s |"
            )
    lines.append("")
    return lines


def score_recall(recall_results):
    total = len(recall_results)
    with_ctx = sum(1 for r in recall_results if (r.get("context") or {}).get("nodes"))
    total_nodes = sum(
        len((r.get("context") or {}).get("nodes", [])) for r in recall_results
    )
    errors = sum(1 for r in recall_results if "ERROR" in r.get("answer", ""))
    return {
        "total": total,
        "with_context": with_ctx,
        "total_nodes": total_nodes,
        "errors": errors,
    }


def format_report(
    name, notes, llm_scores, recall_scores, graph_results, latency, total_elapsed
):
    space_pass = sum(1 for r in llm_scores["space"] if r["pass"])
    space_total = len(llm_scores["space"])
    ren_pass = sum(1 for r in llm_scores["renaissance"] if r["pass"])
    ren_total = len(llm_scores["renaissance"])
    cross_pass = sum(1 for r in llm_scores["cross_domain"] if r["pass"])
    cross_total = len(llm_scores["cross_domain"])
    total_connections = sum(len(g.get("connections", [])) for g in graph_results)

    lines = [
        f"## {name}",
        f"**Date:** {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Notes:** {notes}",
        f"**Data:** {len(SPACE_SNIPPETS)} space + {len(RENAISSANCE_SNIPPETS)} renaissance snippets, "
        f"{len(RECALL_QUESTIONS)} questions, {len(GRAPH_PROBES)} probes",
        "**Scoring:** LLM-judged (not pattern-matched)",
        "",
        "### Scores",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Space relationships | **{space_pass}/{space_total}** |",
        f"| Renaissance relationships | **{ren_pass}/{ren_total}** |",
        f"| Combined relationships | **{space_pass + ren_pass}/{space_total + ren_total}** |",
        f"| Cross-domain isolation | **{cross_pass}/{cross_total}** |",
        f"| Total graph connections | **{total_connections}** |",
        f"| Recall with context | **{recall_scores['with_context']}/{recall_scores['total']}** |",
        f"| Recall total nodes cited | **{recall_scores['total_nodes']}** |",
        f"| Total wall time | **{total_elapsed:.0f}s** |",
        "",
    ]

    lines.extend(format_latency_section(latency))

    for section_label, results in [
        ("Space Race Relationships", llm_scores["space"]),
        ("Renaissance Relationships", llm_scores["renaissance"]),
        ("Cross-Domain Isolation", llm_scores["cross_domain"]),
    ]:
        lines.append(f"### {section_label}")
        for r in results:
            status = "✓" if r["pass"] else "✗"
            lines.append(f"- {status} {r['assertion']}")
            lines.append(f"  - {r['reason']}")
        lines.append("")

    # Graph probes grouped by domain
    for domain_label, probe_list in [
        ("Space Race", SPACE_PROBES),
        ("Renaissance", RENAISSANCE_PROBES),
    ]:
        lines.append(f"### Graph Probes — {domain_label}")
        for g in graph_results:
            if g.get("name") not in probe_list:
                continue
            gname = g.get("name", "?")
            conns = g.get("connections", [])
            eid = g.get("id", "")
            lines.append(f"**{gname}** ({len(conns)} connections)")
            for conn in conns:
                edge = conn["edge"]
                node = conn["node"]
                d = "→" if edge.get("from") == eid else "←"
                label = node.get("name", node.get("content", "")[:50])
                lines.append(f"- {d} [{edge['table']}] {label}")
            lines.append("")

    lines.extend(["---", ""])
    return "\n".join(lines)


# ════════════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════════════


def _install_signal_handlers(state: BenchState):
    def handler(signum, frame):
        state.data["interrupted"] = True
        state.save()
        print(f"\n!! signal {signum} — saving resumable state and stopping")
        raise BenchInterrupt()

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)


def main():
    if len(sys.argv) < 2:
        print("Usage: python experiments/run_experiment.py <name> [notes]")
        print("Resumable: rerun the same <name> to continue an interrupted run.")
        sys.exit(1)

    name = sys.argv[1]
    notes = sys.argv[2] if len(sys.argv) > 2 else ""
    data_dir = os.path.join(EXPERIMENTS_DIR, "data", name)
    os.makedirs(data_dir, exist_ok=True)

    state = BenchState(os.path.join(data_dir, "state.json"), name, notes)
    notes = notes or state.data.get("notes", "")
    if state.data.get("phase") == "done":
        print(f"Experiment {name} is already complete. Use a new name for another run.")
        return
    resuming = not state.fresh
    now = time.time()
    previous_session = state.data.get("session_started_epoch")
    if previous_session:
        state.data["accumulated_s"] = state.data.get("accumulated_s", 0) + max(
            0, now - previous_session
        )
    state.data["session_started_epoch"] = now
    state.data["current"] = None
    state.save()
    print(f"=== Experiment: {name} {'(RESUMING) ' if resuming else ''}===")
    print(
        f"=== {len(SPACE_SNIPPETS)} space + {len(RENAISSANCE_SNIPPETS)} renaissance snippets ==="
    )
    print(f"=== monitor: {state.path} | log is line-buffered ===")

    _install_signal_handlers(state)
    client = make_client()
    base = f"http://localhost:{DEFAULT_PORT}"
    total_t0 = time.time()

    try:
        with ServerSupervisor(
            name,
            DEFAULT_PORT,
            "-experiment",
            wipe=not resuming,
            log_path=os.path.join(data_dir, "server.log"),
        ) as sup:
            # Phase 1: Ingest
            print(f"\n=== INGEST ({len(SNIPPETS)} snippets) ===")
            ingest_phase(client, sup, base, state)

            # Phase 2: Recall
            print(f"\n=== RECALL ({len(RECALL_QUESTIONS)} questions) ===")
            recall_phase(client, sup, base, state)

            # Phase 3: Graph probes
            print(f"\n=== GRAPH PROBES ({len(GRAPH_PROBES)} entities) ===")
            graph_phase(client, sup, base, state)

        ingest_results = state.data["ingest"]
        recall_results = state.data["recall"]
        graph_results = state.data["graph"]

        # Write phase artifacts (idempotent; also available mid-run via state.json)
        for fname, payload in (
            ("ingest.json", ingest_results),
            ("recall.json", recall_results),
            ("graph.json", graph_results),
        ):
            with open(os.path.join(data_dir, fname), "w") as f:
                json.dump(payload, f, indent=2, default=str)

        # Phase 4: LLM-judged scoring (resumable per section)
        print(
            f"\n=== LLM JUDGE ({len(SPACE_ASSERTIONS) + len(RENAISSANCE_ASSERTIONS) + len(CROSS_DOMAIN_ASSERTIONS)} assertions) ==="
        )
        llm_scores = judge_phase(state, graph_results)
        with open(os.path.join(data_dir, "llm_scores.json"), "w") as f:
            json.dump(llm_scores, f, indent=2)

        # Summarize
        recall_scores = score_recall(recall_results)
        latency = collect_latency(ingest_results, recall_results, graph_results)
        session_start = state.data.get("session_started_epoch", total_t0)
        total_elapsed = state.data.get("accumulated_s", 0) + max(
            0, time.time() - session_start
        )

        with open(os.path.join(data_dir, "latency.json"), "w") as f:
            json.dump({"total_s": round(total_elapsed, 2), **latency}, f, indent=2)

        s_pass = sum(1 for r in llm_scores["space"] if r["pass"])
        r_pass = sum(1 for r in llm_scores["renaissance"] if r["pass"])
        c_pass = sum(1 for r in llm_scores["cross_domain"] if r["pass"])

        print(f"\n=== RESULTS ({total_elapsed:.0f}s total) ===")
        print(f"Space relationships:       {s_pass}/{len(SPACE_ASSERTIONS)}")
        print(f"Renaissance relationships: {r_pass}/{len(RENAISSANCE_ASSERTIONS)}")
        print(f"Cross-domain isolation:    {c_pass}/{len(CROSS_DOMAIN_ASSERTIONS)}")
        print(
            f"Recall w/ context:         {recall_scores['with_context']}/{recall_scores['total']}"
        )
        print(
            f"Latency: ingest p95 {latency['ingest'].get('p95_s', '—')}s, "
            f"recall p95 {latency['recall'].get('p95_s', '—')}s"
        )

        # Write journal (only once per completed run)
        journal_path = os.path.join(EXPERIMENTS_DIR, "JOURNAL.md")
        report = format_report(
            name,
            notes,
            llm_scores,
            recall_scores,
            graph_results,
            latency,
            total_elapsed,
        )
        heading = f"## {name}\n"
        if os.path.exists(journal_path):
            with open(journal_path) as f:
                existing = f.read()
        else:
            existing = ""
        if heading in existing:
            start = existing.index(heading)
            next_heading = existing.find("\n## ", start + len(heading))
            end = len(existing) if next_heading < 0 else next_heading + 1
            existing = existing[:start] + report + existing[end:]
        else:
            existing = existing.rstrip() + "\n\n" + report
        with open(journal_path, "w") as f:
            f.write(existing)
        state.data["accumulated_s"] = round(total_elapsed, 2)
        state.data["session_started_epoch"] = None
        state.data["phase"] = "done"
        state.save()
        print(f"\n✓ Journal updated: {journal_path}")
        print(f"✓ Data saved: {data_dir}/")

    except BenchInterrupt:
        state.data["accumulated_s"] = state.data.get("accumulated_s", 0) + round(
            time.time() - state.data.get("session_started_epoch", total_t0), 2
        )
        state.data["session_started_epoch"] = None
        state.save()
        print(
            f"✓ Interrupted — state is saved. Resume with: experiments/benchctl.sh resume {name}"
        )
        return
    finally:
        client.close()


if __name__ == "__main__":
    main()
