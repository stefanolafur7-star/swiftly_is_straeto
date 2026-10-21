# Strætó

## Um

Eftirlit með strætó leiðum og stoppum.

Fyrir hverja leið sem valin er eru búnir til þrír sensorar fyrir hvern vagn á þeirri leið:

- Frávik: sekúndur sem vagninn er frá áætlun (- ef hann er á undan áætlun)
- Næsta stopp: Nafn á næstu stoppistöð
- Device tracker: Staðsetning á vagni birtist á korti

Fyrir hvert stopp sem valið er er búinn til einn sensor:

- Næsti vagn: Áætlaður tími á komu næsta vagns.

## Uppsetning

Áður en hægt er að fara í gegnum uppsetningu þarf að sækja um API key frá Strætó. Sjá upplýsingar [hér](https://www.straeto.is/en/about-straeto/open-data/real-time-data)

Til að geta bætt Strætó við þarf að vera með [HACS](https://hacs.xyz/docs/use/download/download/)

Inní HACS þarf að smella á þrípunktana efst hægramegin og velja Custom repositories. Repository er https://github.com/finnure/swiftly_is_straeto og type er Integration. Endurræsið Home Assistant eftir þetta.

Næst er farið í Settings -> Devices & services -> Add Integration og leitað eftir Swiftly IS Straeto og settur inn API lykill.

Ef API lykill er í lagi er viðbótin tilbúin og hægt að bæta við leiðum til að fylgjast með. Veljið + efst hægramegin og veljið leið úr fellilista og síðan Next. Þá er hægt að velja stoppistöðvar sem á að fylgjast með, enga eða fleiri.

## Rate limit

Þegar þið fáið upplýsingar um API lykil fáið þið að vita hversu mörg köll eru innifalin. Default eru 180 á 15 mín, eða 12 á mínútu. Viðbótin sækir ný gögn á 30 sekúndna fresti.

- Upplýsingar um alla vagna á öllum völdum leiðum eru innifalin í einu kalli
- Hver stoppistöð sem valin er þarf eitt kall. Vegna þess er ekki öruggt að velja fleiri en 5 stopp.
- Ef sama stoppistöð er valin fyrir fleiri en eina leið kostar það bara eitt kall.

## Lyklar með aðeins GTFS-rt aðgang

Sumir API lyklar frá Swiftly hafa bara aðgang að GTFS-rt straumunum (trip updates og vehicle positions) en ekki JSON rauntímaviðmótunum. Viðbótin finnur það sjálf og sækir þá rauntímann úr GTFS-rt straumunum í staðinn, án aukapakka.

- Öll gögn kosta þá tvö köll á 30 sekúndna fresti, sama hversu mörg stopp eru valin. Upplýsingar um leiðir og stopp eru sóttar á 6 tíma fresti.
- GTFS-rt hefur engin block númer, svo vagnar eru auðkenndir með númeri vagnsins.
- Frávik er jákvætt þegar vagninn er á eftir áætlun.
